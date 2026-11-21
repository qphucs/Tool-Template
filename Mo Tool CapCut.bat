@echo off
setlocal
cd /d "%~dp0"

rem Run with python.exe so startup errors stay visible in this window.
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -X utf8 -m capcut_tool.app
) else (
    where python.exe >nul 2>nul
    if errorlevel 1 (
        echo Cannot find Python. Install Python or create the .venv environment first.
        pause
        exit /b 1
    )
    python.exe -X utf8 -m capcut_tool.app
)

echo.
echo The tool has closed. If an error appeared above, send me a screenshot.
pause
