@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "ROOT=%~dp0"
cd /d "%ROOT%"

set "LOG_DIR=%ROOT%runtime\logs"
set "SOCKET_AGENT_PID_FILE=%ROOT%runtime\socket_status_agent.pid"

if not exist "%ROOT%runtime" mkdir "%ROOT%runtime" >nul 2>&1
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%" >nul 2>&1

call :resolve_python
if errorlevel 1 exit /b 1

call :is_agent_running "%SOCKET_AGENT_PID_FILE%" "zwc-socket-status"
if !errorlevel! EQU 0 (
  echo [INFO] socket status agent already running.
  exit /b 0
)

echo [INFO] Starting socket status agent...
set "PYTHONPATH=%ROOT%"
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%PYTHON_BIN%' -ArgumentList 'tools\\socket_status_agent.py' -WorkingDirectory '%ROOT%' -WindowStyle Minimized -RedirectStandardOutput '%LOG_DIR%\socket_status_agent_console.log' -RedirectStandardError '%LOG_DIR%\socket_status_agent_console.err.log'" >nul 2>&1
call :wait_for_pid "%SOCKET_AGENT_PID_FILE%" 10
if !errorlevel! EQU 0 (
  echo [OK] socket status agent started with "%PYTHON_BIN%".
) else (
  echo [WARN] socket status agent failed to stay running. Check runtime\logs\cloud_agent.log and runtime\logs\socket_status_agent_console.log
)
echo [INFO] runtime log: runtime\logs\cloud_agent.log
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
