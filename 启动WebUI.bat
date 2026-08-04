@echo off
rem ============================================================
rem  CYQUANT 数据服务 WebUI 启动器
rem  双击运行即可；关闭本窗口即停止服务
rem ============================================================
chcp 65001 >nul
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [错误] 未找到虚拟环境 .venv\Scripts\python.exe
    echo 请先执行：py -3.10 -m venv .venv 并安装依赖
    pause
    exit /b 1
)

".venv\Scripts\python.exe" -c "import streamlit" >nul 2>&1
if errorlevel 1 (
    echo [错误] 虚拟环境中未安装 streamlit，请先安装依赖：
    echo   .venv\Scripts\python.exe -m pip install -e .
    pause
    exit /b 1
)

echo.
echo  正在启动 CYQUANT 数据服务 WebUI ...
echo  浏览器将自动打开 http://localhost:8501
echo  关闭本窗口即停止服务
echo.

".venv\Scripts\python.exe" -m streamlit run webui/app.py

echo.
echo  服务已停止。
pause
