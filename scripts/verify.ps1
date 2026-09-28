param(
    [ValidateSet("All", "Backend", "Frontend", "Desktop")]
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
    if ($LASTEXITCODE -ne 0) { throw "$Step failed with exit code $LASTEXITCODE." }
}

function Invoke-BackendVerification {
    Write-Host "== Backend verification =="
    if ($Install) {
        python -m pip install --upgrade pip
        Assert-LastExitCode "pip upgrade"
        python -m pip install -e ".[dev]"
        Assert-LastExitCode "Python dependency installation"
    }
    python -m pip check
    Assert-LastExitCode "pip dependency check"
    python -m ruff check backend tests scripts --select E9,F63,F7,F82
    Assert-LastExitCode "Ruff critical correctness checks"
    python -m compileall -q backend
    Assert-LastExitCode "Python compile check"
    .\scripts\test.ps1 @PytestArgs
    Assert-LastExitCode "pytest"
}

function Invoke-FrontendVerification {
    Write-Host "== Frontend verification =="
    Push-Location (Join-Path $repoRoot "apps/desktop")
    try {
        if ($Install) {
            npm ci --no-audit --prefer-offline
            Assert-LastExitCode "npm ci"
        }
        npm run lint
        Assert-LastExitCode "frontend lint"
        npm run test
        Assert-LastExitCode "frontend tests"
        npm run build
        Assert-LastExitCode "frontend build"
    } finally { Pop-Location }
}

function Invoke-DesktopVerification {
    Write-Host "== Electron desktop verification =="
    Push-Location (Join-Path $repoRoot "apps/desktop")
    try {
        if ($Install) {
            npm ci --no-audit --prefer-offline
            Assert-LastExitCode "npm ci"
        }
        npm run desktop:check
        Assert-LastExitCode "desktop contract gate"
        node scripts/electron-credential-smoke.mjs
        Assert-LastExitCode "credential vault smoke"
    } finally { Pop-Location }
}

try {
    if ($Scope -in @("All", "Backend")) { Invoke-BackendVerification }
    if ($Scope -in @("All", "Frontend")) { Invoke-FrontendVerification }
    if ($Scope -in @("All", "Desktop")) { Invoke-DesktopVerification }
    Write-Host "Verification passed for scope: $Scope"
}
finally {
    Pop-Location
}
