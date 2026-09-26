[CmdletBinding()]
param(
    [ValidateSet("Desktop", "Web", "Backend")]
    [string]$Mode = "Desktop",

    [string]$CondaEnvironment = "aitrans",
    [string]$ApiHost = "127.0.0.1",
    [ValidateRange(1, 65535)]
    [int]$ApiPort = 8766,
    [string]$FrontendHost = "127.0.0.1",
    [ValidateRange(1, 65535)]
    [int]$FrontendPort = 5173,

    # Dependencies are installed only when they are absent. Use this switch
    # when the environment is already prepared and the launcher must be read-only.
    [switch]$SkipInstall,

    # Opt in to the Docker-backed Python sandbox for this development session.
    [switch]$EnableSandbox,
    [string]$SandboxImage = "aitrans-python-sandbox:v1",

    # Open the Vite URL automatically for -Mode Web.
    [switch]$OpenBrowser,

    [ValidateRange(5, 300)]
    [int]$StartupTimeoutSeconds = 45
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$DesktopDir = Join-Path $RepoRoot "apps\desktop"
$PackageJson = Join-Path $DesktopDir "package.json"
$PackageLock = Join-Path $DesktopDir "package-lock.json"
$ApiBaseUrl = "http://$ApiHost`:$ApiPort"
$HealthUrl = "$ApiBaseUrl/health"
$SandboxHealthUrl = "$ApiBaseUrl/api/sandbox/debug/health"
$SandboxStudioSource = Join-Path $DesktopDir "src\features\settings\SandboxDebugStudio.tsx"
$SandboxEnabledValue = if ($EnableSandbox) { "true" } else { "false" }

function Write-Section {
    param([string]$Title)

    Write-Host ""
    Write-Host "============================================================" -ForegroundColor DarkCyan
    Write-Host " $Title" -ForegroundColor Cyan
    Write-Host "============================================================" -ForegroundColor DarkCyan
}

function Write-Step {
    param([string]$Title)

    Write-Host ""
    Write-Host "[AITranslator] $Title" -ForegroundColor Yellow
}

function Assert-Command {
    param(
        [string]$Name,
        [string]$InstallHint
    )

    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "$Name was not found. $InstallHint"
    }
}

function Resolve-CondaExecutable {
    if ($env:CONDA_EXE -and (Test-Path -LiteralPath $env:CONDA_EXE)) {
        return $env:CONDA_EXE
    }

    $candidates = @(
        (Join-Path $env:USERPROFILE "anaconda3\Scripts\conda.exe"),
        (Join-Path $env:USERPROFILE "miniconda3\Scripts\conda.exe"),
        "C:\ProgramData\anaconda3\Scripts\conda.exe",
        "C:\ProgramData\miniconda3\Scripts\conda.exe"
    )

    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate) {
            return $candidate
        }
    }

    throw "Conda was not found. Install Miniconda/Anaconda or activate a Python 3.11 environment manually."
}

function Resolve-PowerShellExecutable {
    $pwsh = Get-Command pwsh.exe -ErrorAction SilentlyContinue
    if ($pwsh) {
        return $pwsh.Source
    }

    $powershell = Get-Command powershell.exe -ErrorAction SilentlyContinue
    if ($powershell) {
        return $powershell.Source
    }

    throw "Neither pwsh.exe nor powershell.exe was found."
}

function ConvertTo-EncodedPowerShellCommand {
    param([string]$Command)

    # PowerShell -EncodedCommand expects UTF-16LE input.
    return [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($Command))
}

function ConvertTo-PowerShellLiteral {
    param([string]$Value)

    return "'" + $Value.Replace("'", "''") + "'"
}

function Invoke-Checked {
    param(
        [string]$FilePath,
        [string[]]$Arguments,
        [string]$FailureMessage
    )

    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$FailureMessage Exit code: $LASTEXITCODE."
    }
}

function Invoke-CondaPython {
    param(
        [string]$CondaExe,
        [string[]]$PythonArguments
    )

    & $CondaExe run --no-capture-output -n $CondaEnvironment python @PythonArguments | Out-Null
    return $LASTEXITCODE
}

function Test-HttpEndpoint {
    param([string]$Uri)

    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $Uri -TimeoutSec 2 -ErrorAction Stop
        return [int]$response.StatusCode -ge 200 -and [int]$response.StatusCode -lt 400
    }
    catch {
        return $false
    }
}

