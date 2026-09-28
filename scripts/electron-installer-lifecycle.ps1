[CmdletBinding()]
param(
    [string]$SetupPath = "",
    [string]$PreviousSetupPath = "",
    [switch]$AcknowledgeInstallMutation,
    [switch]$KeepTestData,
    [ValidateRange(30, 600)]
    [int]$TimeoutSeconds = 180
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ($env:OS -ne "Windows_NT") { throw "Electron installer lifecycle testing requires Windows." }
if (-not $AcknowledgeInstallMutation) {
    throw "This test installs and uninstalls AITrans for the current Windows user. Re-run with -AcknowledgeInstallMutation."
}

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$DesktopRoot = Join-Path $RepoRoot "apps\desktop"
$MakerRoot = Join-Path $DesktopRoot "out\make\squirrel.windows\x64"
$ReportRoot = Join-Path $RepoRoot "test-results"
$ReportPath = Join-Path $ReportRoot "electron-installer-lifecycle.json"
$InstallRoot = Join-Path $env:LOCALAPPDATA "AITrans"
$CanonicalVersion = (Get-Content (Join-Path $RepoRoot "VERSION") -Raw).Trim()
$TestDataRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("AITrans-Stage16-Data-" + [guid]::NewGuid().ToString("N"))
$MarkerPath = Join-Path $TestDataRoot "retention-marker.json"

function Resolve-SetupPath {
    param([string]$Requested)
    if (-not [string]::IsNullOrWhiteSpace($Requested)) {
        $resolved = Resolve-Path -LiteralPath $Requested -ErrorAction Stop
        return $resolved.Path
    }
    $candidate = Get-ChildItem -LiteralPath $MakerRoot -Filter "*Setup.exe" -File -ErrorAction Stop |
        Sort-Object LastWriteTimeUtc -Descending |
        Select-Object -First 1
    if (-not $candidate) { throw "No Squirrel Setup.exe found under $MakerRoot." }
    return $candidate.FullName
}

function Wait-Until {
    param(
        [scriptblock]$Condition,
        [string]$Description
    )
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        if (& $Condition) { return }
        Start-Sleep -Milliseconds 500
    } while ([DateTime]::UtcNow -lt $deadline)
    throw "Timed out waiting for $Description."
}

function Get-InstalledAppDirectories {
    if (-not (Test-Path -LiteralPath $InstallRoot)) { return @() }
    return @(Get-ChildItem -LiteralPath $InstallRoot -Directory -Filter "app-*" -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTimeUtc)
}

function Get-LatestInstalledExecutable {
    $directories = @(Get-InstalledAppDirectories)
    if ($directories.Count -eq 0) { return $null }
    $candidate = Join-Path $directories[-1].FullName "AITrans.exe"
    if (Test-Path -LiteralPath $candidate -PathType Leaf) { return $candidate }
    return $null
}

function Find-AITransShortcuts {
    $roots = @(
        [Environment]::GetFolderPath([Environment+SpecialFolder]::DesktopDirectory),
        [Environment]::GetFolderPath([Environment+SpecialFolder]::Programs)
    ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }
    $matches = @()
    foreach ($root in $roots) {
        $matches += @(Get-ChildItem -LiteralPath $root -Filter "AITrans.lnk" -File -Recurse -ErrorAction SilentlyContinue)
    }
    return @($matches | Select-Object -ExpandProperty FullName -Unique)
}

function Invoke-Setup {
    param([string]$Path, [string]$Label)
    Write-Host "Running $Label installer: $Path" -ForegroundColor Cyan
    $process = Start-Process -FilePath $Path -ArgumentList "--silent" -PassThru
    $process.WaitForExit()
    if ($process.ExitCode -ne 0) { throw "$Label Setup.exe exited with code $($process.ExitCode)." }
    Wait-Until -Description "$Label installation files" -Condition {
        (Test-Path -LiteralPath (Join-Path $InstallRoot "Update.exe") -PathType Leaf) -and
        ($null -ne (Get-LatestInstalledExecutable))
    }
}

