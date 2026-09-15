param(
    [string]$CondaEnvironment = "aitrans"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$RepoRoot = Split-Path -Parent $PSScriptRoot

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

function Assert-LastExitCode {
    param([string]$Message)

    if ($LASTEXITCODE -ne 0) {
        throw $Message
    }
}

function Get-TorchRuntimeState {
    param(
        [string]$CondaExe,
        [string]$Environment
    )

    $probe = @'
import json
import importlib.util

if importlib.util.find_spec("torch") is None:
    print(json.dumps({"installed": False, "version": "", "cuda_version": "", "cuda_available": False, "gpu": ""}))
else:
    import torch
    cuda_available = bool(torch.cuda.is_available())
    print(json.dumps({
        "installed": True,
        "version": str(torch.__version__),
        "cuda_version": str(torch.version.cuda or ""),
        "cuda_available": cuda_available,
        "gpu": torch.cuda.get_device_name(0) if cuda_available else "",
    }))
'@

    $json = (& $CondaExe run -n $Environment python -c $probe | Out-String).Trim()
    Assert-LastExitCode "Unable to inspect the PyTorch runtime in Conda environment '$Environment'."
    return $json | ConvertFrom-Json
}

function Convert-CudaVersionToWheelIndex {
    param([string]$CudaVersion)

    $normalized = ($CudaVersion ?? "").Trim()
    if ($normalized -notmatch '^(\d+)\.(\d+)$') {
        return ""
    }
    return "cu$($Matches[1])$($Matches[2])"
}

function Get-PublicTorchVersion {
    param([string]$TorchVersion)

    return (($TorchVersion ?? "") -split '\+', 2)[0]
}

$CondaExe = Resolve-CondaExecutable

Write-Host "Repository        : $RepoRoot"
Write-Host "Conda environment : $CondaEnvironment"
Write-Host ""

$TorchBefore = Get-TorchRuntimeState -CondaExe $CondaExe -Environment $CondaEnvironment
if ($TorchBefore.installed) {
    Write-Host "PyTorch before setup: $($TorchBefore.version)" -ForegroundColor Cyan
    Write-Host "CUDA before setup   : $($TorchBefore.cuda_available) $($TorchBefore.cuda_version) $($TorchBefore.gpu)" -ForegroundColor Cyan
}
else {
    Write-Host "PyTorch before setup: not installed" -ForegroundColor DarkYellow
}

Write-Host ""
Write-Host "Installing optional scientific PDF ingestion dependencies..." -ForegroundColor Yellow

Push-Location $RepoRoot
try {
    & $CondaExe run -n $CondaEnvironment python -m pip install -e ".[rag-advanced]"
    Assert-LastExitCode "Failed to install the rag-advanced optional dependency."

    $TorchAfterInstall = Get-TorchRuntimeState -CondaExe $CondaExe -Environment $CondaEnvironment

    # pip may resolve Docling's PyTorch dependency from the default PyPI index
    # and replace an existing CUDA wheel with a CPU-only wheel. If CUDA worked
    # before setup, restore the exact public torch version from the matching
    # official PyTorch CUDA wheel index.
    if ($TorchBefore.cuda_available -and -not $TorchAfterInstall.cuda_available) {
        $TorchPublicVersion = Get-PublicTorchVersion -TorchVersion $TorchBefore.version
        $CudaWheelIndex = Convert-CudaVersionToWheelIndex -CudaVersion $TorchBefore.cuda_version

        if (-not $TorchPublicVersion -or -not $CudaWheelIndex) {
            throw "Docling dependency resolution replaced CUDA PyTorch with a CPU build, and the previous CUDA wheel could not be identified automatically."
        }

        $TorchIndexUrl = "https://download.pytorch.org/whl/$CudaWheelIndex"
        Write-Host ""
        Write-Host "Docling dependency resolution replaced CUDA PyTorch with a CPU build." -ForegroundColor Yellow
        Write-Host "Restoring torch $TorchPublicVersion from $TorchIndexUrl ..." -ForegroundColor Yellow

        & $CondaExe run -n $CondaEnvironment python -m pip install --force-reinstall "torch==$TorchPublicVersion" --index-url $TorchIndexUrl
        Assert-LastExitCode "Failed to restore the CUDA-enabled PyTorch wheel after Docling installation."
    }

    Write-Host ""
    Write-Host "Verifying Docling import..." -ForegroundColor Yellow
    & $CondaExe run -n $CondaEnvironment python -c "import importlib.metadata as m; import docling; print('Docling:', m.version('docling'))"
    Assert-LastExitCode "Docling import verification failed."

    Write-Host ""
    Write-Host "Verifying local embedding stack after dependency resolution..." -ForegroundColor Yellow
    & $CondaExe run -n $CondaEnvironment python -c "import importlib.metadata as m, torch, transformers, sentence_transformers; print('torch:', torch.__version__); print('Torch CUDA:', torch.version.cuda); print('transformers:', transformers.__version__); print('sentence-transformers:', m.version('sentence-transformers')); print('CUDA:', torch.cuda.is_available()); print('GPU:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'none')"
    Assert-LastExitCode "Docling installed, but the local embedding Python stack is no longer importable."

    $TorchFinal = Get-TorchRuntimeState -CondaExe $CondaExe -Environment $CondaEnvironment
    if ($TorchBefore.cuda_available -and -not $TorchFinal.cuda_available) {
        throw "CUDA was available before Docling setup but is unavailable afterwards. Refusing to report the RAG environment as ready."
    }

    Write-Host ""
    Write-Host "Advanced PDF ingestion is ready." -ForegroundColor Green
    Write-Host "OCR and formula enrichment remain disabled by default; layout and table parsing are enabled."
    Write-Host "Docling parsing runs on CPU by default; CUDA remains reserved for Qwen embedding/reranking."
}
finally {
    Pop-Location
}
