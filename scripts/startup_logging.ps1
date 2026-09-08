[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)]
    [string]$Event,

    [string]$Message = ""
)

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$LogDir = Join-Path $RepoRoot "logs"
$LogFile = Join-Path $LogDir "startup.log"

if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}

$line = "{0} | {1} | {2}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Event, $Message
Add-Content -Path $LogFile -Value $line -Encoding UTF8

Write-Host $line -ForegroundColor DarkGray
