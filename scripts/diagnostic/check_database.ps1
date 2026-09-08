Write-Host "Database Check"
Write-Host "--------------"

$dbCandidates = @(
    "data\aitrans.db",
    "data\aitrans.sqlite3"
)

$found = $false
foreach ($db in $dbCandidates) {
    if (Test-Path $db) {
        Write-Host "[PASS] Database exists: $db"
        $found = $true
    }
}

if (-not $found) {
    Write-Warning "[WARN] No known database file found"
}
