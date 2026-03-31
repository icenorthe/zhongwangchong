@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "ROOT=%~dp0"
cd /d "%ROOT%"

if exist "%ROOT%config\launcher_config.bat" call "%ROOT%config\launcher_config.bat"

if not defined MOBILE_PORT set "MOBILE_PORT=8000"
if not defined BRIDGE_PORT set "BRIDGE_PORT=9000"
if not defined TUNNEL_PROCESS_NAME set "TUNNEL_PROCESS_NAME=cloudflared.exe"

echo [INFO] Stop mobile service on port %MOBILE_PORT%...
call :kill_by_port %MOBILE_PORT%

echo [INFO] Stop bridge service on port %BRIDGE_PORT%...
call :kill_by_port %BRIDGE_PORT%

echo [INFO] Stop tunnel process %TUNNEL_PROCESS_NAME%...
taskkill /IM "%TUNNEL_PROCESS_NAME%" /F >nul 2>&1

echo [INFO] Stop cloud agent...
for /f "tokens=2 delims==" %%a in ('wmic process where "CommandLine like '%%cloud_agent.py%%'" get ProcessId /value ^| findstr "="') do (
  echo     kill PID=%%a
  taskkill /PID %%a /F >nul 2>&1
)

echo [INFO] Stop socket status agent...
for /f "tokens=2 delims==" %%a in ('wmic process where "CommandLine like '%%socket_status_agent.py%%'" get ProcessId /value ^| findstr "="') do (
  echo     kill PID=%%a
  taskkill /PID %%a /F >nul 2>&1
)

echo [OK] Stop done.
endlocal
exit /b 0

:kill_by_port
set "P=%1"
set "FOUND=0"
for /f "tokens=5" %%a in ('netstat -ano ^| findstr /R /C:":%P% .*LISTENING"') do (
  set "FOUND=1"
  echo     kill PID=%%a
  taskkill /PID %%a /F >nul 2>&1
)
if "!FOUND!"=="0" echo     no listener found
exit /b 0
