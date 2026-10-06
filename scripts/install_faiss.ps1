[CmdletBinding()]
param(
    [string]$PythonExecutable = $env:AITRANS_PYTHON_EXECUTABLE,
    [string]$CondaExecutable = $env:CONDA_EXE
)

$ErrorActionPreference = 'Stop'
if (-not $PythonExecutable) {
    $PythonExecutable = if ($env:CONDA_PREFIX) { Join-Path $env:CONDA_PREFIX 'python.exe' } else { (Get-Command python).Source }
}
$prefix = (& $PythonExecutable -c 'import sys; print(sys.prefix)').Trim()
if ($LASTEXITCODE -ne 0) { throw 'Cannot execute the selected Python environment' }
if (-not $CondaExecutable) {
    $candidate = Join-Path (Split-Path (Split-Path $prefix -Parent) -Parent) 'Scripts\conda.exe'
    if (Test-Path -LiteralPath $candidate) { $CondaExecutable = $candidate }
    elseif (Get-Command conda -ErrorAction SilentlyContinue) { $CondaExecutable = (Get-Command conda).Source }
}

# A functioning GPU installation already contains the CPU implementation.
& $PythonExecutable -c 'import faiss,numpy as np; r=faiss.StandardGpuResources(); r.setTempMemory(67108864); i=faiss.index_cpu_to_gpu(r,0,faiss.IndexFlatIP(2)); i.add(np.array([[1.,0.]],dtype=np.float32)); assert i.search(np.array([[1.,0.]],dtype=np.float32),1)[1][0,0]==0; assert np.allclose(np.eye(2,dtype=np.float32) @ np.eye(2,dtype=np.float32),np.eye(2))'
if ($LASTEXITCODE -eq 0) { Write-Host 'FAISS GPU numerical probe passed; keeping installed build.'; exit 0 }

$gpuAvailable = $false
if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) {
    $devices = & nvidia-smi --query-gpu=name --format=csv,noheader 2>$null
    $gpuAvailable = $LASTEXITCODE -eq 0 -and [bool]$devices
}
if ($gpuAvailable -and $CondaExecutable -and (Test-Path -LiteralPath (Join-Path $prefix 'conda-meta'))) {
    # Pin the existing Python/SSL builds so FAISS does not replace the host
    # interpreter. This Windows CUDA build requires NumPy 1.x.
    # OpenBLAS avoids the MKL 2026 / existing PyTorch OpenMP DLL incompatibility
    # observed during real MaxSim matrix multiplication on Windows.
    $pins = @('faiss-gpu=1.9.0', 'numpy=1.26.4', 'libblas=*=*openblas', 'libcblas=*=*openblas', 'liblapack=*=*openblas')
    foreach ($package in @('python', 'openssl', 'ca-certificates')) {
        $records = @(Get-ChildItem -LiteralPath (Join-Path $prefix 'conda-meta') -Filter "$package-*.json")
        foreach ($record in $records) {
            $metadata = Get-Content -LiteralPath $record.FullName -Raw | ConvertFrom-Json
            if ($metadata.name -eq $package) { $pins += "$package=$($metadata.version)=$($metadata.build)" }
        }
    }
    & $CondaExecutable install -p $prefix --override-channels -c conda-forge -c defaults @pins --freeze-installed --download-only --yes
    if ($LASTEXITCODE -eq 0) {
        # Remove the overlapping pip files only once the GPU artifacts exist.
        & $PythonExecutable -m pip uninstall -y faiss-cpu numpy
        if ($LASTEXITCODE -ne 0) { throw 'Could not remove overlapping CPU/NumPy wheels' }
        & $CondaExecutable install -p $prefix --override-channels -c conda-forge -c defaults @pins --freeze-installed --offline --yes
        if ($LASTEXITCODE -eq 0) {
            & $PythonExecutable -c 'import importlib.metadata as m,sys; sys.exit(0 if any(x.name=="opencv-python" and x.version.startswith("5.") for x in m.distributions()) else 1)'
            if ($LASTEXITCODE -eq 0) {
                & $PythonExecutable -m pip install 'opencv-python==4.11.0.86'
                if ($LASTEXITCODE -ne 0) { throw 'OpenCV compatibility install failed' }
            }
            & $PythonExecutable -c 'import faiss,numpy as np; i=faiss.IndexFlatIP(2); i.add(np.array([[1.,0.]],dtype=np.float32)); assert i.search(np.array([[1.,0.]],dtype=np.float32),1)[1][0,0]==0; print("FAISS",faiss.__version__,"CUDA devices",faiss.get_num_gpus())'
            if ($LASTEXITCODE -ne 0) { throw 'Installed FAISS GPU build cannot execute its CPU safety net' }
            & $PythonExecutable -m pip check
            if ($LASTEXITCODE -ne 0) { throw 'Python dependency conflicts remain; review pip check output' }
            Write-Host 'Installed FAISS GPU (includes CPU fallback). Runtime uses GPU when CUDA allocation/search succeeds.'
            exit 0
        }
        throw 'Conda GPU install failed after wheel removal; restore CPU with pip install numpy faiss-cpu==1.15.1 before retrying'
    }
    Write-Warning 'GPU package download failed; checking CPU fallback.'
}

# Keep a GPU-capable build even on a machine temporarily lacking a driver.
& $PythonExecutable -c 'import faiss,numpy as np; i=faiss.IndexFlatIP(2); i.add(np.array([[1.,0.]],dtype=np.float32)); assert i.search(np.array([[1.,0.]],dtype=np.float32),1)[1][0,0]==0'
if ($LASTEXITCODE -ne 0) {
    & $PythonExecutable -m pip install 'faiss-cpu==1.15.1'
    if ($LASTEXITCODE -ne 0) { throw 'FAISS CPU fallback installation failed' }
}
Write-Host 'FAISS CPU fallback is available; GPU install requires an NVIDIA GPU and Conda on Windows.'
