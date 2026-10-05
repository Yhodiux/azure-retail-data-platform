$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
# Spark 3.5.4 image also fixes the Linux Python/Java runtime used by the tests.
$image = "apache/spark:3.5.4@sha256:af0a7250929c5282a4acd4eac17a55206a6a7a8ba2230dacdbbae7e62427f56d"
docker run --rm --network none --hostname retail-core --add-host retail-core:127.0.0.1 `
    --mount "type=bind,source=$projectRoot/src,target=/workspace/src,readonly" `
    --mount "type=bind,source=$projectRoot/tests,target=/workspace/tests,readonly" `
    --workdir /tmp `
    --env PYTHONPATH=/opt/spark/python:/opt/spark/python/lib/py4j-0.10.9.7-src.zip:/workspace/src `
    --env PYTHONDONTWRITEBYTECODE=1 --env SPARK_LOCAL_IP=127.0.0.1 `
    --env PYTHONWARNINGS=ignore::ResourceWarning `
    $image python3 -m unittest discover -s /workspace/tests -v
if ($LASTEXITCODE -ne 0) {
    throw "Portable core tests failed with exit code $LASTEXITCODE"
}
