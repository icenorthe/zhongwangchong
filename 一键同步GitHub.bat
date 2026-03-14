@echo off
setlocal
cd /d %~dp0

set "REPO_URL=%~1"
set "NO_PAUSE=%~2"

if "%REPO_URL%"=="" set "REPO_URL=https://github.com/icenorthe/zhongwangchong"

echo ==============================
echo      GitHub Sync
echo ==============================
echo Repo: %REPO_URL%
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0sync_github.ps1" -RepoUrl "%REPO_URL%"

if errorlevel 1 (
  echo.
  echo Sync failed. Check network, Git login, or remote permissions.
  if /i not "%NO_PAUSE%"=="--nopause" pause
  exit /b 1
)

echo.
echo Sync finished successfully.
if /i not "%NO_PAUSE%"=="--nopause" pause
endlocal
