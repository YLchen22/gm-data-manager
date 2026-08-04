@echo off
rem ============================================================
rem  CYQUANT Data Service WebUI Launcher
rem  Double-click to start. Close this window to stop.
rem ============================================================
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Virtual env not found: .venv\Scripts\python.exe
    echo Create it first: py -3.10 -m venv .venv
    pause
    exit /b 1
)

".venv\Scripts\python.exe" -c "import streamlit" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] streamlit not installed in .venv
    echo Run: .venv\Scripts\python.exe -m pip install -e .
    pause
    exit /b 1
)

echo.
echo  Starting CYQUANT Data Service WebUI ...
echo  Browser will open at http://localhost:8501
echo  Close this window to stop the service.
echo.

rem Disable streamlit usage-stats/onboarding email prompt
set STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

".venv\Scripts\python.exe" -m streamlit run webui/app.py

echo.
echo  Service stopped.
pause
