@echo off
chcp 65001 >nul
title Isključi automatsko pokretanje API poslužitelja
cd /d "%~dp0"

set "STARTUP_FOLDER=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "SHORTCUT_PATH=%STARTUP_FOLDER%\ArgusFace_API_Server.lnk"

echo ==============================================================================
echo    ArgusFace Studio - Isključivanje automatskog pokretanja API poslužitelja
echo ==============================================================================
echo.

if exist "%SHORTCUT_PATH%" (
    del /f /q "%SHORTCUT_PATH%"
    echo [OK] Automatsko pokretanje je ISKLJUČENO.
    echo Prečac je uklonjen iz Windows Startup mape.
) else (
    echo [INFO] Automatsko pokretanje već nije bilo aktivno.
)
echo.
pause
