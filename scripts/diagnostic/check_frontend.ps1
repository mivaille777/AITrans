Write-Host "Frontend Check"
Write-Host "--------------"

$Desktop = Join-Path $PSScriptRoot "..\..\apps\desktop"

if (Test-Path (Join-Path $Desktop "package.json")) {
    Write-Host "[PASS] package.json exists"
} else {
    Write-Warning "[WARN] package.json missing"
}

if (Test-Path (Join-Path $Desktop "node_modules")) {
    Write-Host "[PASS] node_modules exists"
} else {
    Write-Warning "[WARN] node_modules missing"
}

Push-Location $Desktop
try {
    npm --version
} finally {
    Pop-Location
}
