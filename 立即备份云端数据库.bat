@echo off
setlocal
cd /d "%~dp0"

python tools\backup_pythonanywhere_db.py
if errorlevel 1 (
  echo.
  echo [ERROR] 云端数据库备份失败。
  exit /b 1
)

echo.
echo [OK] 云端数据库备份完成。
exit /b 0
