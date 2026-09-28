param(
    [string]$CondaEnvironment = "aitrans",
    [switch]$InstallDependencies,
    [switch]$SkipRagProbe,
    [switch]$Verify,
    [switch]$BackendOnly,
    [switch]$BuiltRuntime
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Forward = @{ CondaEnvironment = $CondaEnvironment }
if ($InstallDependencies) { $Forward.InstallDependencies = $true }
if ($SkipRagProbe) { $Forward.SkipRagProbe = $true }
if ($Verify) { $Forward.Verify = $true }
if ($BackendOnly) { $Forward.BackendOnly = $true }
if ($BuiltRuntime) { $Forward.BuiltRuntime = $true }

& (Join-Path $PSScriptRoot "start-electron.ps1") @Forward
exit $LASTEXITCODE
