[CmdletBinding()]
param(
    [string]$CondaEnvironment = "aitrans"
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ReportDir = Join-Path $Root "runtime\diagnose"
New-Item -ItemType Directory -Force -Path $ReportDir | Out-Null
$Report = Join-Path $ReportDir ("diagnose-{0}.txt" -f (Get-Date -Format "yyyyMMdd-HHmmss"))
$PowerShellExecutable = (Get-Process -Id $PID).Path
$Failures = [System.Collections.Generic.List[string]]::new()
$env:AITRANS_DIAGNOSTIC_CONDA_ENV = $CondaEnvironment

function Add-Report {
    param([string]$Text)

    $Text | Tee-Object -FilePath $Report -Append
}

function Run-Check {
    param(
        [string]$Name,
        [string]$ScriptPath
    )

    Add-Report ""
    Add-Report "[$Name]"
    if (-not (Test-Path -LiteralPath $ScriptPath -PathType Leaf)) {
        Add-Report "[FAIL] Missing checker: $ScriptPath"
        $Failures.Add($Name)
        return
    }

    $Output = & $PowerShellExecutable `
        -NoLogo `
        -NoProfile `
        -NonInteractive `
        -ExecutionPolicy Bypass `
        -File $ScriptPath 2>&1
    $ExitCode = $LASTEXITCODE
    $Output | Tee-Object -FilePath $Report -Append
    if ($ExitCode -ne 0) {
        Add-Report "[FAIL] $Name checker exited with code $ExitCode"
        $Failures.Add($Name)
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
if ($Failures.Count -gt 0) {
    Add-Report "Overall: FAIL ($($Failures -join ', '))"
    Add-Report "Report saved: $Report"
    exit 1
}

Add-Report "Overall: PASS"
Add-Report "Report saved: $Report"
