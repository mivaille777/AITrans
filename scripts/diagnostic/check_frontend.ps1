[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$Desktop = (Resolve-Path (Join-Path $PSScriptRoot "..\..\apps\desktop")).Path
$PackageJson = Join-Path $Desktop "package.json"

Write-Host "Frontend Check"
Write-Host "--------------"

if (-not (Test-Path -LiteralPath $PackageJson -PathType Leaf)) {
    throw "Frontend package.json is missing: $PackageJson"
}
Write-Host "[PASS] package.json"

$Npm = Get-Command npm -ErrorAction SilentlyContinue
if ($null -eq $Npm) {
    throw "npm is unavailable"
}
$NpmVersion = & $Npm.Source --version 2>&1
if ($LASTEXITCODE -ne 0) {
    throw "npm version check failed: $NpmVersion"
}
Write-Host "[PASS] npm $NpmVersion"

if (Test-Path -LiteralPath (Join-Path $Desktop "node_modules") -PathType Container) {
    Write-Host "[PASS] node_modules"
}
else {
    Write-Warning "[WARN] node_modules is missing; run npm ci in apps/desktop"
}
