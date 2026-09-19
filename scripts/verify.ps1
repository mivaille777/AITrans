param(
    [ValidateSet("All", "Backend", "Frontend", "Tauri")]
    [string]$Scope = "All",
    [switch]$Install,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$PytestArgs
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Push-Location $repoRoot

function Assert-LastExitCode {
    param([string]$Step)

    if ($LASTEXITCODE -ne 0) {
        throw "$Step failed with exit code $LASTEXITCODE."
    }
}

function Invoke-BackendVerification {
    Write-Host "== Backend verification =="

    $pythonVersion = (& python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')").Trim()
    Assert-LastExitCode "Python version check"
    if ($pythonVersion -ne "3.11") {
        throw "Python 3.11 is required for full backend verification. Current version: $pythonVersion"
    }

    if ($Install) {
        & python -m pip install --upgrade pip
        Assert-LastExitCode "pip upgrade"
        & python -m pip install -e ".[dev]"
        Assert-LastExitCode "Python dependency installation"
    }

    & python -m pip check
    Assert-LastExitCode "pip dependency check"

    & python -m ruff check backend tests scripts --select E9,F63,F7,F82
    Assert-LastExitCode "Ruff critical correctness checks"

    & python -m compileall -q backend
    Assert-LastExitCode "Python compile check"

    & .\scripts\test.ps1 @PytestArgs
    Assert-LastExitCode "pytest"
}

function Invoke-FrontendVerification {
    Write-Host "== Frontend verification =="

    Push-Location (Join-Path $repoRoot "apps/desktop")
    try {
        if ($Install) {
            & npm ci --no-audit --prefer-offline
            Assert-LastExitCode "npm ci"
        }

        & npm run lint
        Assert-LastExitCode "frontend lint"

        & npm run test
        Assert-LastExitCode "frontend tests"

        & npm run build
        Assert-LastExitCode "frontend build"
    }
    finally {
        Pop-Location
    }
}

function Invoke-TauriVerification {
    Write-Host "== Tauri verification =="

    $manifest = "apps/desktop/src-tauri/Cargo.toml"

    & cargo fmt --manifest-path $manifest -- --check
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "cargo fmt found existing formatting drift. This check is advisory until the Rust baseline is normalized."
    }

    & cargo clippy --manifest-path $manifest --locked --no-default-features --all-targets -- -D warnings
    Assert-LastExitCode "cargo clippy"

    & cargo test --manifest-path $manifest --locked --no-default-features
    Assert-LastExitCode "cargo test"

    & cargo build --manifest-path $manifest --locked --no-default-features
    Assert-LastExitCode "cargo build"
}

try {
    if ($Scope -in @("All", "Backend")) {
        Invoke-BackendVerification
    }

    if ($Scope -in @("All", "Frontend")) {
        Invoke-FrontendVerification
    }

    if ($Scope -in @("All", "Tauri")) {
        Invoke-TauriVerification
    }

    Write-Host "Verification passed for scope: $Scope"
}
finally {
    Pop-Location
}
