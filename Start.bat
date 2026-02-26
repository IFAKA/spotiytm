@echo off
cd /d "%~dp0"

echo.
echo   Spotify ^> YouTube Music
echo   ----------------------------------------
echo.

:: ── Python check ──────────────────────────────────────────────────────────
:: Try py launcher first (installed with Python, always in C:\Windows\)
set PYTHON=
py --version >nul 2>&1
if %errorlevel% == 0 (
    set PYTHON=py
) else (
    python --version >nul 2>&1
    if %errorlevel% == 0 (
        set PYTHON=python
    )
)

if "%PYTHON%" == "" (
    echo   Python is not installed. We opened python.org for you.
    echo.
    echo   IMPORTANT: During install, check the box "Add Python to PATH"
    echo   Then close and re-run Start.bat
    echo.
    start https://www.python.org/downloads/windows/
    pause
    exit /b 1
)

:: ── Step 1: Virtual environment ───────────────────────────────────────────
if exist ".venv\" (
    echo   Step 1/3: Environment ready v
) else (
    echo   Step 1/3: Creating environment (first time only)...
    %PYTHON% -m venv .venv
)

call .venv\Scripts\activate.bat

:: ── Step 2: Dependencies ──────────────────────────────────────────────────
echo   Step 2/3: Installing tools (first time: ~2 min)...
pip install -r requirements.txt --quiet

:: ── Step 3: Launch ────────────────────────────────────────────────────────
echo   Step 3/3: Starting app -- your browser will open automatically
echo.
echo   ─────────────────────────────────────────
echo   Keep this window open. Close it to stop the app.
echo   ─────────────────────────────────────────
echo.

%PYTHON% app.py

pause