function Test-TcpPortAvailable {
    param([int]$Port)

    $listener = $null
    try {
        $hostAddress = [Net.Dns]::GetHostAddresses($ApiHost) | Select-Object -First 1
        $listener = [Net.Sockets.TcpListener]::new($hostAddress, $Port)
        $listener.Start()
        return $true
    }
    catch {
        return $false
    }
    finally {
        if ($null -ne $listener) {
            $listener.Stop()
        }
    }
}

function Test-SandboxBackendApiCompatible {
    param([string]$BaseUrl)

    try {
        Invoke-RestMethod -Uri "$BaseUrl/api/sandbox/debug/health" -TimeoutSec 2 -ErrorAction Stop | Out-Null
        $catalog = Invoke-RestMethod -Uri "$BaseUrl/api/agent/tools" -TimeoutSec 2 -ErrorAction Stop
        return [bool]($catalog.tools | Where-Object { $_.name -eq "python_execute" })
    }
    catch {
        return $false
    }
}

function Resolve-SandboxApiPort {
    if (-not $EnableSandbox -or -not (Test-HttpEndpoint $HealthUrl)) {
        return
    }

    try {
        Invoke-RestMethod -Uri $SandboxHealthUrl -TimeoutSec 2 -ErrorAction Stop | Out-Null
        return
    }
    catch {
        $statusCode = 0
        if ($null -ne $_.Exception.Response) {
            try {
                $statusCode = [int]$_.Exception.Response.StatusCode
            }
            catch {
                $statusCode = 0
            }
        }

        if ($statusCode -ne 404) {
            return
        }
    }

    $occupiedApiUrl = $ApiBaseUrl
    $lastPort = [Math]::Min(65535, $ApiPort + 50)
    $firstFreePort = $null
    for ($candidate = $ApiPort + 1; $candidate -le $lastPort; $candidate++) {
        if (Test-TcpPortAvailable -Port $candidate) {
            if ($null -eq $firstFreePort) {
                $firstFreePort = $candidate
            }
            continue
        }

        $candidateBaseUrl = "http://$ApiHost`:$candidate"
        if (Test-SandboxBackendApiCompatible -BaseUrl $candidateBaseUrl) {
            $script:ApiPort = $candidate
            $script:ApiBaseUrl = $candidateBaseUrl
            $script:HealthUrl = "$ApiBaseUrl/health"
            $script:SandboxHealthUrl = "$ApiBaseUrl/api/sandbox/debug/health"
            Write-Host "  $occupiedApiUrl has no Sandbox Debug API; reusing compatible backend at $ApiBaseUrl." -ForegroundColor DarkYellow
            return
        }
    }

    if ($null -eq $firstFreePort) {
        throw "No free API port was found between $($ApiPort + 1) and $lastPort. Pass -ApiPort with an unused port."
    }

    $script:ApiPort = $firstFreePort
    $script:ApiBaseUrl = "http://$ApiHost`:$ApiPort"
    $script:HealthUrl = "$ApiBaseUrl/health"
    $script:SandboxHealthUrl = "$ApiBaseUrl/api/sandbox/debug/health"

    Write-Host "  $occupiedApiUrl is serving a backend without Sandbox Debug API; using free port $ApiPort for this sandbox-enabled session." -ForegroundColor DarkYellow
}

function Get-SandboxRuntimeHealth {
    $deadline = (Get-Date).AddSeconds($StartupTimeoutSeconds)
    $lastError = "No response was received."
    $requestTimeoutSeconds = [Math]::Min(10, [Math]::Max(3, $StartupTimeoutSeconds))

    while ((Get-Date) -lt $deadline) {
        try {
            return Invoke-RestMethod -Uri $SandboxHealthUrl -TimeoutSec $requestTimeoutSeconds -ErrorAction Stop
        }
        catch {
            $statusCode = 0
            if ($null -ne $_.Exception.Response) {
                try {
                    $statusCode = [int]$_.Exception.Response.StatusCode
                }
                catch {
                    $statusCode = 0
                }
            }

            if ($statusCode -eq 404) {
                throw "The API at $ApiBaseUrl returned 404 for $SandboxHealthUrl. The backend started for this session does not include the Sandbox Debug API; confirm that scripts/start.ps1 and the backend are from the same checkout."
            }

            $lastError = $_.Exception.Message
            if ((Get-Date) -lt $deadline) {
                Start-Sleep -Milliseconds 500
            }
        }
    }

    throw "Sandbox health check did not respond within $StartupTimeoutSeconds seconds at $SandboxHealthUrl. Last error: $lastError"
}

