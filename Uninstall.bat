@echo off
cd /d "%~dp0"

echo.
echo   Spotify ^> YouTube Music -- Uninstall
echo   ─────────────────────────────────────────
echo.

:: .venv
if exist ".venv\" (
    echo   Removing .venv\ ...
    rmdir /s /q .venv
) else (
    echo   .venv\ not found -- skipping
)

:: Auth file
if exist "headers_auth.json" (
    echo   Removing headers_auth.json ...
    del /f /q headers_auth.json
) else (
    echo   headers_auth.json not found -- skipping
)

:: Checkpoints
if exist "checkpoints\" (
    echo   Removing checkpoints\ ...
    rmdir /s /q checkpoints
) else (
    echo   checkpoints\ not found -- skipping
)

:: Playwright Chromium cache
set PW_CACHE=%LOCALAPPDATA%\ms-playwright
if exist "%PW_CACHE%\" (
    echo.
    choice /M "  Remove Playwright Chromium cache (~150 MB)?"
    if errorlevel 2 (
        echo   Skipping Playwright cache.
    ) else (
        echo   Removing Playwright cache...
        rmdir /s /q "%PW_CACHE%"
    )
)

echo.
echo   Done. You can now delete this folder.
echo.
pause
