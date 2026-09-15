param(
    [switch]$FullAgentSuite
)

$ErrorActionPreference = "Stop"
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")

$focusedTests = @(
    "tests/agent/test_writing_tool_boundary.py",
    "tests/agent/test_tool_result_contract.py",
    "tests/agent/test_typed_tool_registry.py",
    "tests/agent/test_translation_tool_boundary.py",
    "tests/agent/test_reading_tool_boundary.py",
    "tests/agent/test_research_tool_boundary.py",
    "tests/test_backend_agent_tools.py"
)

Push-Location $repoRoot
try {
    $conda = Get-Command conda -ErrorAction SilentlyContinue
    if ($null -eq $conda) {
        throw "Conda is unavailable. Open the configured PowerShell environment and retry."
    }

    foreach ($testPath in $focusedTests) {
        if (-not (Test-Path $testPath)) {
            throw "Stage 10.4 test file is missing: $testPath"
        }
    }

    Write-Host "[Stage 10.4] Verifying Writing Tool boundary and typed result contract in conda env: aitrans"
    & conda run -n aitrans python -m pytest @focusedTests -q
    if ($LASTEXITCODE -ne 0) {
        throw "Stage 10.4 focused tests failed with exit code $LASTEXITCODE."
    }

    if ($FullAgentSuite) {
        Write-Host "[Stage 10.4] Running full Agent regression suite..."
        & conda run -n aitrans python -m pytest tests/agent -q
        if ($LASTEXITCODE -ne 0) {
            throw "Agent regression suite failed with exit code $LASTEXITCODE."
        }
    }

    Write-Host "[Stage 10.4] Writing Tool and result-contract verification passed."
}
finally {
    Pop-Location
}