function Assert-SandboxBackendReady {
    $sandboxHealth = Get-SandboxRuntimeHealth

    if (-not $sandboxHealth.available) {
        $reason = if ($sandboxHealth.error_code) { $sandboxHealth.error_code } else { "runtime_unavailable" }
        throw "Sandbox was requested, but the API at $ApiBaseUrl reports '$reason'. An already-running backend cannot inherit -EnableSandbox; stop it or use another -ApiPort, then verify Docker Linux mode and image '$SandboxImage'."
    }

    $catalog = $null
    try {
        $catalog = Invoke-RestMethod -Uri "$ApiBaseUrl/api/agent/tools" -TimeoutSec 3 -ErrorAction Stop
    }
    catch {
        throw "Sandbox runtime is healthy at $ApiBaseUrl, but the Agent tool catalog could not be read. Confirm this API belongs to the current checkout."
    }

    if (-not ($catalog.tools | Where-Object { $_.name -eq "python_execute" })) {
        throw "Sandbox runtime is healthy at $ApiBaseUrl, but python_execute is missing from /api/agent/tools. The API is likely from a different checkout; stop it or choose another -ApiPort."
    }
}

function Wait-ForHttpEndpoint {
    param(
        [string]$Uri,
        [int]$TimeoutSeconds,
        [System.Diagnostics.Process]$Process
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-HttpEndpoint $Uri) {
            return $true
        }

        if ($null -ne $Process -and $Process.HasExited) {
            return $false
        }

        Start-Sleep -Milliseconds 500
    }

    return $false
}

function Start-PowerShellTerminal {
    param(
        [string]$PowerShellExe,
        [string]$WorkingDirectory,
        [string]$Command,
        [string]$WindowTitle
    )

    $encodedCommand = ConvertTo-EncodedPowerShellCommand $Command
    return Start-Process `
        -FilePath $PowerShellExe `
        -WorkingDirectory $WorkingDirectory `
        -ArgumentList @(
            "-NoLogo",
            "-NoExit",
            "-ExecutionPolicy",
            "Bypass",
            "-EncodedCommand",
            $encodedCommand
        ) `
        -WindowStyle Normal `
        -PassThru
}

function Ensure-PythonRuntime {
    param([string]$CondaExe)

    Write-Step "Check Python environment: $CondaEnvironment"

    $pythonVersionOutput = & $CondaExe run --no-capture-output -n $CondaEnvironment python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "Conda environment '$CondaEnvironment' is unavailable. Create it first or pass -CondaEnvironment with another environment. Output: $pythonVersionOutput"
    }

    $pythonVersion = ($pythonVersionOutput | Select-Object -Last 1).ToString().Trim()
    if ($pythonVersion -notmatch '^3\.(11|12)$') {
        throw "AITranslator requires Python 3.11 or 3.12. Environment '$CondaEnvironment' has $pythonVersion."
    }

    $backendProbe = @(
        "-c",
        "import backend.main; print('backend-import-ok')"
    )
    $probeExitCode = Invoke-CondaPython $CondaExe $backendProbe
    if ($probeExitCode -eq 0) {
        Write-Host "  Python $pythonVersion / backend dependencies OK" -ForegroundColor Green
        return
    }

    if ($SkipInstall) {
        throw "Backend dependencies are incomplete in '$CondaEnvironment'. Re-run without -SkipInstall to install them."
    }

    Write-Host "  Backend dependencies are incomplete; installing editable project + dev extras..." -ForegroundColor DarkYellow
    Push-Location $RepoRoot
    try {
        Invoke-Checked `
            $CondaExe `
            @("run", "--no-capture-output", "-n", $CondaEnvironment, "python", "-m", "pip", "install", "-e", ".[dev]") `
            "Python dependency installation failed."
    }
    finally {
        Pop-Location
    }

    $probeExitCode = Invoke-CondaPython $CondaExe $backendProbe
    if ($probeExitCode -ne 0) {
        throw "Backend import check still fails after dependency installation."
    }
}

function Ensure-FrontendRuntime {
    param([string]$NpmCommand)

    Write-Step "Check frontend dependencies"

    if (-not (Test-Path -LiteralPath $PackageJson) -or -not (Test-Path -LiteralPath $PackageLock)) {
        throw "Frontend package manifests are missing under $DesktopDir."
    }

    $nodeModulesDir = Join-Path $DesktopDir "node_modules"
    if (Test-Path -LiteralPath $nodeModulesDir) {
        Write-Host "  node_modules already exists" -ForegroundColor Green
        return
    }

    if ($SkipInstall) {
        throw "Frontend dependencies are missing. Re-run without -SkipInstall to execute npm ci."
    }

    Push-Location $DesktopDir
    try {
        Invoke-Checked $NpmCommand @("ci", "--no-audit", "--prefer-offline") "Frontend dependency installation failed."
    }
    finally {
        Pop-Location
    }
}

