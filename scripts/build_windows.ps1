[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$desktopRoot = Join-Path $repoRoot "apps\desktop"

if (-not (Test-Path -LiteralPath (Join-Path $desktopRoot "package.json") -PathType Leaf)) {
    throw "React/Tauri desktop package was not found: $desktopRoot"
}

Push-Location $desktopRoot
try {
    & npm run tauri:build
    if ($LASTEXITCODE -ne 0) {
        throw "Tauri build failed with exit code $LASTEXITCODE."
    }
}
finally {
    Pop-Location
}

Write-Host "React/Tauri desktop build completed."
