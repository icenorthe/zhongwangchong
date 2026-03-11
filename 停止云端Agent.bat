@echo off
setlocal

for /f "tokens=2" %%a in ('tasklist /v ^| findstr /I "zwc-cloud-agent"') do (
  taskkill /PID %%a /F >nul 2>&1
)

for /f "tokens=2" %%a in ('wmic process where "CommandLine like '%%cloud_agent.py%%'" get ProcessId /value ^| findstr "="') do (
  taskkill /PID %%a /F >nul 2>&1
)

echo [OK] cloud agent stop command sent.
exit /b 0
