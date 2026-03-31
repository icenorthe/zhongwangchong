@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "ROOT=%~dp0"
cd /d "%ROOT%"

echo [INFO] Stop web heartbeat...
taskkill /FI "WINDOWTITLE eq zwc-mobile" /T >nul 2>&1
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*mobile_charge_server.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" >nul 2>&1
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*local_bridge_api.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" >nul 2>&1
taskkill /IM "cloudflared.exe" /T >nul 2>&1

echo [INFO] Stop local heartbeat...
taskkill /FI "WINDOWTITLE eq zwc-cloud-agent" /T >nul 2>&1
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*cloud_agent.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" >nul 2>&1

echo [OK] Heartbeat stop done.
endlocal
if /I "%~1"=="--nopause" exit /b 0
pause
exit /b 0
