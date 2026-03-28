@echo off
setlocal

cd /d "%~dp0backend"

:: ── Check Python (try py launcher, then python) ────────────────
where py >nul 2>&1
if not errorlevel 1 (
    set PYTHON=py
    goto :found_python
)
where python >nul 2>&1
if not errorlevel 1 (
    set PYTHON=python
    goto :found_python
)
echo ERROR: Python not found. Install Python 3.11+ from python.org.
pause
exit /b 1
:found_python

:: ── Create venv if missing ─────────────────────────────────────
if not exist "venv\Scripts\activate.bat" (
    echo Creating virtual environment...
    %PYTHON% -m venv venv
    if errorlevel 1 (
        echo ERROR: Failed to create virtual environment.
        pause
        exit /b 1
    )
)

:: ── Activate venv ──────────────────────────────────────────────
call venv\Scripts\activate.bat

:: ── Install dependencies ────────────────────────────────────────
echo Installing dependencies...
pip install -r requirements.txt
if errorlevel 1 (
    echo ERROR: Dependency installation failed.
    pause
    exit /b 1
)

:: ── Open browser after 2s ──────────────────────────────────────
start "" /b cmd /c "timeout /t 2 >nul && start http://localhost:8000/app"

:: ── Start server ───────────────────────────────────────────────
echo.
echo  VibeTrading running at http://localhost:8000/app
echo  Press Ctrl+C to stop.
echo.
uvicorn main:app --reload --port 8000
if errorlevel 1 (
    echo ERROR: Server failed to start. See output above.
    pause
)
