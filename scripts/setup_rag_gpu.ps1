[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$requirementsPath = Join-Path $repoRoot "aitranslator-rag-requirements.txt"

if ($env:CONDA_DEFAULT_ENV -ne "aitrans") {
    throw "Activate the 'aitrans' Conda environment before running this script."
}

if (-not (Test-Path -LiteralPath $requirementsPath -PathType Leaf)) {
    throw "RAG requirements file not found: $requirementsPath"
}

python -m pip install torch==2.11.0 --index-url https://download.pytorch.org/whl/cu130
if ($LASTEXITCODE -ne 0) {
    throw "Failed to install the CUDA PyTorch baseline."
}

python -m pip install -r $requirementsPath
if ($LASTEXITCODE -ne 0) {
    throw "Failed to install RAG runtime dependencies."
}

python -m pip check
if ($LASTEXITCODE -ne 0) {
    throw "RAG dependency validation failed."
}

python -c "import torch; print(f'torch={torch.__version__}'); print(f'cuda_available={torch.cuda.is_available()}'); print(f'gpu={torch.cuda.get_device_name(0) if torch.cuda.is_available() else \"none\"}')"
if ($LASTEXITCODE -ne 0) {
    throw "Failed to inspect the installed PyTorch runtime."
}
