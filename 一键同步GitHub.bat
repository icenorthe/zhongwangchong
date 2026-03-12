@echo off
chcp 65001 >nul 2>&1
title GitHub 自动同步脚本
echo ==============================
echo      GitHub 自动同步脚本
echo ==============================
echo.

:: 1. 检查是否安装了 Git
where git >nul 2>&1
if %errorlevel% neq 0 (
    echo 错误：未检测到 Git，请先安装 Git！
    echo 下载地址：https://git-scm.com/download/win
    pause
    exit /b 1
)

:: 2. 检查是否在 Git 仓库目录
git rev-parse --is-inside-work-tree >nul 2>&1
if %errorlevel% neq 0 (
    echo 错误：当前目录不是 Git 仓库！
    echo 请先初始化仓库或克隆仓库到本地。
    pause
    exit /b 1
)

:: 3. 拉取最新代码（你的分支是 master，不是 main）
echo [1/4] 拉取远程最新代码...
git pull origin master
if %errorlevel% neq 0 (
    echo 警告：拉取代码失败（可能是本地无远程分支），继续执行...
)

:: 4. 添加所有修改的文件
echo [2/4] 添加所有修改的文件到暂存区...
git add .

:: 5. 提交代码（修复变量定义，避免空提交）
set "commit_msg=auto sync at %date:~0,4%-%date:~5,2%-%date:~8,2% %time:~0,2%:%time:~3,2%:%time:~6,2%"
echo [3/4] 提交代码，信息：%commit_msg%
git commit -m "%commit_msg%"
if %errorlevel% neq 0 (
    echo 提示：没有需要提交的修改，无需同步！
    pause
    exit /b 0
)

:: 6. 推送到 GitHub（分支改为 master）
echo [4/4] 推送代码到 GitHub...
git push origin master

:: 7. 执行结果判断
if %errorlevel% equ 0 (
    echo.
    echo ==============================
    echo      代码同步成功！
    echo ==============================
) else (
    echo.
    echo ==============================
    echo      代码同步失败！
    echo 请检查：
    echo 1. 是否配置了 GitHub 账号（用户名/邮箱）
    echo 2. 是否有推送权限（仓库是自己的）
    echo 3. 网络是否正常
    echo ==============================
)

echo.
echo 按任意键退出...
pause >nul