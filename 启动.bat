@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo ============================================
echo   OneNote PDF 思维导图 - 本地服务
echo ============================================
echo.
echo   服务地址 http://localhost:8000/
echo   关闭这个黑窗口即停止服务。
echo.

REM pick venv python if present
if exist "venv\Scripts\python.exe" goto havevenv

REM first run: create venv + install deps
echo   [首次运行] 正在创建虚拟环境并安装依赖，约 1-2 分钟...
where python >nul 2>nul
if errorlevel 1 goto trypy

set "PYRAW=python"
goto makevenv

:trypy
where py >nul 2>nul
if errorlevel 1 goto nopython

set "PYRAW=py -3"

:makevenv
%PYRAW% -m venv venv
if exist "venv\Scripts\python.exe" goto venvok

echo [错误] 虚拟环境创建失败，请检查 Python 安装。
pause
exit /b 1

:venvok
set "PY=venv\Scripts\python.exe"
"%PY%" -m pip install -q -r app\requirements.txt
if errorlevel 1 (
    echo [错误] 依赖安装失败，请检查网络后重试。
    pause
    exit /b 1
)

:havevenv
set "PY=venv\Scripts\python.exe"

REM cache buster: static files carry no Cache-Control
start "" cmd /c "timeout /t 2 >nul & start http://localhost:8000/?v=%RANDOM%"

"%PY%" -m uvicorn app.main:app --port 8000

echo.
echo 服务已停止。
pause
exit /b 0

:nopython
echo [错误] 没有找到 Python。
echo        请先到 python.org 安装 Python，勾选 "Add to PATH"。
echo.
pause
exit /b 1
