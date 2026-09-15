param(
    [switch]$FullAgentSuite
)

$ErrorActionPreference = "Stop"
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")

Push-Location $repoRoot
try {
    $conda = Get-Command conda -ErrorAction SilentlyContinue
    if ($null -eq $conda) {
        throw "Conda is unavailable. Open the configured PowerShell environment and retry."
    }

    Write-Host "[Stage 10.1] Verifying Translation Tool boundary in conda env: aitrans"
    & conda run -n aitrans python -m pytest `
        tests/agent/test_translation_tool_boundary.py `
        tests/test_agent_translation_cascade.py `
        tests/agent/test_typed_tool_registry.py `
        tests/agent/test_agent_router_service.py `
        -q
    if ($LASTEXITCODE -ne 0) {
        throw "Stage 10.1 focused tests failed with exit code $LASTEXITCODE."
    }

    if ($FullAgentSuite) {
        Write-Host "[Stage 10.1] Running full Agent regression suite..."
        & conda run -n aitrans python -m pytest tests/agent tests/test_agent_translation_cascade.py -q
        if ($LASTEXITCODE -ne 0) {
            throw "Agent regression suite failed with exit code $LASTEXITCODE."
        }
    }

    Write-Host "[Stage 10.1] Translation Tool verification passed."
}
finally {
    Pop-Location
}