function Get-InstalledBackendVersion {
    param([string]$ElectronExecutable)

    $appDirectory = Split-Path -Parent $ElectronExecutable
    $backendExecutable = Join-Path $appDirectory "resources\backend\AITransBackend\AITransBackend.exe"
    if (-not (Test-Path -LiteralPath $backendExecutable -PathType Leaf)) {
        throw "Installed backend sidecar was not found: $backendExecutable"
    }

    $output = & $backendExecutable --runtime-smoke-test
    if ($LASTEXITCODE -ne 0) {
        throw "Installed backend sidecar smoke failed with exit code $LASTEXITCODE."
    }
    $payload = ($output -join [Environment]::NewLine) | ConvertFrom-Json
    return [string]$payload.version
}

function Invoke-InstalledRuntimeSmoke {
    param([string]$Executable, [int]$Port)
    $oldApiPort = $env:AITRANS_API_PORT
    $oldHealth = $env:AITRANS_BACKEND_HEALTH_URL
    $oldData = $env:AITRANSLATOR_DATA_DIR
    try {
        $env:AITRANS_API_PORT = [string]$Port
        $env:AITRANS_BACKEND_HEALTH_URL = "http://127.0.0.1:$Port/health"
        $env:AITRANSLATOR_DATA_DIR = $TestDataRoot
        & $Executable --electron-runtime-smoke-test
        if ($LASTEXITCODE -ne 0) { throw "Installed Electron runtime smoke failed with exit code $LASTEXITCODE." }
    }
    finally {
        $env:AITRANS_API_PORT = $oldApiPort
        $env:AITRANS_BACKEND_HEALTH_URL = $oldHealth
        $env:AITRANSLATOR_DATA_DIR = $oldData
    }
}

function Invoke-Uninstall {
    $update = Join-Path $InstallRoot "Update.exe"
    if (-not (Test-Path -LiteralPath $update -PathType Leaf)) { return }
    Write-Host "Uninstalling AITrans through Squirrel Update.exe..." -ForegroundColor Cyan
    $process = Start-Process -FilePath $update -ArgumentList "--uninstall", "--silent" -PassThru
    $process.WaitForExit()
    if ($process.ExitCode -ne 0) { throw "Squirrel uninstall exited with code $($process.ExitCode)." }
    Wait-Until -Description "AITrans application removal" -Condition {
        (Get-InstalledAppDirectories).Count -eq 0
    }
}

if (Test-Path -LiteralPath $InstallRoot) {
    throw "Refusing lifecycle test because an existing AITrans installation was found at $InstallRoot."
}

$SetupPath = Resolve-SetupPath $SetupPath
if ($PreviousSetupPath) { $PreviousSetupPath = (Resolve-Path -LiteralPath $PreviousSetupPath).Path }
New-Item -ItemType Directory -Force -Path $ReportRoot, $TestDataRoot | Out-Null
@{ created_at = (Get-Date).ToUniversalTime().ToString("o"); expected_version = $CanonicalVersion } |
    ConvertTo-Json | Set-Content -LiteralPath $MarkerPath -Encoding utf8

$phases = [System.Collections.Generic.List[object]]::new()
$installedByTest = $false
$shortcutsAfterInstall = @()
$shortcutsAfterUninstall = @()
$previousVersionFolder = $null
$currentVersionFolder = $null

