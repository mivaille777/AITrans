[CmdletBinding()]
param()

$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
$ReportDir = Join-Path $Root "runtime\diagnose"
New-Item -ItemType Directory -Force -Path $ReportDir | Out-Null
$Report = Join-Path $ReportDir ("diagnose-{0}.txt" -f (Get-Date -Format "yyyyMMdd-HHmmss"))

function Add-Report($Text) {
    $Text | Tee-Object -FilePath $Report -Append
}

Add-Report "===================================="
Add-Report "AITranslator Diagnosis Report"
Add-Report "===================================="
Add-Report "Time: $(Get-Date)"
Add-Report "Root: $Root"

Add-Report ""
Add-Report "[Environment]"
python --version 2>&1 | Tee-Object -FilePath $Report -Append
node --version 2>&1 | Tee-Object -FilePath $Report -Append
cargo --version 2>&1 | Tee-Object -FilePath $Report -Append

Add-Report ""
Add-Report "[Backend]"
try {
    python -c "from backend.main import create_app; app=create_app(); print(app.title, app.version)" 2>&1 | Tee-Object -FilePath $Report -Append
} catch {
    Add-Report "Backend import failed"
}

try {
    Invoke-RestMethod "http://127.0.0.1:8766/api/health" -TimeoutSec 3 | Out-String | Add-Content $Report
    Add-Report "Backend health OK"
} catch {
    Add-Report "Backend health unavailable"
}

Add-Report ""
Add-Report "[Frontend]"
if (Test-Path (Join-Path $Root "apps\desktop\node_modules")) {
    Add-Report "node_modules exists"
} else {
    Add-Report "node_modules missing"
}

Add-Report ""
Add-Report "Report saved: $Report"
