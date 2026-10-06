<#
.SYNOPSIS
Starts the current AITrans Electron desktop and its managed FastAPI backend.
.DESCRIPTION
Uses a named Conda environment in child processes without changing the caller's
active environment. Use -CheckOnly for preflight without opening the application.
#>
[CmdletBinding()]
param(
    [ValidatePattern('^[A-Za-z0-9_.-]+$')]
    [string]$CondaEnvironment = "aitrans",
    [switch]$InstallDependencies,
    [switch]$SkipRagProbe,
    [switch]$Verify,
    [switch]$BackendOnly,
    [switch]$BuiltRuntime,
    [switch]$CheckOnly,
    [switch]$EnableSandbox,
    [string]$SandboxImage = "aitrans-python-sandbox:v1"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$RepoRoot = $PSScriptRoot
$DesktopDir = Join-Path $RepoRoot "apps\desktop"

function Resolve-CondaExecutable {
    if ($env:CONDA_EXE -and (Test-Path -LiteralPath $env:CONDA_EXE -PathType Leaf)) {
        return $env:CONDA_EXE
    }
    $command = Get-Command conda.exe -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($command) { return $command.Source }
    foreach ($candidate in @(
        "$env:USERPROFILE\anaconda3\Scripts\conda.exe",
        "$env:USERPROFILE\miniconda3\Scripts\conda.exe",
        "C:\ProgramData\anaconda3\Scripts\conda.exe",
        "C:\ProgramData\miniconda3\Scripts\conda.exe"
    )) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) { return $candidate }
    }
    throw "Conda was not found. Set CONDA_EXE to its conda.exe path."
}

function Assert-NativeSuccess {
    param([string]$Message)
    if ($LASTEXITCODE -ne 0) { throw "$Message (exit code $LASTEXITCODE)." }
}

if ($BackendOnly -and $BuiltRuntime) {
    throw "-BackendOnly and -BuiltRuntime cannot be used together."
}
if ($BackendOnly -and ($InstallDependencies -or $Verify)) {
    throw "Desktop dependency installation/verification cannot be combined with -BackendOnly."
}
if ($CheckOnly -and ($InstallDependencies -or $Verify)) {
    throw "-CheckOnly does not install dependencies or run the full verification suite."
}

$CondaExe = Resolve-CondaExecutable
$PreviousEnvironment = @{}
foreach ($name in @("AITRANS_REPO_ROOT", "AITRANS_PYTHON_EXECUTABLE", "AITRANS_RENDERER_URL", "AITRANS_SANDBOX_ENABLED", "AITRANS_SANDBOX_IMAGE")) {
    $PreviousEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
}

