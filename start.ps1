param(
    # Conda environment used by the Python backend and local RAG runtime.
    [string]$CondaEnvironment = "aitrans",

    # Optional debugging modes. By default Backend + Tauri start together.
    [switch]$BackendOnly,
    [switch]$TauriOnly,

    # Dependency installation is intentionally opt-in so normal startup stays
    # fast and does not depend on registry/network availability.
    [switch]$InstallDependencies
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

# ============================================================
# AITranslator - development launcher
# ============================================================
#
# This script is the fast daily-development counterpart of:
#   scripts/verify_and_start.ps1
#
# verify_and_start.ps1 owns synchronization, tests, lint/build and Cargo checks.
# start.ps1 performs only lightweight local preflight checks and launches the
# current working tree. It deliberately performs no git fetch/pull so the app
# can be started while offline or while GitHub/npm networking is unavailable.

$RepoRoot = $PSScriptRoot
$DesktopDir = Join-Path $RepoRoot "apps\desktop"
$TauriDir = Join-Path $DesktopDir "src-tauri"
$ExpectedBranch = "WebReBuild"

function Assert-LastExitCode {
    param([string]$Message)

    if ($LASTEXITCODE -ne 0) {
        throw $Message
    }
}

function Resolve-CondaExecutable {
    $command = Get-Command conda -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }

    $candidates = @(
        "$env:USERPROFILE\anaconda3\Scripts\conda.exe",
        "$env:USERPROFILE\miniconda3\Scripts\conda.exe",
        "C:\ProgramData\anaconda3\Scripts\conda.exe",
        "C:\ProgramData\miniconda3\Scripts\conda.exe"
    )

    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) {
            return $candidate
        }
    }

    throw "Conda executable was not found. Install Conda or add it to PATH."
}

function Resolve-PowerShellExecutable {
    $pwsh = Get-Command pwsh.exe -ErrorAction SilentlyContinue
    if ($pwsh) {
        return $pwsh.Source
    }

    $windowsPowerShell = Get-Command powershell.exe -ErrorAction SilentlyContinue
    if ($windowsPowerShell) {
        return $windowsPowerShell.Source
    }

    throw "Neither pwsh.exe nor powershell.exe was found."
}

function ConvertTo-EncodedPowerShellCommand {
    param([string]$Command)

    # PowerShell -EncodedCommand expects UTF-16LE input.
    return [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($Command))
}

function ConvertTo-PowerShellSingleQuotedLiteral {
    param([string]$Value)

    return $Value.Replace("'", "''")
}

function Assert-CommandAvailable {
    param(
        [string]$Name,
        [string]$InstallHint
    )

    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "$Name was not found. $InstallHint"
    }
}

if ($BackendOnly -and $TauriOnly) {
    throw "-BackendOnly and -TauriOnly cannot be used together."
}

if (-not (Test-Path (Join-Path $DesktopDir "package.json"))) {
    throw "Desktop package.json was not found at '$DesktopDir'. Run this script from the AITranslator repository root."
}

if (-not (Test-Path (Join-Path $TauriDir "tauri.conf.json"))) {
    throw "Tauri configuration was not found at '$TauriDir'."
}

Write-Host ""
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host " AITranslator development launcher" -ForegroundColor Cyan
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host "Repository        : $RepoRoot"
Write-Host "Desktop directory : $DesktopDir"
Write-Host "Conda environment : $CondaEnvironment"
Write-Host ""

# ------------------------------------------------------------
# 1. Activate the same Conda environment used by verification
# ------------------------------------------------------------

$CondaExe = Resolve-CondaExecutable

(& $CondaExe "shell.powershell" "hook") |
    Out-String |
    Invoke-Expression

conda activate $CondaEnvironment
Assert-LastExitCode "Failed to activate Conda environment '$CondaEnvironment'."

if ($env:CONDA_DEFAULT_ENV -ne $CondaEnvironment) {
    throw "Wrong Conda environment: '$env:CONDA_DEFAULT_ENV'. Expected '$CondaEnvironment'."
}

python -c "import sys; print('Python executable  :', sys.executable); print('Python version     :', sys.version.split()[0])"
Assert-LastExitCode "Python is not usable inside Conda environment '$CondaEnvironment'."

# ------------------------------------------------------------
# 2. Lightweight local preflight only (no network/git sync)
# ------------------------------------------------------------

Assert-CommandAvailable "node" "Install the project Node.js toolchain first."
Assert-CommandAvailable "npm" "Install the project Node.js toolchain first."
if (-not $BackendOnly) {
    Assert-CommandAvailable "cargo" "Install Rust/Cargo before starting the Tauri desktop app."
}

Set-Location $RepoRoot
$CurrentBranch = ""
try {
    $CurrentBranch = (git branch --show-current 2>$null).Trim()
}
catch {
    $CurrentBranch = ""
}

if ($CurrentBranch) {
    $CurrentCommit = (git rev-parse --short HEAD 2>$null).Trim()
    Write-Host "Git branch         : $CurrentBranch"
    Write-Host "Git HEAD           : $CurrentCommit"
    if ($CurrentBranch -ne $ExpectedBranch) {
        Write-Host "WARNING: current branch is '$CurrentBranch'; normal development target is '$ExpectedBranch'." -ForegroundColor Yellow
    }
}
else {
    Write-Host "Git status         : unavailable (startup will continue)." -ForegroundColor DarkYellow
}

