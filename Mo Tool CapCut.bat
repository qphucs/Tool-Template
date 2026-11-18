@echo off
rem Mở app CapCut Template Tool (double-click file này)
cd /d "%~dp0"
start "" ".venv\Scripts\pythonw.exe" -X utf8 -m capcut_tool.app
