[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$LogDirectory = Join-Path $RepoRoot "logs"
$StartupLog = Join-Path $LogDirectory "startup.log"

function Initialize-StartupLogging {
    if (-not (Test-Path -LiteralPath $LogDirectory)) {
        New-Item -ItemType Directory -Path $LogDirectory -Force | Out-Null
    }

    if (-not (Test-Path -LiteralPath $StartupLog)) {
        New-Item -ItemType File -Path $StartupLog -Force | Out-Null
    }
}

function Write-StartupEvent {
    param(
        [Parameter(Mandatory=$true)]
        [string]$Event,

        [Parameter(Mandatory=$true)]
        [string]$Message
    )

    Initialize-StartupLogging

    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') | INFO | $Event | $Message"

    Add-Content -Path $StartupLog -Value $line
    Write-Host $line -ForegroundColor DarkGray
}

Initialize-StartupLogging
