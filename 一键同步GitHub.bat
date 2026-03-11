@echo off
setlocal
cd /d %~dp0

REM 用法：
REM   一键同步GitHub.bat https://github.com/icenorthe/zhongwangchong
REM   一键同步GitHub.bat https://github.com/icenorthe/zhongwangchong.git
REM 可选参数：
REM   --nopause    运行结束不暂停（适合在已打开的终端里跑）
set "REPO_URL=%~1"
set "NO_PAUSE=%~2"

if not "%REPO_URL%"=="" (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0sync_github.ps1" -RepoUrl "%REPO_URL%"
) else (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0sync_github.ps1"
)

if errorlevel 1 (
  echo.
  echo 同步失败，请查看上方输出。
  if /i not "%NO_PAUSE%"=="--nopause" pause
  exit /b 1
)

echo.
echo 同步成功。
if /i not "%NO_PAUSE%"=="--nopause" pause
endlocal
