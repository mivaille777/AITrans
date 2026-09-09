$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

function Assert-ExitCode([string]$Step) {
    if ($LASTEXITCODE -ne 0) {
        throw "$Step failed with exit code $LASTEXITCODE"
    }
}

Write-Host "`n=== AITrans Stage 5 verification ===" -ForegroundColor Cyan
Write-Host "Repository: $repoRoot"

Write-Host "`n[1/4] Backend import" -ForegroundColor Cyan
python -c "import backend.main; from backend.services.multi_agent_runtime_bridge import MultiAgentRuntimeBridge; print('stage5-backend-import-ok')"
Assert-ExitCode "Backend import"

Write-Host "`n[2/4] Stage 5 backend regression tests" -ForegroundColor Cyan
$tests = @(
    "tests/agent/test_multi_agent_stage5_6.py",
    "tests/agent/test_multi_agent_stage5_7.py",
    "tests/agent/test_multi_agent_stage5_8.py",
    "tests/agent/test_multi_agent_stage5_9.py"
)
python -m pytest @tests -q
Assert-ExitCode "Stage 5 backend tests"

Write-Host "`n[3/4] Desktop tests" -ForegroundColor Cyan
Push-Location "apps/desktop"
try {
    if (-not (Test-Path "node_modules")) {
        Write-Host "node_modules not found; installing locked frontend dependencies..." -ForegroundColor Yellow
        npm ci
        Assert-ExitCode "npm ci"
    }

    npm test
    Assert-ExitCode "Desktop tests"

    Write-Host "`n[4/4] Desktop production build" -ForegroundColor Cyan
    npm run build
    Assert-ExitCode "Desktop production build"
}
finally {
    Pop-Location
}

Write-Host "`n=== Stage 5 verification passed ===" -ForegroundColor Green
Write-Host "Next: start the backend with 'python -m backend', then start the desktop frontend with 'cd apps/desktop; npm run dev'." -ForegroundColor Green
