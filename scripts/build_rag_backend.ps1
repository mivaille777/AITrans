[CmdletBinding()]
param(
    [switch]$Clean
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$specPath = Join-Path $repoRoot "aitrans_backend.spec"
$buildRoot = Join-Path $repoRoot "build\rag-sidecar"
$distRoot = Join-Path $repoRoot "dist"
$distApp = Join-Path $distRoot "AITransBackend"
$exePath = Join-Path $distApp "AITransBackend.exe"
$condaPython = if ($env:CONDA_PREFIX) { Join-Path $env:CONDA_PREFIX "python.exe" } else { "" }
$python = if ($condaPython -and (Test-Path -LiteralPath $condaPython -PathType Leaf)) {
    $condaPython
} else {
    (Get-Command python -ErrorAction Stop).Source
}

function Remove-ExactBuildTarget {
    param([Parameter(Mandatory = $true)][string]$Target)

    $resolvedTarget = [IO.Path]::GetFullPath($Target)
    $resolvedRoot = [IO.Path]::GetFullPath($repoRoot).TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
    if (-not $resolvedTarget.StartsWith($resolvedRoot, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove a path outside the repository: $resolvedTarget"
    }
    if (Test-Path -LiteralPath $resolvedTarget) {
        Remove-Item -LiteralPath $resolvedTarget -Recurse -Force
    }
}

if ($Clean) {
    Remove-ExactBuildTarget -Target $buildRoot
    Remove-ExactBuildTarget -Target $distApp
}

foreach ($module in @("PyInstaller", "sentence_transformers", "transformers", "qdrant_client")) {
    & $python -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('$module') else 1)"
    if ($LASTEXITCODE -ne 0) {
        throw "Missing packaging dependency '$module'. Install .[build] and aitranslator-rag-requirements.txt first."
    }
}

& $python -m PyInstaller `
    --clean `
    --noconfirm `
    --distpath $distRoot `
    --workpath $buildRoot `
    $specPath
if ($LASTEXITCODE -ne 0) {
    throw "RAG backend sidecar build failed with exit code $LASTEXITCODE."
}
if (-not (Test-Path -LiteralPath $exePath -PathType Leaf)) {
    throw "Expected sidecar executable was not produced: $exePath"
}

$forbiddenModelFiles = @(
    Get-ChildItem -LiteralPath $distApp -Recurse -File |
        Where-Object {
            $_.Name -in @("model.safetensors", "pytorch_model.bin") -or
            $_.Extension -eq ".gguf"
        }
)
if ($forbiddenModelFiles.Count -gt 0) {
    $names = ($forbiddenModelFiles | ForEach-Object { $_.FullName }) -join ", "
    throw "The sidecar bundle contains forbidden model weights: $names"
}

$previousHubOffline = $env:HF_HUB_OFFLINE
$previousTransformersOffline = $env:TRANSFORMERS_OFFLINE
try {
    $env:HF_HUB_OFFLINE = "1"
    $env:TRANSFORMERS_OFFLINE = "1"
    $process = Start-Process `
        -FilePath $exePath `
        -ArgumentList "--runtime-smoke-test" `
        -WindowStyle Hidden `
        -Wait `
        -PassThru
} finally {
    if ($null -eq $previousHubOffline) {
        Remove-Item Env:HF_HUB_OFFLINE -ErrorAction SilentlyContinue
    } else {
        $env:HF_HUB_OFFLINE = $previousHubOffline
    }
    if ($null -eq $previousTransformersOffline) {
        Remove-Item Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue
    } else {
        $env:TRANSFORMERS_OFFLINE = $previousTransformersOffline
    }
}
if ($process.ExitCode -ne 0) {
    throw "Packaged offline runtime smoke test failed with exit code $($process.ExitCode)."
}

Write-Host "RAG backend sidecar build passed: $exePath"
Write-Host "Managed model weights remain external: %LOCALAPPDATA%\AITrans\models"
