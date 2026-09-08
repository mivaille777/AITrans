$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$RuntimeDir = Join-Path $RepoRoot "runtime"
$LogFile = Join-Path $RuntimeDir "startup.log"

function Write-StartupLog {
    param(
        [Parameter(Mandatory=$true)]
        [string]$Message
    )

    New-Item -ItemType Directory -Force -Path $RuntimeDir | Out-Null

    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') | $Message"

    Add-Content -Path $LogFile -Value $line -Encoding UTF8
}

Export-ModuleMember -Function Write-StartupLog
