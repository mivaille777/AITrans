Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$LogDirectory = Join-Path (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path "logs"
$StartupLog = Join-Path $LogDirectory "startup.log"

function Initialize-StartupLogging {
    if (-not (Test-Path -LiteralPath $LogDirectory)) {
        New-Item -ItemType Directory -Path $LogDirectory | Out-Null
    }
}

function Write-StartupEvent {
    param(
        [string]$Event,
        [string]$Message
    )

    Initialize-StartupLogging
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') | INFO | $Event | $Message"
    Add-Content -LiteralPath $StartupLog -Value $line
}
