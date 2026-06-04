@echo off
cd /d "%~dp0"

echo(
echo   Spotify ^> YouTube Music
echo   ----------------------------------------
echo(

rem Python check
set PYTHON=
py --version >nul 2>&1
if not errorlevel 1 set PYTHON=py
if defined PYTHON goto :venv
python --version >nul 2>&1
if not errorlevel 1 set PYTHON=python
if defined PYTHON goto :venv

echo   Python is not installed. We opened python.org for you.
echo(
echo   IMPORTANT: During install, check the box "Add Python to PATH"
echo   Then close and re-run Start.bat
echo(
start https://www.python.org/downloads/windows/
pause
exit /b 1

:venv
if exist ".venv\" (
    echo   Step 1/3: Environment ready
) else (
    echo   Step 1/3: Creating environment - first time only
    %PYTHON% -m venv .venv
)

call .venv\Scripts\activate.bat

echo   Step 2/3: Installing tools (first time: ~2 min)...
python -m pip install -r requirements.txt --quiet

echo   Step 3/3: Starting app -- your browser will open automatically
echo(
echo   -------------------------------------------------
echo   Keep this window open. Close it to stop the app.
echo   -------------------------------------------------
echo(

%PYTHON% app.py
pause
