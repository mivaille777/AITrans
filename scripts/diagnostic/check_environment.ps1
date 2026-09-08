Write-Host "Environment Check"
Write-Host "-----------------"

python --version
node --version
cargo --version

if ($env:CONDA_DEFAULT_ENV) {
    Write-Host "Conda: $env:CONDA_DEFAULT_ENV"
} else {
    Write-Warning "Conda environment not detected"
}
