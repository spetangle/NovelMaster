@echo off
chcp 65001 >nul
REM NovelMaster WebUI Launcher (FastAPI)

set HOST=0.0.0.0
set PORT=13567
set VENV=venv

cd /d "%~dp0"

echo.
echo ========================================
echo    NovelMaster WebUI Launcher (FastAPI)
echo ========================================
echo.

REM 检查并结束占用端口的进程
echo [*] 检查端口 %PORT%...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :%PORT% ^| findstr LISTENING') do (
    echo [WARN] 发现进程占用端口 %%a，正在结束...
    taskkill /F /PID %%a >nul 2>&1
)
echo [OK] 端口已释放

REM 检查Python
echo [*] 检查 Python...
python --version >nul 2>&1
if errorlevel 1 (
    python3 --version >nul 2>&1
    if errorlevel 1 (
        echo [ERROR] 未找到 Python，请先安装 Python 3.8+
        pause
        exit /b 1
    )
    set PYTHON=python3
) else (
    set PYTHON=python
)
echo [OK] Found Python

REM 检查虚拟环境
if exist "%VENV%\Scripts\python.exe" (
    echo [*] 使用虚拟环境: %VENV%
    set PYTHON=%VENV%\Scripts\python.exe
) else (
    echo [*] 使用系统 Python
)

REM 安装依赖
echo.
echo [*] 检查依赖...
if exist "requirements.txt" (
    call pip install -r requirements.txt --quiet
    echo [OK] 依赖已安装
)

echo.
echo ========================================
echo    Starting FastAPI server...
echo    Visit http://localhost:%PORT%
echo    API Docs: http://localhost:%PORT%/docs
echo ========================================
echo.

"%PYTHON%" app.py
