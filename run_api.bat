@echo off
chcp 65001 >nul
title ArgusFace Studio - Lokalni API Poslužitelj (Pozadinski AI Engine)
echo ========================================================
echo   ArgusFace Studio - Lokalni API Poslužitelj (Port 5055)
echo   Omogućuje rad Docker Telegram Bota i vanjskih servisa
echo ========================================================
echo.

cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    set "PYTHON_EXE=.venv\Scripts\python.exe"
) else (
    set "PYTHON_EXE=python"
)

echo [*] Provjera pokretanja API poslužitelja...
"%PYTHON_EXE%" -m src.api_server
pause
