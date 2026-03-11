@echo off
setlocal
cd /d %~dp0

REM 可选：把你的仓库地址写在这里，或在命令行传参：
REM   一键同步GitHub.bat https://github.com/icenorthe/REPO.git
set "REPO_URL=%~1"

if not "%REPO_URL%"=="" (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0sync_github.ps1" -RepoUrl "%REPO_URL%"
) else (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0sync_github.ps1"
)

if errorlevel 1 (
  echo.
  echo 同步失败，请查看上方输出。
  pause
  exit /b 1
)

echo.
echo 同步成功。
timeout /t 2 >nul
endlocal

