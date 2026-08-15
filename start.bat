@echo off
chcp 65001 >nul
title 歌词时间戳 · LRC Maker
setlocal
cd /d "%~dp0"

rem ---------- 查找 Python ----------
set "PY=python"
where python >nul 2>nul
if errorlevel 1 (
    where py >nul 2>nul
    if errorlevel 1 (
        echo [错误] 未找到 Python。请先安装 Python 3.10+，安装时勾选 “Add to PATH”。
        pause
        exit /b 1
    )
    set "PY=py -3"
)

rem ---------- 创建虚拟环境（首次运行自动创建）----------
if not exist ".venv\Scripts\python.exe" (
    echo [1/3] 首次运行：正在创建虚拟环境 .venv ...
    %PY% -m venv .venv
    if errorlevel 1 (
        echo [错误] 虚拟环境创建失败，请检查 Python 安装后重试。
        pause
        exit /b 1
    )
)

rem ---------- 检查并安装依赖 ----------
".venv\Scripts\python.exe" -c "import faster_whisper, av, opencc, pypinyin, rapidfuzz" >nul 2>nul
if errorlevel 1 (
    echo [2/3] 首次运行：正在安装依赖（约几分钟，请耐心等待）...
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [错误] 依赖安装失败，请检查网络后重新运行本脚本。
        pause
        exit /b 1
    )
)

rem ---------- 启动 ----------
echo [3/3] 正在启动 歌词时间戳 ...
echo       浏览器将自动打开 http://127.0.0.1:8766 ，关闭本窗口即退出。
".venv\Scripts\python.exe" server.py
echo.
echo 程序已退出。若提示端口被占用，请先关闭其他歌词时间戳窗口再重试。
pause
endlocal
