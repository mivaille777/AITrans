[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$CondaEnvironment = if ($env:AITRANS_DIAGNOSTIC_CONDA_ENV) {
    $env:AITRANS_DIAGNOSTIC_CONDA_ENV
} else {
    "aitrans"
}
$Conda = Get-Command conda -ErrorAction SilentlyContinue

Write-Host "Backend Check"
Write-Host "-------------"

Push-Location $Root
try {
    if ($null -ne $Conda) {
        $ImportResult = & $Conda.Source run -n $CondaEnvironment python -c "from backend.main import create_app; app=create_app(); print(app.title, app.version)" 2>&1
    }
    else {
        $ImportResult = & python -c "from backend.main import create_app; app=create_app(); print(app.title, app.version)" 2>&1
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Backend import failed: $ImportResult"
    }
    Write-Host "[PASS] Backend import: $ImportResult"
}
finally {
    Pop-Location
}

$Listener = Get-NetTCPConnection -LocalPort 8766 -State Listen -ErrorAction SilentlyContinue
if (-not $Listener) {
    Write-Warning "[WARN] Backend port 8766 is not listening; live health check skipped"
    return
}

$Health = Invoke-RestMethod "http://127.0.0.1:8766/health" -TimeoutSec 3
if ($Health.status -ne "ok" -or $Health.service -ne "aitrans-backend") {
    throw "Backend /health returned an unexpected response"
}
Write-Host "[PASS] Backend /health"
