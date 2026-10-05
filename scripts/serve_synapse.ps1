param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[a-z0-9-]+-ondemand\.sql\.azuresynapse\.net$')]
    [string]$Server,
    [string]$EvidencePath = '.tools/synapse/serving-validation.json'
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$sqlRoot = Join-Path $projectRoot 'serving/synapse'
Add-Type -AssemblyName System.Data

# Existing Azure CLI sign-in; the access token is never printed or persisted.
$sqlToken = & az account get-access-token --resource https://database.windows.net/ --query accessToken -o tsv
if ($LASTEXITCODE -ne 0 -or -not $sqlToken) { throw 'Cannot obtain the existing Entra SQL access token' }

function Open-Database([string]$Database) {
    $connection = [System.Data.SqlClient.SqlConnection]::new()
    $connection.ConnectionString = "Server=tcp:$Server,1433;Initial Catalog=$Database;Encrypt=True;TrustServerCertificate=False;Connection Timeout=30;Application Name=AzureRetailServerless"
    $connection.AccessToken = $sqlToken
    try { $connection.Open() } catch { $connection.Dispose(); throw }
    return $connection
}

function Batches([string]$Filename) {
    $sql = [IO.File]::ReadAllText((Join-Path $sqlRoot $Filename))
    return @([regex]::Split($sql, '(?im)^\s*GO\s*(?:--[^\r\n]*)?$') | Where-Object { $_.Trim() })
}

function Execute-Script($Connection, [string]$Filename) {
    foreach ($batch in (Batches $Filename)) {
        $command = $Connection.CreateCommand()
        try {
            $command.CommandText = $batch
            $command.CommandTimeout = 180
            $command.ExecuteNonQuery() | Out-Null
        } finally { $command.Dispose() }
    }
}

function Read-Script($Connection, [string]$Filename) {
    $sets = [Collections.Generic.List[object]]::new()
    foreach ($batch in (Batches $Filename)) {
        $command = $Connection.CreateCommand()
        $reader = $null
        try {
            $command.CommandText = $batch
            $command.CommandTimeout = 180
            $reader = $command.ExecuteReader()
            do {
                if ($reader.FieldCount -eq 0) { continue }
                $columns = [Collections.Generic.List[string]]::new()
                for ($i = 0; $i -lt $reader.FieldCount; $i++) { $columns.Add($reader.GetName($i)) }
                $rows = [Collections.Generic.List[object]]::new()
                while ($reader.Read()) {
                    $row = [ordered]@{}
                    for ($i = 0; $i -lt $reader.FieldCount; $i++) {
                        $value = if ($reader.IsDBNull($i)) { $null } else { $reader.GetValue($i) }
                        $row[$reader.GetName($i)] = $value
                    }
                    $rows.Add([pscustomobject]$row)
                }
                $sets.Add([pscustomobject]@{columns=$columns.ToArray(); rows=$rows.ToArray()})
            } while ($reader.NextResult())
        } finally {
            if ($reader) { $reader.Dispose() }
            $command.Dispose()
        }
    }
    return $sets.ToArray()
}

function Ensure-MasterKey($Connection) {
    $check = $Connection.CreateCommand()
    try {
        $check.CommandText = "SELECT COUNT(*) FROM sys.symmetric_keys WHERE name = N'##MS_DatabaseMasterKey##'"
        $check.CommandTimeout = 180
        if ([int]$check.ExecuteScalar() -gt 0) { return }
    } finally { $check.Dispose() }

    # Generate only for a missing key. No password in files, environment, logs,
    # command-line arguments or evidence. The SQL server retains its key.
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    $bytes = [byte[]]::new(32)
    $keyPassword = $null
    $command = $null
    try {
        $rng.GetBytes($bytes)
        $keyPassword = 'Aa1!' + [Convert]::ToBase64String($bytes)
        foreach ($batch in (Batches '01_master_key.sql')) {
            $command = $Connection.CreateCommand()
            $command.CommandText = $batch
            $command.CommandTimeout = 180
            $parameter = $command.Parameters.Add('@MasterKeyPassword', [System.Data.SqlDbType]::NVarChar, 128)
            $parameter.Value = $keyPassword
            $command.ExecuteNonQuery() | Out-Null
            $command.Parameters.Clear()
            $command.Dispose()
            $command = $null
            $parameter = $null
        }
    } catch {
        # Do not emit SQL exception details that might include dynamic DDL.
        throw 'Database master key initialization failed; the runtime password was not logged or saved.'
    } finally {
        if ($command) {
            $command.Parameters.Clear()
            $command.Dispose()
        }
        $parameter = $null
        $keyPassword = $null
        [Array]::Clear($bytes, 0, $bytes.Length)
        $rng.Dispose()
    }
}

$master = Open-Database 'master'
try { Execute-Script $master '01_database.sql' } finally { $master.Dispose() }
$database = Open-Database 'retail_analytics'
try {
    Ensure-MasterKey $database
    Execute-Script $database '02_gold_source.sql'
    Execute-Script $database '03_views.sql'
    $checks = @(Read-Script $database '04_validate.sql')
    $expected = @{sales_by_state=27; sales_by_category=74; sales_by_payment_type=5; top_sellers=3095; top_customers=96135}
    $countSets = @($checks | Where-Object { $_.columns -contains 'row_count' })
    if ($countSets.Count -ne 1 -or @($countSets[0].rows).Count -ne 5) { throw 'Expected five SQL counts' }
    foreach ($row in $countSets[0].rows) {
        if (-not $expected.ContainsKey($row.dataset) -or $row.row_count -ne $expected[$row.dataset]) {
            throw ('Unexpected SQL count for ' + $row.dataset)
        }
    }
    if (@($countSets[0].rows.dataset | Select-Object -Unique).Count -ne 5) { throw 'Duplicate count dataset' }
    $viewSets = @($checks | Where-Object { $_.columns -contains 'view_name' })
    if ($viewSets.Count -ne 1 -or @($viewSets[0].rows).Count -ne 5) { throw 'Expected five dbo views' }
    $analytics = @(Read-Script $database '05_analytics.sql')
    if ($analytics.Count -ne 5) { throw 'Expected five analytical query results' }
    $report = @{result='SUCCESS'; serverless_endpoint=$Server; database='retail_analytics';
                authentication='Microsoft Entra access token'; storage_identity='Synapse Managed Identity';
                validation=$checks; analytical_queries=$analytics; checked_at_utc=[DateTime]::UtcNow.ToString('o')}
    $parent = Split-Path $EvidencePath -Parent
    if ($parent) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
    $report | ConvertTo-Json -Depth 15 | Set-Content -LiteralPath $EvidencePath -Encoding UTF8
    Write-Output 'SUCCESS: five views queried; counts match Gold; five analytical queries executed'
} finally {
    $database.Dispose()
    $sqlToken = $null
}
