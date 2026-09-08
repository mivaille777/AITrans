[CmdletBinding()]
param(
    [switch]$SkipFrontend,
    [switch]$SkipBackend
)

$ErrorActionPreference = "Stop"

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

Write-Host "===================================="
Write-Host "AITranslator Smoke Test"
Write-Host "Root: $Root"
Write-Host "===================================="

Write-Host "[1/5] Python config and logging"
Push-Location $Root
try {
    python -c "from backend.config import settings; from backend.core import get_logger; print(settings.APP_ENV); get_logger('smoke')('')"
}
finally {
    Pop-Location
}

if (-not $SkipBackend) {
    Write-Host "[2/5] Backend import"
    Push-Location $Root
    try {
        python -c "from backend.main import create_app; app=create_app(); print(app.title, app.version)"
    }
    finally {
        Pop-Location
    }
}

Write-Host "[3/5] Runtime directories"
$runtime = Join-Path $Root "runtime"
$logs = Join-Path $Root "logs"

if (Test-Path $runtime) { Write-Host "runtime exists" }
else { Write-Warning "runtime missing" }

if (Test-Path $logs) { Write-Host "logs exists" }
else { Write-Warning "logs missing" }

if (-not $SkipFrontend) {
    Write-Host "[4/5] Frontend package check"
    if (Test-Path (Join-Path $Root "apps\desktop\package.json")) {
        Write-Host "frontend package OK"
    }
    else {
        throw "frontend package.json missing"
    }
}

Write-Host "[5/5] Smoke test completed"
Write-Host "PASS"
