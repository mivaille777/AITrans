$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$RepoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$RuntimeDir = Join-Path $RepoRoot "runtime"
$LogFile = Join-Path $RuntimeDir "startup.log"

function Write-StartupLog {
    param(
        [Parameter(Mandatory=$true)]
        [string]$Message,
        [ValidateSet("INFO","WARN","ERROR")]
        [string]$Level = "INFO"
    )

    New-Item -ItemType Directory -Force -Path $RuntimeDir | Out-Null

    $line = "[{0}] [{1}] {2}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Level, $Message
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
    Write-Host $line
}

function Initialize-StartupLogging {
    Write-StartupLog "AITranslator startup begin"
}

Export-ModuleMember -Function Write-StartupLog, Initialize-StartupLogging