Push-Location $RepoRoot
try {
    $PythonOutput = & $CondaExe run --no-capture-output -n $CondaEnvironment python -c "import sys; print(sys.executable)"
    Assert-NativeSuccess "Cannot use Python in Conda environment '$CondaEnvironment'"
    $PythonExecutable = ([string]($PythonOutput | Select-Object -Last 1)).Trim()
    if (-not (Test-Path -LiteralPath $PythonExecutable -PathType Leaf)) {
        throw "Conda did not resolve a usable Python executable: '$PythonExecutable'."
    }
    $env:AITRANS_REPO_ROOT = $RepoRoot
    $env:AITRANS_PYTHON_EXECUTABLE = $PythonExecutable
    if ($EnableSandbox) {
        $env:AITRANS_SANDBOX_ENABLED = "true"
        $env:AITRANS_SANDBOX_IMAGE = $SandboxImage
    }

    Write-Host "AITrans source launcher" -ForegroundColor Cyan
    Write-Host "Repository : $RepoRoot"
    Write-Host "Python     : $PythonExecutable"
    Write-Host "Conda      : $CondaEnvironment"
    Write-Host "Mode       : $(if ($BackendOnly) { 'Backend' } elseif ($BuiltRuntime) { 'Desktop preview' } else { 'Desktop development' })"

    $BackendProbe = @'
import importlib.util
import sys
required = ("fastapi", "uvicorn", "numpy")
missing = [name for name in required if importlib.util.find_spec(name) is None]
if not (3, 11) <= sys.version_info[:2] < (3, 13):
    raise SystemExit("AITrans requires Python 3.11 or 3.12.")
if missing:
    raise SystemExit("Missing backend dependencies: " + ", ".join(missing) + ". Install the project in this Conda environment first.")
print("Backend dependency preflight passed.")
'@
    $BackendProbe | & $CondaExe run --no-capture-output -n $CondaEnvironment python -
    Assert-NativeSuccess "Backend dependency preflight failed"

    if (-not $SkipRagProbe) {
        $RagProbe = @'
import importlib.metadata as metadata
import importlib.util
from backend.rag.runtime_probe import probe_local_vector_runtime
print("FAISS runtime:", probe_local_vector_runtime())
for module, distribution in (("docling", "docling"), ("sentence_transformers", "sentence-transformers")):
    print(distribution + ":", metadata.version(distribution) if importlib.util.find_spec(module) else "not installed")
if importlib.util.find_spec("torch"):
    import torch
    print("Torch:", torch.__version__, "CUDA available:", torch.cuda.is_available())
    if torch.cuda.is_available():
        print("GPU:", torch.cuda.get_device_name(0))
print("Local RAG runtime preflight passed (temporary smoke-test store only).")
'@
        $RagProbe | & $CondaExe run --no-capture-output -n $CondaEnvironment python -
        Assert-NativeSuccess "Local FAISS/RAG preflight failed; see scripts/install_faiss.ps1"
    }

    if (-not $BackendOnly) {
        $NodeExe = (Get-Command node.exe -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
        $NpmExe = (Get-Command npm.cmd -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
        $NodeMajor = [int]((& $NodeExe --version).Trim().TrimStart("v").Split(".")[0])
        Assert-NativeSuccess "Cannot run Node.js"
        if ($NodeMajor -lt 24) { throw "Use the project Node.js 24+ toolchain." }
        $Package = Get-Content -LiteralPath (Join-Path $DesktopDir "package.json") -Raw | ConvertFrom-Json
        foreach ($scriptName in @("desktop:dev", "desktop:preview", "desktop:verify")) {
            if (-not $Package.scripts.PSObject.Properties[$scriptName]) {
                throw "Missing current desktop npm command: $scriptName."
            }
        }

        Push-Location $DesktopDir
        try {
            if ($InstallDependencies) {
                & $CondaExe run --no-capture-output -n $CondaEnvironment $NpmExe ci --no-audit --prefer-offline
                Assert-NativeSuccess "Desktop dependency installation failed"
            }
            foreach ($entry in @("node_modules\.bin\vite.cmd", "node_modules\electron\cli.js")) {
                if (-not (Test-Path -LiteralPath (Join-Path $DesktopDir $entry) -PathType Leaf)) {
                    throw "Desktop dependencies are missing. Run .\start.ps1 -InstallDependencies from the repository root."
                }
            }
            if ($Verify) {
                & $CondaExe run --no-capture-output -n $CondaEnvironment $NpmExe run desktop:verify
                Assert-NativeSuccess "Desktop verification failed"
            }
            if ($CheckOnly) {
                Write-Host "Startup preflight passed; no application was started." -ForegroundColor Green
                return
            }

            Remove-Item Env:AITRANS_RENDERER_URL -ErrorAction SilentlyContinue
            $DesktopCommand = if ($BuiltRuntime) { "desktop:preview" } else { "desktop:dev" }
            Write-Host "Starting $DesktopCommand; Electron owns the backend lifecycle." -ForegroundColor Green
            & $CondaExe run --no-capture-output -n $CondaEnvironment $NpmExe run $DesktopCommand
            Assert-NativeSuccess "Desktop runtime exited with an error"
        }
        finally { Pop-Location }
    }
    else {
        if ($CheckOnly) {
            Write-Host "Backend startup preflight passed; no application was started." -ForegroundColor Green
            return
        }
        Write-Host "Starting FastAPI backend (python -m backend)." -ForegroundColor Green
        & $CondaExe run --no-capture-output -n $CondaEnvironment python -m backend
        Assert-NativeSuccess "Backend runtime exited with an error"
    }
}
finally {
    foreach ($name in $PreviousEnvironment.Keys) {
        [Environment]::SetEnvironmentVariable($name, $PreviousEnvironment[$name], "Process")
    }
    Pop-Location
}
