@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "ROOT=%~dp0"
cd /d "%ROOT%"

if exist "%ROOT%config\launcher_config.bat" call "%ROOT%config\launcher_config.bat"

if not defined MOBILE_PORT set "MOBILE_PORT=8000"
if not defined BRIDGE_PORT set "BRIDGE_PORT=9000"
if not defined TUNNEL_ENABLED set "TUNNEL_ENABLED=0"
if not defined TUNNEL_PROCESS_NAME set "TUNNEL_PROCESS_NAME=cloudflared.exe"
set "LOG_DIR=%ROOT%runtime\logs"
if not exist "%LOG_DIR%" md "%LOG_DIR%"

where python >nul 2>&1
if errorlevel 1 (
  echo [ERROR] python not found in PATH.
  goto :END
)

call :ensure_bridge
call :ensure_mobile
call :ensure_tunnel

echo.
echo [OK] Startup check completed.
echo Order page: http://127.0.0.1:%MOBILE_PORT%
echo Admin page: http://127.0.0.1:%MOBILE_PORT%/admin
echo LAN page  : http://YOUR-IP:%MOBILE_PORT%
goto :END

:ensure_bridge
call :is_listening %BRIDGE_PORT%
if !errorlevel! EQU 0 (
  curl -s "http://127.0.0.1:%BRIDGE_PORT%/health" >nul 2>&1
  if !errorlevel! EQU 0 (
    echo [INFO] Bridge already running on port %BRIDGE_PORT%.
    exit /b 0
  )
  echo [WARN] Port %BRIDGE_PORT% is occupied by another process.
  exit /b 0
)

echo [INFO] Starting bridge service...
start "zwc-bridge" /min cmd /c "cd /d ""%ROOT%"" && set LOCAL_BRIDGE_PORT=%BRIDGE_PORT% && python services\local_bridge_api.py >> ""%LOG_DIR%\bridge.log"" 2>&1"
timeout /t 2 >nul
curl -s "http://127.0.0.1:%BRIDGE_PORT%/health" >nul 2>&1
if !errorlevel! EQU 0 (
  echo [OK] Bridge started on port %BRIDGE_PORT%.
) else (
  echo [ERROR] Bridge startup failed.
)
exit /b 0

:ensure_mobile
call :is_listening %MOBILE_PORT%
if !errorlevel! EQU 0 (
  curl -s "http://127.0.0.1:%MOBILE_PORT%/api/health" >nul 2>&1
  if !errorlevel! EQU 0 (
    echo [INFO] Mobile service already running on port %MOBILE_PORT%.
    exit /b 0
  )
  echo [WARN] Port %MOBILE_PORT% is occupied by another process.
  exit /b 0
)

echo [INFO] Starting mobile service...
start "zwc-mobile" /min cmd /c "cd /d ""%ROOT%"" && set PORT=%MOBILE_PORT% && python services\mobile_charge_server.py >> ""%LOG_DIR%\mobile.log"" 2>&1"
timeout /t 2 >nul
curl -s "http://127.0.0.1:%MOBILE_PORT%/api/health" >nul 2>&1
if !errorlevel! EQU 0 (
  echo [OK] Mobile service started on port %MOBILE_PORT%.
) else (
  echo [ERROR] Mobile service startup failed.
)
exit /b 0

:ensure_tunnel
if /I not "%TUNNEL_ENABLED%"=="1" (
  echo [INFO] Tunnel disabled ^(TUNNEL_ENABLED=0^).
  exit /b 0
)

if not defined TUNNEL_COMMAND set "TUNNEL_COMMAND=cloudflared tunnel --url http://127.0.0.1:%MOBILE_PORT%"

echo %TUNNEL_COMMAND% | findstr /I "cloudflared" >nul
if !errorlevel! EQU 0 (
  where cloudflared >nul 2>&1
  if errorlevel 1 (
    echo [WARN] cloudflared not found. Tunnel skipped.
    exit /b 0
  )
)

tasklist | findstr /I "%TUNNEL_PROCESS_NAME%" >nul 2>&1
if !errorlevel! EQU 0 (
  echo [INFO] Tunnel process already running: %TUNNEL_PROCESS_NAME%
  exit /b 0
)

echo [INFO] Starting tunnel...
start "zwc-tunnel" /min cmd /c "cd /d ""%ROOT%"" && %TUNNEL_COMMAND% >> ""%LOG_DIR%\tunnel.log"" 2>&1"
timeout /t 2 >nul
tasklist | findstr /I "%TUNNEL_PROCESS_NAME%" >nul 2>&1
if !errorlevel! EQU 0 (
  echo [OK] Tunnel started.
) else (
  echo [WARN] Tunnel may not be running.
)
exit /b 0

:is_listening
netstat -ano | findstr /R /C:":%1 .*LISTENING" >nul
exit /b %errorlevel%

:END
endlocal
exit /b 0