Resolve-SandboxApiPort

Write-Section "AITranslator development launcher"
Write-Host "Mode       : $Mode"
Write-Host "Repository : $RepoRoot"
Write-Host "API        : $ApiBaseUrl"
Write-Host "Sandbox    : $(if ($EnableSandbox) { "enabled ($SandboxImage)" } else { "disabled (pass -EnableSandbox to opt in)" })"
if ($Mode -ne "Backend") {
    Write-Host "Frontend   : http://$FrontendHost`:$FrontendPort"
}

if (-not (Test-Path -LiteralPath $DesktopDir)) {
    throw "Desktop project directory was not found: $DesktopDir"
}

if ($EnableSandbox -and -not (Test-Path -LiteralPath $SandboxStudioSource)) {
    throw "Sandbox Debug Studio is not present in this checkout. Use branch 'codex/sandbox-frontend-integration' before starting with -EnableSandbox."
}

$CondaExe = Resolve-CondaExecutable
$PowerShellExe = Resolve-PowerShellExecutable
Assert-Command "node" "Install Node.js 20 or newer and restart PowerShell."
$NpmCommandInfo = Get-Command npm.cmd -ErrorAction SilentlyContinue
if ($null -eq $NpmCommandInfo) {
    $NpmCommandInfo = Get-Command npm -ErrorAction SilentlyContinue
}
if ($null -eq $NpmCommandInfo) {
    throw "npm was not found. Install Node.js 20 or newer and restart PowerShell."
}
$NpmCommand = $NpmCommandInfo.Source

if ($Mode -eq "Desktop" -and $FrontendPort -ne 5173) {
    throw "Tauri devUrl is fixed to port 5173. Use -FrontendPort 5173 for -Mode Desktop or use -Mode Web for a custom Vite port."
}

Ensure-PythonRuntime $CondaExe
if ($Mode -ne "Backend") {
    Ensure-FrontendRuntime $NpmCommand
}
if ($Mode -eq "Desktop") {
    Assert-Command "cargo" "Install Rust from https://rustup.rs and restart PowerShell."
}

$BackendProcess = $null
$FrontendProcess = $null

