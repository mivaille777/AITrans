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

    $testFiles = @(
        "tests/agent/test_research_tool_boundary.py",
        "tests/agent/test_translation_tool_boundary.py",
        "tests/agent/test_reading_tool_boundary.py",
        "tests/agent/test_typed_tool_registry.py",
        "tests/agent/test_agent_router_service.py",
        "tests/agent/test_product_agent_routing.py",
        "tests/test_backend_agent_tools.py",
        "tests/test_backend_product_agent.py",
        "tests/test_research_workspace.py"
    )

    foreach ($testFile in $testFiles) {
        if (-not (Test-Path $testFile -PathType Leaf)) {
            throw "Stage 10.3 test file is missing: $testFile"
        }
    }

    Write-Host "[Stage 10.3] Verifying Research Tool boundary in conda env: aitrans"
    & conda run -n aitrans python -m pytest @testFiles -q
    if ($LASTEXITCODE -ne 0) {
        throw "Stage 10.3 focused tests failed with exit code $LASTEXITCODE."
    }

    if ($FullAgentSuite) {
        Write-Host "[Stage 10.3] Running full Agent regression suite..."
        & conda run -n aitrans python -m pytest tests/agent -q
        if ($LASTEXITCODE -ne 0) {
            throw "Agent regression suite failed with exit code $LASTEXITCODE."
        }
    }

    Write-Host "[Stage 10.3] Research Tool verification passed."
}
finally {
    Pop-Location
}
