@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "ROOT=%~dp0"
cd /d "%ROOT%"

if exist "%ROOT%config\launcher_config.bat" call "%ROOT%config\launcher_config.bat"
if not defined BRIDGE_PORT set "BRIDGE_PORT=9000"
set "LOG_DIR=%ROOT%runtime\logs"
set "CLOUD_AGENT_PID_FILE=%ROOT%runtime\cloud_agent.pid"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%" >nul 2>&1

call :resolve_python
if errorlevel 1 exit /b 1

call :ensure_bridge
call :ensure_cloud_agent
exit /b 0

:ensure_bridge
netstat -ano | findstr /R /C:":%BRIDGE_PORT% .*LISTENING" >nul
if !errorlevel! EQU 0 (
  curl -s "http://127.0.0.1:%BRIDGE_PORT%/health" >nul 2>&1
  if !errorlevel! EQU 0 (
    echo [INFO] Bridge already running on port %BRIDGE_PORT%.
    exit /b 0
  )
  echo [WARN] Port %BRIDGE_PORT% is occupied but bridge health check failed.
  exit /b 0
)

echo [INFO] Starting local bridge service...
set "LOCAL_BRIDGE_PORT=%BRIDGE_PORT%"
set "PYTHONPATH=%ROOT%"
set "LOCAL_AUTOMATION_COMMAND="%PYTHON_BIN%" -m services.local_charge_runner"
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%PYTHON_BIN%' -ArgumentList '-m','services.local_bridge_api' -WorkingDirectory '%ROOT%' -WindowStyle Minimized -RedirectStandardOutput '%LOG_DIR%\bridge.log' -RedirectStandardError '%LOG_DIR%\bridge.err.log'" >nul 2>&1
call :wait_for_http "http://127.0.0.1:%BRIDGE_PORT%/health" 15
if !errorlevel! EQU 0 (
  echo [OK] Bridge started on port %BRIDGE_PORT%.
) else (
  echo [WARN] Bridge may not be running yet. Check runtime\logs\bridge.log
)
exit /b 0

:ensure_cloud_agent
call :is_agent_running "%CLOUD_AGENT_PID_FILE%" "zwc-cloud-agent"
if !errorlevel! EQU 0 (
  echo [INFO] Cloud agent already running.
  exit /b 0
)

echo [INFO] Starting cloud agent...
set "PYTHONPATH=%ROOT%"
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%PYTHON_BIN%' -ArgumentList '-u','-m','services.cloud_agent' -WorkingDirectory '%ROOT%' -WindowStyle Minimized -RedirectStandardOutput '%LOG_DIR%\cloud_agent_console.log' -RedirectStandardError '%LOG_DIR%\cloud_agent_console.err.log'" >nul 2>&1
call :wait_for_pid "%CLOUD_AGENT_PID_FILE%" 10
if !errorlevel! EQU 0 (
  echo [OK] cloud agent started.
) else (
  echo [WARN] cloud agent failed to stay running. Check runtime\logs\cloud_agent.log and runtime\logs\cloud_agent_console.log
)
exit /b 0

:resolve_python
set "PYTHON_BIN="
if exist "%ROOT%.venv\Scripts\python.exe" call :try_python "%ROOT%.venv\Scripts\python.exe"
if defined PYTHON_BIN exit /b 0
for %%I in (python.exe python) do (
  if not defined PYTHON_BIN (
    set "CANDIDATE=%%~$PATH:I"
    if defined CANDIDATE call :try_python "!CANDIDATE!"
  )
)
if defined PYTHON_BIN exit /b 0
echo [ERROR] python not found or not runnable. Please create .venv or fix PATH.
exit /b 1

:try_python
"%~1" --version >nul 2>&1
if errorlevel 1 exit /b 1
set "PYTHON_BIN=%~1"
exit /b 0

:wait_for_http
set "WAIT_URL=%~1"
set "WAIT_SECONDS=%~2"
for /l %%I in (1,1,!WAIT_SECONDS!) do (
  curl -s --max-time 2 "!WAIT_URL!" >nul 2>&1
  if !errorlevel! EQU 0 exit /b 0
  timeout /t 1 >nul
)
exit /b 1

:wait_for_pid
set "WAIT_PID_FILE=%~1"
set "WAIT_SECONDS=%~2"
for /l %%I in (1,1,!WAIT_SECONDS!) do (
  call :is_pid_running "!WAIT_PID_FILE!"
  if !errorlevel! EQU 0 exit /b 0
  timeout /t 1 >nul
)
exit /b 1

:is_agent_running
call :is_pid_running "%~1"
if !errorlevel! EQU 0 exit /b 0
call :is_window_running "%~2"
if !errorlevel! EQU 0 exit /b 0
exit /b 1

:is_pid_running
set "PID_FILE=%~1"
if not exist "%PID_FILE%" exit /b 1
set "RUNNING_PID="
for /f "usebackq delims=" %%P in ("%PID_FILE%") do if not defined RUNNING_PID set "RUNNING_PID=%%P"
if not defined RUNNING_PID (
  del /q "%PID_FILE%" >nul 2>&1
  exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -Command "if (Get-Process -Id !RUNNING_PID! -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }" >nul 2>&1
if errorlevel 1 del /q "%PID_FILE%" >nul 2>&1
exit /b %errorlevel%

:is_window_running
powershell -NoProfile -ExecutionPolicy Bypass -Command "$p=Get-Process cmd -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowTitle -eq '%~1' }; if($p){exit 0}else{exit 1}" >nul 2>&1
exit /b %errorlevel%
