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

function Run-Check($Name, $ScriptPath) {
    Add-Report ""
    Add-Report "[$Name]"
    if (Test-Path $ScriptPath) {
        & $ScriptPath 2>&1 | Tee-Object -FilePath $Report -Append
    } else {
        Add-Report "Missing checker: $ScriptPath"
    }
}

Add-Report "===================================="
Add-Report "AITranslator Diagnosis Report"
Add-Report "===================================="
Add-Report "Time: $(Get-Date)"
Add-Report "Root: $Root"

Run-Check "Environment" (Join-Path $PSScriptRoot "diagnostic\check_environment.ps1")
Run-Check "Backend" (Join-Path $PSScriptRoot "diagnostic\check_backend.ps1")
Run-Check "Frontend" (Join-Path $PSScriptRoot "diagnostic\check_frontend.ps1")
Run-Check "Database" (Join-Path $PSScriptRoot "diagnostic\check_database.ps1")
Run-Check "LLM" (Join-Path $PSScriptRoot "diagnostic\check_llm.ps1")

Add-Report ""
Add-Report "Report saved: $Report"
