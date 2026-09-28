param(
    [string[]]$NewTest = @(),
    [string[]]$NewFrontendTest = @(),
    [switch]$NoStart,
    [switch]$SkipFullPythonTests,
    [switch]$AllowLocalChanges,
    [string]$CondaEnvironment = "aitrans"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$RepoRoot = Split-Path -Parent $PSScriptRoot
$DesktopDir = Join-Path $RepoRoot "apps\desktop"

function Assert-LastExitCode {
    param([string]$Message)
    if ($LASTEXITCODE -ne 0) { throw $Message }
}

function Resolve-CondaExecutable {
    if ($env:CONDA_EXE -and (Test-Path -LiteralPath $env:CONDA_EXE)) { return $env:CONDA_EXE }
    $command = Get-Command conda -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    foreach ($candidate in @(
        "$env:USERPROFILE\anaconda3\Scripts\conda.exe",
        "$env:USERPROFILE\miniconda3\Scripts\conda.exe",
        "C:\ProgramData\anaconda3\Scripts\conda.exe",
        "C:\ProgramData\miniconda3\Scripts\conda.exe"
    )) {
        if (Test-Path -LiteralPath $candidate) { return $candidate }
    }
    throw "Conda executable was not found."
}

Set-Location $RepoRoot
if (-not $AllowLocalChanges) {
    $dirty = @(git status --porcelain --untracked-files=no)
    Assert-LastExitCode "Unable to inspect Git working tree."
    if ($dirty.Count -gt 0) {
        throw "Tracked local changes detected. Review them first or use -AllowLocalChanges."
    }
}

$CondaExe = Resolve-CondaExecutable

foreach ($target in @($NewTest | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })) {
    & $CondaExe run --no-capture-output -n $CondaEnvironment python -m pytest $target -q
    Assert-LastExitCode "Targeted Python test failed: $target"
}

if (-not $SkipFullPythonTests) {
    & $CondaExe run --no-capture-output -n $CondaEnvironment python -m pytest -q --ignore=tests/manual
    Assert-LastExitCode "Python test suite failed."
}

Set-Location $DesktopDir
if (-not (Test-Path (Join-Path $DesktopDir "node_modules"))) {
    npm ci --no-audit --prefer-offline
    Assert-LastExitCode "Desktop dependency installation failed."
}

foreach ($target in @($NewFrontendTest | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })) {
    npx vitest run $target
    Assert-LastExitCode "Targeted frontend test failed: $target"
}

npm run desktop:verify
Assert-LastExitCode "Electron desktop verification failed."

if ($NoStart) {
    Set-Location $RepoRoot
    exit 0
}

Set-Location $RepoRoot
& (Join-Path $RepoRoot "start-electron.ps1") -CondaEnvironment $CondaEnvironment
exit $LASTEXITCODE
