@echo off
chcp 65001 >nul
title Uključi automatsko pokretanje API poslužitelja
cd /d "%~dp0"

set "STARTUP_FOLDER=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "SHORTCUT_PATH=%STARTUP_FOLDER%\ArgusFace_API_Server.lnk"
set "TARGET_VBS=%~dp0run_api_silent.vbs"

echo ==============================================================================
echo    ArgusFace Studio - Uključivanje automatskog pokretanja API poslužitelja
echo ==============================================================================
echo.

powershell -NoProfile -Command "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut('%SHORTCUT_PATH%'); $s.TargetPath = '%TARGET_VBS%'; $s.WorkingDirectory = '%~dp0'; $s.Description = 'ArgusFace Studio Pozadinski API Poslužitelj'; $s.Save()"

echo [OK] Automatsko pokretanje je UKLJUČENO!
echo.
echo Prečac je uspješno kreiran u Windows Startup mapi:
echo   %SHORTCUT_PATH%
echo.
echo API poslužitelj će se sada automatski pokretati pri svakom paljenju računala.
echo.
pause
