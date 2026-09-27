param(
    [string]$CondaEnvironment = "aitrans",
    [switch]$InstallDependencies,
    [switch]$SkipRagProbe
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$RepoRoot = $PSScriptRoot
$DesktopDir = Join-Path $RepoRoot "apps\desktop"
$ExpectedBranch = "electronrebuild"

function Assert-LastExitCode {
    param([string]$Message)

    if ($LASTEXITCODE -ne 0) {
        throw $Message
    }
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

if (-not (Test-Path (Join-Path $DesktopDir "package.json"))) {
    throw "Desktop package.json was not found at '$DesktopDir'."
}

Assert-CommandAvailable "git" "Install Git and add it to PATH."
Assert-CommandAvailable "node" "Install the project Node.js toolchain first."
Assert-CommandAvailable "npm" "Install the project Node.js toolchain first."

Set-Location $RepoRoot
$CurrentBranch = (git branch --show-current 2>$null).Trim()
Assert-LastExitCode "Unable to resolve the current Git branch."

if ($CurrentBranch -ne $ExpectedBranch) {
    throw "This launcher is dedicated to '$ExpectedBranch'. Current branch is '$CurrentBranch'."
}

$CurrentCommit = (git rev-parse --short HEAD 2>$null).Trim()
Assert-LastExitCode "Unable to resolve the current Git commit."

$CondaExe = Resolve-CondaExecutable
(& $CondaExe "shell.powershell" "hook") |
    Out-String |
    Invoke-Expression

conda activate $CondaEnvironment
Assert-LastExitCode "Failed to activate Conda environment '$CondaEnvironment'."

if ($env:CONDA_DEFAULT_ENV -ne $CondaEnvironment) {
    throw "Wrong Conda environment: '$env:CONDA_DEFAULT_ENV'. Expected '$CondaEnvironment'."
}

$PythonExecutable = (python -c "import sys; print(sys.executable)").Trim()
Assert-LastExitCode "Python is not usable inside Conda environment '$CondaEnvironment'."

Write-Host ""
Write-Host "================================================" -ForegroundColor Cyan
Write-Host " AITrans ElectronRebuild development launcher" -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan
Write-Host "Repository        : $RepoRoot"
Write-Host "Branch            : $CurrentBranch"
Write-Host "Git HEAD           : $CurrentCommit"
Write-Host "Desktop directory : $DesktopDir"
Write-Host "Conda environment : $CondaEnvironment"
Write-Host "Python executable : $PythonExecutable"
Write-Host "Desktop runtime   : Electron"
Write-Host ""

Set-Location $DesktopDir

if ($InstallDependencies) {
    Write-Host "Installing desktop dependencies..." -ForegroundColor Yellow
    npm ci --no-audit --prefer-offline
    Assert-LastExitCode "Desktop dependency installation failed."
}
elseif (-not (Test-Path (Join-Path $DesktopDir "node_modules"))) {
    throw "apps\desktop\node_modules is missing. Run '.\start-electronrebuild.ps1 -InstallDependencies' once."
}

if (-not $SkipRagProbe) {
    $RagRuntimeProbe = @'
import importlib.metadata as metadata
import importlib.util as util

print("Docling              :", metadata.version("docling") if util.find_spec("docling") else "not installed (pypdf fallback)")
print("sentence-transformers:", metadata.version("sentence-transformers") if util.find_spec("sentence_transformers") else "missing")
if util.find_spec("torch"):
    import torch
    print("Torch                :", torch.__version__)
    print("Torch CUDA           :", torch.version.cuda)
    print("CUDA available       :", torch.cuda.is_available())
    print("GPU                  :", torch.cuda.get_device_name(0) if torch.cuda.is_available() else "none")
else:
    print("Torch                : missing")
    print("CUDA available       : False")
'@
    python -c $RagRuntimeProbe
    Assert-LastExitCode "Unable to inspect local RAG Python dependencies."
}

$PreviousRepoRoot = $env:AITRANS_REPO_ROOT
$PreviousPythonExecutable = $env:AITRANS_PYTHON_EXECUTABLE

try {
    # Electron owns the FastAPI lifecycle in this branch. Passing explicit
    # absolute values avoids PATH/cwd ambiguity when Electron spawns Python.
    $env:AITRANS_REPO_ROOT = $RepoRoot
    $env:AITRANS_PYTHON_EXECUTABLE = $PythonExecutable

    Write-Host ""
    Write-Host "Starting Electron development runtime..." -ForegroundColor Green
    Write-Host "Vite             : managed by scripts/electron-dev.mjs" -ForegroundColor DarkCyan
    Write-Host "FastAPI backend  : managed by Electron BackendProcessManager" -ForegroundColor DarkCyan
    Write-Host "Backend health   : http://127.0.0.1:8766/health" -ForegroundColor DarkCyan
    Write-Host "Cargo / Tauri    : not required by this launcher" -ForegroundColor DarkCyan
    Write-Host ""

    npm run electron:dev
    if ($LASTEXITCODE -ne 0) {
        $ElectronExitCode = $LASTEXITCODE
        Write-Host ""
        Write-Host "Electron development runtime failed with exit code $ElectronExitCode." -ForegroundColor Red
        Write-Host "The root cause is in the npm / Vite / Electron output immediately above this message." -ForegroundColor Yellow
        Write-Host "For an isolated compile check run: cd apps\desktop; npm run electron:compile" -ForegroundColor DarkCyan
        exit $ElectronExitCode
    }
}
finally {
    if ($null -eq $PreviousRepoRoot) {
        Remove-Item Env:AITRANS_REPO_ROOT -ErrorAction SilentlyContinue
    }
    else {
        $env:AITRANS_REPO_ROOT = $PreviousRepoRoot
    }

    if ($null -eq $PreviousPythonExecutable) {
        Remove-Item Env:AITRANS_PYTHON_EXECUTABLE -ErrorAction SilentlyContinue
    }
    else {
        $env:AITRANS_PYTHON_EXECUTABLE = $PreviousPythonExecutable
    }

    Set-Location $RepoRoot
}
