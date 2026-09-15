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

    $focusedTests = @(
        "tests/agent/test_reading_tool_boundary.py",
        "tests/agent/test_typed_tool_registry.py",
        "tests/agent/test_agent_router_service.py",
        "tests/agent/test_agent_multi_step_planner.py",
        "tests/agent/test_reading_context_provider.py"
    )

    foreach ($testPath in $focusedTests) {
        if (-not (Test-Path $testPath -PathType Leaf)) {
            throw "Stage 10.2 test file is missing: $testPath"
        }
    }

    Write-Host "[Stage 10.2] Verifying Reading Tool boundary in conda env: aitrans"
    & conda run -n aitrans python -m pytest @focusedTests -q
    if ($LASTEXITCODE -ne 0) {
        throw "Stage 10.2 focused tests failed with exit code $LASTEXITCODE."
    }

    if ($FullAgentSuite) {
        Write-Host "[Stage 10.2] Running full Agent regression suite..."
        & conda run -n aitrans python -m pytest tests/agent -q
        if ($LASTEXITCODE -ne 0) {
            throw "Agent regression suite failed with exit code $LASTEXITCODE."
        }
    }

    Write-Host "[Stage 10.2] Reading Tool verification passed."
}
finally {
    Pop-Location
}
