@echo off
setlocal
if not exist "%~dp0ai-video-studio\node_modules\next\dist\bin\next" (
    echo Dependencies are not installed. Run npm.cmd install inside ai-video-studio first.
    pause
    exit /b 1
)
start "AI Video Studio server" cmd /k "cd /d ""%~dp0ai-video-studio"" && npm.cmd run dev -- --hostname 127.0.0.1 --port 3100"
timeout /t 5 /nobreak >nul
start "" "http://127.0.0.1:3100"
