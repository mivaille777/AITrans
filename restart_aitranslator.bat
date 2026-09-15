@echo off
setlocal EnableExtensions

set "REPO_ROOT=%~dp0"
set "START_SCRIPT=%REPO_ROOT%scripts\start.ps1"

if not exist "%START_SCRIPT%" (
  echo [AITranslator] Cannot find "%START_SCRIPT%".
  pause
  exit /b 1
)

echo.
echo ============================================================
echo  AITranslator restart
echo ============================================================
echo Stopping the local backend, Vite server, and Tauri desktop app...

powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference = 'SilentlyContinue';" ^
  "$portOwners = [System.Collections.Generic.HashSet[int]]::new();" ^
  "foreach ($port in @(8766, 5173)) { foreach ($connection in @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)) { [void]$portOwners.Add([int]$connection.OwningProcess) } };" ^
  "foreach ($processId in $portOwners) { Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue };" ^
  "$desktopProcesses = @(Get-Process -Name 'aitrans-desktop', 'AITranslator' -ErrorAction SilentlyContinue);" ^
  "$launcherTerminals = @(Get-Process -ErrorAction SilentlyContinue ^| Where-Object { $_.MainWindowTitle -like 'AITranslator*' });" ^
  "foreach ($process in @($desktopProcesses) + @($launcherTerminals)) { Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue }"

timeout /t 2 /nobreak >nul

echo Starting AITranslator Desktop...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%START_SCRIPT%" -Mode Desktop
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
  echo.
  echo [AITranslator] Restart failed with exit code %EXIT_CODE%.
  echo Check the terminal output above for the missing dependency or startup error.
  pause
  exit /b %EXIT_CODE%
)

echo.
echo [AITranslator] Restart command completed. The Tauri window may need a moment to compile and appear.
pause
exit /b 0
