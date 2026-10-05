$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
python -B -m unittest discover -s (Join-Path $projectRoot "integration_tests/unit") -v
if ($LASTEXITCODE -ne 0) { throw "Integration contract tests failed" }
$image = "apache/spark:3.5.4@sha256:af0a7250929c5282a4acd4eac17a55206a6a7a8ba2230dacdbbae7e62427f56d"
docker run --rm --network none --hostname retail-integration --add-host retail-integration:127.0.0.1 `
    --mount "type=bind,source=$projectRoot/src,target=/workspace/src,readonly" `
    --mount "type=bind,source=$projectRoot/tooling,target=/workspace/tooling,readonly" `
    --mount "type=bind,source=$projectRoot/integration,target=/workspace/integration,readonly" `
    --mount "type=bind,source=$projectRoot/integration_tests,target=/workspace/integration_tests,readonly" `
    --workdir /tmp --env PYTHONPATH=/opt/spark/python:/opt/spark/python/lib/py4j-0.10.9.7-src.zip:/workspace/src:/workspace `
    --env PYTHONDONTWRITEBYTECODE=1 --env SPARK_LOCAL_IP=127.0.0.1 --env PYTHONWARNINGS=ignore::ResourceWarning `
    $image python3 -m unittest discover -s /workspace/integration_tests/spark -v
if ($LASTEXITCODE -ne 0) { throw "Local Spark adapter tests failed" }
