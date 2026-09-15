[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$CondaEnvironment = if ($env:AITRANS_DIAGNOSTIC_CONDA_ENV) {
    $env:AITRANS_DIAGNOSTIC_CONDA_ENV
} else {
    "aitrans"
}
$Conda = Get-Command conda -ErrorAction SilentlyContinue

Write-Host "LLM Configuration Check"
Write-Host "-----------------------"

$Checker = Join-Path $PSScriptRoot "check_llm.py"
if (-not (Test-Path -LiteralPath $Checker -PathType Leaf)) {
    throw "LLM diagnostic helper is missing: $Checker"
}

Push-Location $Root
try {
    if ($null -ne $Conda) {
        $Output = & $Conda.Source run -n $CondaEnvironment python $Checker 2>&1
    }
    else {
        $Output = & python $Checker 2>&1
    }
    if ($LASTEXITCODE -ne 0) {
        throw "LLM configuration check failed: $Output"
    }
    $Output
}
finally {
    Pop-Location
}