Set-Location $DesktopDir
$NodeModules = Join-Path $DesktopDir "node_modules"
if ($InstallDependencies) {
    Write-Host ""
    Write-Host "Installing frontend dependencies..." -ForegroundColor Yellow
    Write-Host "-> npm ci --no-audit --prefer-offline" -ForegroundColor Cyan
    npm ci --no-audit --prefer-offline
    Assert-LastExitCode "Frontend dependency installation failed."
}
elseif (-not (Test-Path $NodeModules)) {
    throw "Frontend node_modules is missing. Run '.\start.ps1 -InstallDependencies' once, or run 'npm ci' from apps\desktop."
}

# Do not load the actual Qwen models here. Import-level probes are sufficient
# to surface the most common local RAG environment mistakes before startup.
$RagRuntimeProbe = @'
import importlib.metadata as metadata
import importlib.util as util

print("Docling           :", metadata.version("docling") if util.find_spec("docling") else "not installed (pypdf fallback)")
print("sentence-transformers:", metadata.version("sentence-transformers") if util.find_spec("sentence_transformers") else "missing")
if util.find_spec("torch"):
    import torch
    print("Torch             :", torch.__version__)
    print("Torch CUDA        :", torch.version.cuda)
    print("CUDA available    :", torch.cuda.is_available())
    print("GPU               :", torch.cuda.get_device_name(0) if torch.cuda.is_available() else "none")
else:
    print("Torch             : missing")
    print("CUDA available    : False")
'@
python -c $RagRuntimeProbe
Assert-LastExitCode "Unable to inspect local RAG Python dependencies."

Write-Host ""
Write-Host "Preflight complete. No git fetch/pull or verification suite was run." -ForegroundColor Green

# ------------------------------------------------------------
# 3. Launch Backend + Tauri concurrently
# ------------------------------------------------------------

$PowerShellExe = Resolve-PowerShellExecutable
$EscapedCondaExe = ConvertTo-PowerShellSingleQuotedLiteral $CondaExe
$EscapedCondaEnvironment = ConvertTo-PowerShellSingleQuotedLiteral $CondaEnvironment
$EscapedDesktopDir = ConvertTo-PowerShellSingleQuotedLiteral $DesktopDir

$BackendCommand = @"
`$ErrorActionPreference = 'Stop'
(& '$EscapedCondaExe' 'shell.powershell' 'hook') | Out-String | Invoke-Expression
conda activate '$EscapedCondaEnvironment'
Set-Location '$EscapedDesktopDir'
Write-Host ''
Write-Host '====================================' -ForegroundColor Cyan
Write-Host ' AITranslator Backend' -ForegroundColor Cyan
Write-Host ' Conda: $EscapedCondaEnvironment' -ForegroundColor Cyan
Write-Host ' Directory: $EscapedDesktopDir' -ForegroundColor Cyan
Write-Host '====================================' -ForegroundColor Cyan
Write-Host ''
npm run backend:dev
"@

$TauriCommand = @"
`$ErrorActionPreference = 'Stop'
(& '$EscapedCondaExe' 'shell.powershell' 'hook') | Out-String | Invoke-Expression
conda activate '$EscapedCondaEnvironment'
Set-Location '$EscapedDesktopDir'
Write-Host ''
Write-Host '====================================' -ForegroundColor Magenta
Write-Host ' AITranslator Tauri Desktop' -ForegroundColor Magenta
Write-Host ' Conda: $EscapedCondaEnvironment' -ForegroundColor Magenta
Write-Host ' Directory: $EscapedDesktopDir' -ForegroundColor Magenta
Write-Host ' Vite: managed by tauri beforeDevCommand' -ForegroundColor Magenta
Write-Host '====================================' -ForegroundColor Magenta
Write-Host ''
npm run tauri:dev
"@

$Processes = [System.Collections.Generic.List[object]]::new()

if (-not $TauriOnly) {
    $BackendEncoded = ConvertTo-EncodedPowerShellCommand $BackendCommand
    $BackendProcess = Start-Process `
        -FilePath $PowerShellExe `
        -ArgumentList "-NoExit", "-EncodedCommand", $BackendEncoded `
        -PassThru
    $Processes.Add([PSCustomObject]@{ Name = "Backend"; Process = $BackendProcess })
}

if (-not $BackendOnly) {
    $TauriEncoded = ConvertTo-EncodedPowerShellCommand $TauriCommand
    $TauriProcess = Start-Process `
        -FilePath $PowerShellExe `
        -ArgumentList "-NoExit", "-EncodedCommand", $TauriEncoded `
        -PassThru
    $Processes.Add([PSCustomObject]@{ Name = "Tauri"; Process = $TauriProcess })
}

Write-Host ""
foreach ($entry in $Processes) {
    Write-Host ("{0,-18}: {1}" -f ("$($entry.Name) PID"), $entry.Process.Id) -ForegroundColor Green
}
Write-Host ""

if (-not $BackendOnly -and -not $TauriOnly) {
    Write-Host "Backend and Tauri were launched concurrently in separate PowerShell windows." -ForegroundColor Green
    Write-Host "Tauri starts Vite through tauri.conf.json beforeDevCommand; do not start a third Vite process." -ForegroundColor Cyan
}
elseif ($BackendOnly) {
    Write-Host "Backend-only development process launched." -ForegroundColor Green
}
else {
    Write-Host "Tauri-only development process launched." -ForegroundColor Green
}

Write-Host "Use scripts\verify_and_start.ps1 for synchronization and formal verification." -ForegroundColor DarkCyan
Write-Host "Keep the launched PowerShell window(s) open while testing." -ForegroundColor Cyan

Set-Location $RepoRoot
