# scripts/webrebuild-dev.ps1
# AITranslator WebReBuild frontend verification + development launcher

$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$DesktopDir = Join-Path $RepoRoot "apps\desktop"
$PackageJson = Join-Path $DesktopDir "package.json"

function Stop-WithError {
    param([string]$Message)

    Write-Host ""
    Write-Host "[ERROR] $Message" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host " AITranslator WebReBuild Dev Launcher" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# ------------------------------------------------------------
# 1. Validate project directory
# ------------------------------------------------------------

if (-not (Test-Path $DesktopDir)) {
    Stop-WithError "Desktop directory not found: $DesktopDir"
}

if (-not (Test-Path $PackageJson)) {
    Stop-WithError "package.json not found: $PackageJson"
}

Write-Host "[1/5] Desktop project found" -ForegroundColor Green
Write-Host "      $DesktopDir"
Write-Host ""

Push-Location $DesktopDir

try {
    # --------------------------------------------------------
    # 2. Frontend lint
    # --------------------------------------------------------

    Write-Host "[2/5] Running frontend lint..." -ForegroundColor Yellow
    Write-Host ""

    & npm run lint

    if ($LASTEXITCODE -ne 0) {
        Stop-WithError "npm run lint failed with exit code $LASTEXITCODE"
    }

    Write-Host ""
    Write-Host "Frontend lint passed." -ForegroundColor Green
    Write-Host ""

    # --------------------------------------------------------
    # 3. Frontend tests
    # --------------------------------------------------------

    Write-Host "[3/5] Running frontend tests..." -ForegroundColor Yellow
    Write-Host ""

    & npm run test

    if ($LASTEXITCODE -ne 0) {
        Stop-WithError "npm run test failed with exit code $LASTEXITCODE"
    }

    Write-Host ""
    Write-Host "Frontend tests passed." -ForegroundColor Green
    Write-Host ""

    # --------------------------------------------------------
    # 4. Production build
    # --------------------------------------------------------

    Write-Host "[4/5] Running frontend production build..." -ForegroundColor Yellow
    Write-Host ""

    & npm run build

    if ($LASTEXITCODE -ne 0) {
        Stop-WithError "npm run build failed with exit code $LASTEXITCODE"
    }

    Write-Host ""
    Write-Host "Frontend build passed." -ForegroundColor Green
    Write-Host ""

    # --------------------------------------------------------
    # 5. Start backend and Tauri in separate PowerShell windows
    # --------------------------------------------------------

    Write-Host "[5/5] Starting development services..." -ForegroundColor Yellow
    Write-Host ""

    $BackendCommand = @"
Set-Location '$DesktopDir'
`$Host.UI.RawUI.WindowTitle = 'AITranslator - Backend'
Write-Host 'AITranslator Backend' -ForegroundColor Cyan
Write-Host 'FastAPI: http://127.0.0.1:8766' -ForegroundColor DarkGray
Write-Host ''
npm run backend:dev
"@

    $TauriCommand = @"
Set-Location '$DesktopDir'
`$Host.UI.RawUI.WindowTitle = 'AITranslator - Tauri'
Write-Host 'AITranslator Tauri Desktop' -ForegroundColor Cyan
Write-Host ''
npm run tauri:dev
"@

    Start-Process pwsh `
        -WorkingDirectory $DesktopDir `
        -ArgumentList @(
            "-NoExit",
            "-Command",
            $BackendCommand
        )

    # Give FastAPI a moment to start before Tauri loads React.
    Start-Sleep -Seconds 2

    Start-Process pwsh `
        -WorkingDirectory $DesktopDir `
        -ArgumentList @(
            "-NoExit",
            "-Command",
            $TauriCommand
        )

    Write-Host "Backend terminal started." -ForegroundColor Green
    Write-Host "Tauri terminal started." -ForegroundColor Green
    Write-Host ""
    Write-Host "Development environment is running." -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Backend : http://127.0.0.1:8766" -ForegroundColor DarkGray
    Write-Host "Vite    : http://127.0.0.1:5173" -ForegroundColor DarkGray
    Write-Host ""
}
finally {
    Pop-Location
}
