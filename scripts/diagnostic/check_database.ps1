[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$CondaEnvironment = if ($env:AITRANS_DIAGNOSTIC_CONDA_ENV) {
    $env:AITRANS_DIAGNOSTIC_CONDA_ENV
} else {
    "aitrans"
}
$Conda = Get-Command conda -ErrorAction SilentlyContinue

Write-Host "Database Check"
Write-Host "--------------"

Push-Location $Root
try {
    if ($null -ne $Conda) {
        $ConfigOutput = & $Conda.Source run -n $CondaEnvironment python -c "from app.infrastructure.paths import writable_config_dir; print(writable_config_dir().resolve())" 2>&1
    }
    else {
        $ConfigOutput = & python -c "from app.infrastructure.paths import writable_config_dir; print(writable_config_dir().resolve())" 2>&1
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to resolve the writable configuration directory: $ConfigOutput"
    }
}
finally {
    Pop-Location
}

$ConfigDir = [string]($ConfigOutput | Select-Object -Last 1)
$DatabaseDirs = @(
    $ConfigDir,
    (Join-Path $Root "data")
) | Select-Object -Unique
$Databases = @(
    foreach ($Directory in $DatabaseDirs) {
        if (Test-Path -LiteralPath $Directory -PathType Container) {
            Get-ChildItem -LiteralPath $Directory -Filter "*.sqlite3" -File
        }
    }
)

if ($Databases.Count -eq 0) {
    Write-Warning "[WARN] No runtime SQLite databases exist yet"
}
else {
    foreach ($Database in ($Databases | Sort-Object FullName)) {
        $SizeKiB = [math]::Round($Database.Length / 1KB, 1)
        Write-Host "[PASS] $($Database.FullName) ($SizeKiB KiB)"
    }
}

$LegacyChatHistory = Join-Path $ConfigDir "chat_history.json"
if (Test-Path -LiteralPath $LegacyChatHistory -PathType Leaf) {
    Write-Warning "[WARN] Legacy chat_history.json is no longer read and can be archived or removed"
}
