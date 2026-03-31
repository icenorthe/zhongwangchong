@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "ROOT=%~dp0"
cd /d "%ROOT%"

call :resolve_python
if errorlevel 1 (
  pause
  exit /b 1
)

call "%PYTHON_BIN%" tools\sync_pythonanywhere.py
set "SYNC_EXIT=%errorlevel%"
if not "%SYNC_EXIT%"=="0" (
  echo.
  echo [ERROR] Sync failed with exit code %SYNC_EXIT%.
  pause
)
exit /b %SYNC_EXIT%

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
