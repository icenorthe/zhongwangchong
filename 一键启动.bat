@echo off
setlocal
cd /d "%~dp0"
call "%~dp0一键启动所有服务.bat"
exit /b %errorlevel%
