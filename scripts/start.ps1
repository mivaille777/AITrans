[CmdletBinding()]
param(
    [ValidateSet("Desktop", "Web", "Backend")]
    [string]$Mode = "Desktop",
    [string]$CondaEnvironment = "aitrans",
    [string]$ApiHost = "127.0.0.1",
    [ValidateRange(1, 65535)] [int]$ApiPort = 8766,
    [string]$FrontendHost = "127.0.0.1",
    [ValidateRange(1, 65535)] [int]$FrontendPort = 5173,
    [switch]$SkipInstall,
    [switch]$EnableSandbox,
    [string]$SandboxImage = "aitrans-python-sandbox:v1",
    [switch]$OpenBrowser,
    [ValidateRange(5, 300)] [int]$StartupTimeoutSeconds = 45
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$DesktopDir = Join-Path $RepoRoot "apps\desktop"
$ApiBaseUrl = "http://{0}:{1}" -f $ApiHost, $ApiPort

function Resolve-CondaExecutable {
    if ($env:CONDA_EXE -and (Test-Path -LiteralPath $env:CONDA_EXE)) { return $env:CONDA_EXE }
    $command = Get-Command conda -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    foreach ($candidate in @(
        "$env:USERPROFILE\anaconda3\Scripts\conda.exe",
        "$env:USERPROFILE\miniconda3\Scripts\conda.exe",
        "C:\ProgramData\anaconda3\Scripts\conda.exe",
        "C:\ProgramData\miniconda3\Scripts\conda.exe"
    )) {
        if (Test-Path -LiteralPath $candidate) { return $candidate }
    }
    throw "Conda executable was not found."
}

$env:AITRANS_API_HOST = $ApiHost
$env:AITRANS_API_PORT = [string]$ApiPort
$env:AITRANS_FRONTEND_ORIGIN = "http://{0}:{1}" -f $FrontendHost, $FrontendPort
$env:AITRANS_SANDBOX_ENABLED = if ($EnableSandbox) { "true" } else { "false" }
$env:AITRANS_SANDBOX_IMAGE = $SandboxImage
$env:VITE_API_BASE_URL = $ApiBaseUrl

if ($Mode -eq "Desktop") {
    if ($ApiPort -ne 8766 -or $FrontendPort -ne 5173) {
        throw "Desktop mode currently uses API port 8766 and renderer port 5173. Use Web mode for custom ports."
    }
    $forward = @{ CondaEnvironment = $CondaEnvironment }
    if (-not $SkipInstall -and -not (Test-Path (Join-Path $DesktopDir "node_modules"))) {
        $forward.InstallDependencies = $true
    }
    & (Join-Path $RepoRoot "start-electron.ps1") @forward
    exit $LASTEXITCODE
}

$CondaExe = Resolve-CondaExecutable

if ($Mode -eq "Backend") {
    Set-Location $RepoRoot
    & $CondaExe run --no-capture-output -n $CondaEnvironment python -m backend
    exit $LASTEXITCODE
}

if (-not $SkipInstall -and -not (Test-Path (Join-Path $DesktopDir "node_modules"))) {
    Push-Location $DesktopDir
    try {
        npm ci --no-audit --prefer-offline
        if ($LASTEXITCODE -ne 0) { throw "Frontend dependency installation failed." }
    } finally { Pop-Location }
}

$BackendProcess = Start-Process -FilePath $CondaExe -WorkingDirectory $RepoRoot -ArgumentList @(
    "run", "--no-capture-output", "-n", $CondaEnvironment, "python", "-m", "backend"
) -PassThru

try {
    Start-Sleep -Seconds 1
    Set-Location $DesktopDir
    if ($OpenBrowser) {
        Start-Process ("http://{0}:{1}" -f $FrontendHost, $FrontendPort) | Out-Null
    }
    npm run dev -- --host $FrontendHost --port $FrontendPort
}
finally {
    if ($BackendProcess -and -not $BackendProcess.HasExited) {
        if ($IsWindows) {
            taskkill.exe /PID $BackendProcess.Id /T /F | Out-Null
        } else {
            Stop-Process -Id $BackendProcess.Id -Force -ErrorAction SilentlyContinue
        }
    }
}

exit $LASTEXITCODE
