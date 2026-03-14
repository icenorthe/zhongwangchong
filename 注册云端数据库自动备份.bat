@echo off
setlocal
cd /d "%~dp0"

set "TASK_NAME=ZWC-PythonAnywhere-DB-Backup"
set "INTERVAL_HOURS=2"

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\register_db_backup_task.ps1" -TaskName "%TASK_NAME%" -IntervalHours %INTERVAL_HOURS%
if errorlevel 1 (
  echo.
  echo [ERROR] 自动备份计划任务注册失败。
  exit /b 1
)

echo.
echo [OK] 已注册自动备份任务：%TASK_NAME%
echo 默认每 %INTERVAL_HOURS% 小时备份一次云端 orders.db 到 archive\pythonanywhere_db
exit /b 0
