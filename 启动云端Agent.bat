@echo off
setlocal
cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 (
  echo [ERROR] python not found in PATH.
  exit /b 1
)

start "zwc-cloud-agent" /min cmd /c "cd /d ""%~dp0"" && python services\cloud_agent.py"
echo [OK] cloud agent started.
exit /b 0