try {
    if ($PreviousSetupPath) {
        Invoke-Setup -Path $PreviousSetupPath -Label "previous-version"
        $installedByTest = $true
        $previousExe = Get-LatestInstalledExecutable
        $previousVersionFolder = Split-Path -Leaf (Split-Path -Parent $previousExe)
        if ($previousVersionFolder -eq "app-$CanonicalVersion") {
            throw "PreviousSetupPath resolved to the current VERSION; a true upgrade test requires an older installer."
        }
        Invoke-InstalledRuntimeSmoke -Executable $previousExe -Port 18768
        $phases.Add([pscustomobject]@{ name = "previous-install"; status = "passed"; app_folder = $previousVersionFolder })
    }

    Invoke-Setup -Path $SetupPath -Label $(if ($PreviousSetupPath) { "upgrade" } else { "fresh" })
    $installedByTest = $true
    $currentExe = Get-LatestInstalledExecutable
    $currentVersionFolder = Split-Path -Leaf (Split-Path -Parent $currentExe)
    if ($currentVersionFolder -ne "app-$CanonicalVersion") {
        throw "Installed app folder $currentVersionFolder does not match VERSION $CanonicalVersion."
    }
    Invoke-InstalledRuntimeSmoke -Executable $currentExe -Port 18769
    $installedBackendVersion = Get-InstalledBackendVersion -ElectronExecutable $currentExe
    if ($installedBackendVersion -ne $CanonicalVersion) {
        throw "Installed backend version $installedBackendVersion does not match VERSION $CanonicalVersion."
    }
    $shortcutsAfterInstall = @(Find-AITransShortcuts)
    if ($shortcutsAfterInstall.Count -eq 0) { throw "No AITrans desktop/start-menu shortcut was created." }
    $phases.Add([pscustomobject]@{
        name = $(if ($PreviousSetupPath) { "upgrade" } else { "fresh-install" });
        status = "passed";
        app_folder = $currentVersionFolder;
        shortcuts = $shortcutsAfterInstall
    })

    if (-not $PreviousSetupPath) {
        Invoke-Setup -Path $SetupPath -Label "same-version-reinstall"
        $reinstallExe = Get-LatestInstalledExecutable
        Invoke-InstalledRuntimeSmoke -Executable $reinstallExe -Port 18770
        $reinstallBackendVersion = Get-InstalledBackendVersion -ElectronExecutable $reinstallExe
        if ($reinstallBackendVersion -ne $CanonicalVersion) {
            throw "Reinstalled backend version $reinstallBackendVersion does not match VERSION $CanonicalVersion."
        }
        $phases.Add([pscustomobject]@{ name = "same-version-reinstall"; status = "passed"; backend_version = $reinstallBackendVersion })
    }

    if (-not (Test-Path -LiteralPath $MarkerPath -PathType Leaf)) {
        throw "User data marker disappeared before uninstall."
    }

    Invoke-Uninstall
    $installedByTest = $false
    if (-not (Test-Path -LiteralPath $MarkerPath -PathType Leaf)) {
        throw "User data marker was removed by uninstall."
    }
    $shortcutsAfterUninstall = @(Find-AITransShortcuts)
    if ($shortcutsAfterUninstall.Count -ne 0) {
        throw "AITrans shortcuts remain after uninstall: $($shortcutsAfterUninstall -join ', ')"
    }
    $backendProcesses = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -ieq "AITransBackend.exe" })
    if ($backendProcesses.Count -ne 0) {
        throw "AITransBackend process remains after uninstall."
    }
    $phases.Add([pscustomobject]@{ name = "uninstall"; status = "passed"; user_data_retained = $true })

    $report = [ordered]@{
        schema_version = 1
        generated_at = (Get-Date).ToUniversalTime().ToString("o")
        status = "passed"
        version = $CanonicalVersion
        install_root = $InstallRoot
        isolated_data_root = $TestDataRoot
        previous_setup = $PreviousSetupPath
        current_setup = $SetupPath
        previous_app_folder = $previousVersionFolder
        current_app_folder = $currentVersionFolder
        installed_backend_version = $installedBackendVersion
        phases = $phases
    }
    $report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $ReportPath -Encoding utf8
    Write-Host "Installer lifecycle PASS. Report: $ReportPath" -ForegroundColor Green
}
catch {
    $failure = [ordered]@{
        schema_version = 1
        generated_at = (Get-Date).ToUniversalTime().ToString("o")
        status = "failed"
        version = $CanonicalVersion
        install_root = $InstallRoot
        isolated_data_root = $TestDataRoot
        error = $_.Exception.Message
        phases = $phases
    }
    $failure | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $ReportPath -Encoding utf8
    throw
}
finally {
    if ($installedByTest) {
        try { Invoke-Uninstall } catch { Write-Warning "Cleanup uninstall failed: $($_.Exception.Message)" }
    }
    if (-not $KeepTestData -and (Test-Path -LiteralPath $TestDataRoot)) {
        Remove-Item -LiteralPath $TestDataRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
