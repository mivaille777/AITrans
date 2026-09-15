[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

Write-Host "Environment Check"
Write-Host "-----------------"

$Missing = [System.Collections.Generic.List[string]]::new()
$CondaEnvironment = if ($env:AITRANS_DIAGNOSTIC_CONDA_ENV) {
    $env:AITRANS_DIAGNOSTIC_CONDA_ENV
} else {
    "aitrans"
}
$Conda = Get-Command conda -ErrorAction SilentlyContinue
if ($null -ne $Conda) {
    $PythonVersion = & $Conda.Source run -n $CondaEnvironment python --version 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "[PASS] Python runtime ($CondaEnvironment): $PythonVersion"
    }
    else {
        Write-Host "[FAIL] Conda environment '$CondaEnvironment' is unavailable"
        $Missing.Add("Python environment $CondaEnvironment")
    }
}
else {
    $Python = Get-Command python -ErrorAction SilentlyContinue
    if ($null -eq $Python) {
        Write-Host "[FAIL] python is unavailable"
        $Missing.Add("python")
    }
    else {
        $PythonVersion = & $Python.Source --version 2>&1
        Write-Host "[PASS] $PythonVersion"
    }
}

foreach ($CommandName in @("node", "cargo")) {
    $Command = Get-Command $CommandName -ErrorAction SilentlyContinue
    if ($null -eq $Command) {
        Write-Host "[FAIL] $CommandName is unavailable"
        $Missing.Add($CommandName)
        continue
    }

    $Version = & $Command.Source --version 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[FAIL] $CommandName version check failed"
        $Missing.Add($CommandName)
        continue
    }
    Write-Host "[PASS] $Version"
}

if ($Missing.Count -gt 0) {
    throw "Missing required development commands: $($Missing -join ', ')"
}
