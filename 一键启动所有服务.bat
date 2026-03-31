@echo off
setlocal
cd /d "%~dp0"

call "%~dp0启动接单服务.bat"
if errorlevel 1 exit /b %errorlevel%

call "%~dp0启动站点状态服务.bat"
if errorlevel 1 exit /b %errorlevel%

echo.
echo [OK] All services startup completed.
exit /b 0
