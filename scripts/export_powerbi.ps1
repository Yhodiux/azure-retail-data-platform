param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[a-z0-9-]+-ondemand\.sql\.azuresynapse\.net$')]
    [string]$Server,
    [string]$OutputDirectory
)
$ErrorActionPreference = 'Stop'
if (-not $OutputDirectory) { $OutputDirectory = Join-Path (Split-Path $PSScriptRoot -Parent) 'powerbi/data' }
Add-Type -AssemblyName System.Data
$expected = [ordered]@{
    sales_by_state = 27
    sales_by_category = 74
    sales_by_payment_type = 5
    top_sellers = 3095
    top_customers = 96135
}
$culture = [Globalization.CultureInfo]::InvariantCulture
function Csv-Field($Value) {
    if ($null -eq $Value -or $Value -is [DBNull]) { return '' }
    if ($Value -is [DateTime]) {
        $text = $Value.ToString('yyyy-MM-dd HH:mm:ss.ffffff', $culture)
    } elseif ($Value -is [IFormattable]) {
        $text = $Value.ToString($null, $culture)
    } else { $text = [string]$Value }
    return '"' + $text.Replace('"', '""') + '"'
}

# Reuse the existing Azure CLI sign-in; retain the SQL token only in memory.
$token = & az account get-access-token --resource https://database.windows.net/ --query accessToken -o tsv
if ($LASTEXITCODE -ne 0 -or -not $token) { throw 'Cannot obtain Entra SQL access token.' }
$connection = [System.Data.SqlClient.SqlConnection]::new()
$connection.ConnectionString = "Server=tcp:$Server,1433;Initial Catalog=retail_analytics;Encrypt=True;TrustServerCertificate=False;Connection Timeout=30;Application Name=AzureRetailPowerBIExport"
$connection.AccessToken = $token
try {
    $connection.Open()
    New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
    foreach ($name in $expected.Keys) {
        $path = Join-Path $OutputDirectory ($name + '.csv')
        if (Test-Path -LiteralPath $path) { throw "Refusing to overwrite existing file: $path" }
        $command = $connection.CreateCommand()
        $reader = $null
        $writer = $null
        $complete = $false
        try {
            # Fixed allowlist above; no DDL, transformation, filter or extra metric.
            $command.CommandText = "SELECT * FROM dbo.vw_$name"
            $command.CommandTimeout = 300
            $reader = $command.ExecuteReader()
            $columns = @()
            for ($i = 0; $i -lt $reader.FieldCount; $i++) { $columns += $reader.GetName($i) }
            $writer = [IO.StreamWriter]::new($path, $false, [Text.UTF8Encoding]::new($false))
            $writer.WriteLine((($columns | ForEach-Object { Csv-Field $_ }) -join ','))
            $count = 0
            while ($reader.Read()) {
                $fields = for ($i = 0; $i -lt $reader.FieldCount; $i++) { Csv-Field ($reader.GetValue($i)) }
                $writer.WriteLine(($fields -join ','))
                $count++
            }
            if ($count -ne $expected[$name]) { throw "Unexpected count for ${name}: $count; expected $($expected[$name])" }
            $writer.Dispose()
            $writer = $null
            $complete = $true
            [pscustomobject]@{file=$path; columns=$columns; rows=$count; bytes=(Get-Item -LiteralPath $path).Length} | ConvertTo-Json -Compress
        } finally {
            if ($writer) { $writer.Dispose() }
            if ($reader) { $reader.Dispose() }
            $command.Dispose()
            if (-not $complete -and (Test-Path -LiteralPath $path)) { Remove-Item -LiteralPath $path }
        }
    }
} finally {
    $connection.Dispose()
    $token = $null
}
