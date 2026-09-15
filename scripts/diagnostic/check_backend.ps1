Write-Host "Backend Check"
Write-Host "-------------"

Write-Host "Import test"
python -c "from backend.main import create_app; app=create_app(); print(app.title, app.version)" 2>&1

Write-Host ""
Write-Host "Port 8766"
$listener = Get-NetTCPConnection -LocalPort 8766 -State Listen -ErrorAction SilentlyContinue
if ($listener) {
    Write-Host "[PASS] Backend port 8766"
} else {
    Write-Warning "[WARN] Backend port 8766 is not listening"
}

try {
    Invoke-RestMethod "http://127.0.0.1:8766/api/health" -TimeoutSec 3 | Out-String
    Write-Host "[PASS] Health endpoint"
} catch {
    Write-Warning "[WARN] Health endpoint unavailable"
}
