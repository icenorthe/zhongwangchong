@echo off
chcp 65001 >nul
title 应用页码格式

:: 直接双击此BAT运行，会弹出文件选择框
:: 也可以把Word文档拖到此BAT上运行

:: 检查Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未检测到Python，请先安装Python 3
    echo 下载地址：https://www.python.org/downloads/
    echo 安装时记得勾选 "Add Python to PATH"
    pause
    exit /b
)

:: 运行Python脚本（同目录）
python "%~dp0应用页码格式.py" %1

