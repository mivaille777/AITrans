$ErrorActionPreference = "Stop"

$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "../..")).Path
$imageName = "aitrans-python-sandbox:v1"

Push-Location $repositoryRoot
try {
    docker build --tag $imageName --file sandbox/python/Dockerfile sandbox/python
    if ($LASTEXITCODE -ne 0) {
        throw "Docker image build failed with exit code $LASTEXITCODE."
    }

    docker image inspect $imageName | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Docker image inspection failed with exit code $LASTEXITCODE."
    }
}
finally {
    Pop-Location
}
