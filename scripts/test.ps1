param(
    [switch]$Install,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$PytestArgs
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Push-Location $repoRoot
try {
    $pythonVersion = (& python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')").Trim()
    if ($LASTEXITCODE -ne 0) {
        throw "Python is unavailable. Activate the project's Python 3.11 environment first."
    }
    if ($pythonVersion -ne "3.11") {
        throw "Python 3.11 is required for this project. Current version: $pythonVersion"
    }

    if ($Install) {
        Write-Host "Installing project and test dependencies..."
        & python -m pip install -e ".[dev]"
        if ($LASTEXITCODE -ne 0) {
            throw "Dependency installation failed with exit code $LASTEXITCODE."
        }
    }

    Write-Host "Running local pytest with Python $pythonVersion..."
    & python -m pytest -q --ignore=tests/manual @PytestArgs
    if ($LASTEXITCODE -ne 0) {
        throw "pytest failed with exit code $LASTEXITCODE."
    }

    Write-Host "Local pytest passed."
}
finally {
    Pop-Location
}