$BackendCommand = @"
`$ErrorActionPreference = 'Stop'
`$Host.UI.RawUI.WindowTitle = 'AITranslator - FastAPI backend'
Set-Location $(ConvertTo-PowerShellLiteral $RepoRoot)
`$env:AITRANS_API_HOST = $(ConvertTo-PowerShellLiteral $ApiHost)
`$env:AITRANS_API_PORT = $(ConvertTo-PowerShellLiteral ([string]$ApiPort))
`$env:AITRANS_FRONTEND_ORIGIN = $(ConvertTo-PowerShellLiteral ("http://$FrontendHost`:$FrontendPort"))
`$env:AITRANS_SANDBOX_ENABLED = $(ConvertTo-PowerShellLiteral $SandboxEnabledValue)
`$env:AITRANS_SANDBOX_IMAGE = $(ConvertTo-PowerShellLiteral $SandboxImage)
Write-Host 'AITranslator backend' -ForegroundColor Cyan
Write-Host 'Health: $HealthUrl' -ForegroundColor DarkGray
Write-Host 'Conda : $CondaEnvironment' -ForegroundColor DarkGray
Write-Host ''
& $(ConvertTo-PowerShellLiteral $CondaExe) run --no-capture-output -n $(ConvertTo-PowerShellLiteral $CondaEnvironment) python -m backend
`$exitCode = `$LASTEXITCODE
Write-Host "Backend stopped with exit code `$exitCode." -ForegroundColor Yellow
exit `$exitCode
"@

if (Test-HttpEndpoint $HealthUrl) {
    Write-Host "Backend is already running: $HealthUrl" -ForegroundColor Green
}
else {
    Write-Step "Start FastAPI backend"
    $BackendProcess = Start-PowerShellTerminal $PowerShellExe $RepoRoot $BackendCommand "AITranslator - FastAPI backend"
    if (-not (Wait-ForHttpEndpoint $HealthUrl $StartupTimeoutSeconds $BackendProcess)) {
        throw "Backend did not become healthy within $StartupTimeoutSeconds seconds. Check the backend terminal for details."
    }
    Write-Host "  Backend ready (PID $($BackendProcess.Id))" -ForegroundColor Green
}

if ($Mode -eq "Backend") {
    if ($EnableSandbox) {
        Assert-SandboxBackendReady
    }
    Write-Section "Backend ready"
    Write-Host "Health : $HealthUrl" -ForegroundColor Green
    Write-Host "Docs   : $ApiBaseUrl/docs" -ForegroundColor Green
    Write-Host "Close the FastAPI terminal window to stop the backend." -ForegroundColor DarkGray
    exit 0
}

if ($EnableSandbox) {
    Assert-SandboxBackendReady
    Write-Host "  Sandbox Debug API and python_execute are ready" -ForegroundColor Green
}

$FrontendBaseUrl = "http://$FrontendHost`:$FrontendPort"
if ($Mode -eq "Web") {
    $FrontendCommand = @"
`$ErrorActionPreference = 'Stop'
`$Host.UI.RawUI.WindowTitle = 'AITranslator - Vite frontend'
Set-Location $(ConvertTo-PowerShellLiteral $DesktopDir)
`$env:VITE_API_BASE_URL = $(ConvertTo-PowerShellLiteral $ApiBaseUrl)
Write-Host 'AITranslator Vite frontend' -ForegroundColor Cyan
Write-Host 'URL: $FrontendBaseUrl' -ForegroundColor DarkGray
Write-Host 'API: $ApiBaseUrl' -ForegroundColor DarkGray
Write-Host ''
npm run dev -- --host $(ConvertTo-PowerShellLiteral $FrontendHost) --port $FrontendPort
`$exitCode = `$LASTEXITCODE
Write-Host "Vite stopped with exit code `$exitCode." -ForegroundColor Yellow
exit `$exitCode
"@

    Write-Step "Start Vite frontend"
    $FrontendProcess = Start-PowerShellTerminal $PowerShellExe $DesktopDir $FrontendCommand "AITranslator - Vite frontend"
    if (-not (Wait-ForHttpEndpoint $FrontendBaseUrl $StartupTimeoutSeconds $FrontendProcess)) {
        throw "Vite did not become reachable within $StartupTimeoutSeconds seconds. Check the frontend terminal for details."
    }
    Write-Host "  Frontend ready (PID $($FrontendProcess.Id))" -ForegroundColor Green

    if ($OpenBrowser) {
        Start-Process $FrontendBaseUrl | Out-Null
    }
}
else {
    $TauriCommand = @"
`$ErrorActionPreference = 'Stop'
`$Host.UI.RawUI.WindowTitle = 'AITranslator - Tauri desktop'
Set-Location $(ConvertTo-PowerShellLiteral $DesktopDir)
`$env:VITE_API_BASE_URL = $(ConvertTo-PowerShellLiteral $ApiBaseUrl)
Write-Host 'AITranslator Tauri desktop' -ForegroundColor Magenta
Write-Host 'API: $ApiBaseUrl' -ForegroundColor DarkGray
Write-Host 'Tauri will start Vite through tauri.conf.json.' -ForegroundColor DarkGray
Write-Host ''
npm run tauri:dev
`$exitCode = `$LASTEXITCODE
Write-Host "Tauri stopped with exit code `$exitCode." -ForegroundColor Yellow
exit `$exitCode
"@

    Write-Step "Start Tauri desktop frontend"
    $FrontendProcess = Start-PowerShellTerminal $PowerShellExe $DesktopDir $TauriCommand "AITranslator - Tauri desktop"
    Write-Host "  Tauri terminal started (PID $($FrontendProcess.Id))" -ForegroundColor Green
    Write-Host "  Main window will appear after Rust/Tauri compilation finishes." -ForegroundColor DarkGray
}

Write-Section "AITranslator is ready"
Write-Host "Backend : $HealthUrl" -ForegroundColor Green
if ($Mode -eq "Web") {
    Write-Host "Frontend: $FrontendBaseUrl" -ForegroundColor Green
    Write-Host "Browser : $($OpenBrowser.IsPresent)" -ForegroundColor DarkGray
}
else {
    Write-Host "Desktop : Tauri main window" -ForegroundColor Green
    Write-Host "Overlay : created by the desktop shell when needed" -ForegroundColor DarkGray
}
Write-Host "Close the corresponding PowerShell terminal to stop the service." -ForegroundColor Cyan
