@echo off
chcp 65001 >nul
title ArgusFace Studio - Automatsko pokretanje API poslužitelja s Windowsima
cd /d "%~dp0"

set "STARTUP_FOLDER=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "SHORTCUT_PATH=%STARTUP_FOLDER%\ArgusFace_API_Server.lnk"
set "TARGET_VBS=%~dp0run_api_silent.vbs"

:menu
cls
echo ==============================================================================
echo    ArgusFace Studio - Automatsko pokretanje API poslužitelja (Port 5055)
echo ==============================================================================
echo.
echo Ovaj uslužni program omogućuje da se lokalni AI API poslužitelj pokreće
echo automatski i tiho (u pozadini) pri svakom paljenju / restartu Windowsa.
echo.
if exist "%SHORTCUT_PATH%" (
    echo [STATUS]: [X] UKLJUČENO - API poslužitelj se automatski pali s Windowsima.
) else (
    echo [STATUS]: [ ] ISKLJUČENO - API poslužitelj se ne pali automatski.
)
echo.
echo ------------------------------------------------------------------------------
echo   1. UKLJUČI automatsko pokretanje s Windowsima (Preporučeno za 24/7 Bot)
echo   2. ISKLJUČI automatsko pokretanje s Windowsima
echo   3. Pokreni API poslužitelj odmah sada u pozadini
echo   4. Izlaz
echo ------------------------------------------------------------------------------
echo.
choice /c 1234 /n /m "Pritisnite tipku (1, 2, 3 ili 4 na tipkovnici): "

if errorlevel 4 exit /b
if errorlevel 3 goto start_now
if errorlevel 2 goto disable_autostart
if errorlevel 1 goto enable_autostart
goto menu

:enable_autostart
powershell -NoProfile -Command "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut('%SHORTCUT_PATH%'); $s.TargetPath = '%TARGET_VBS%'; $s.WorkingDirectory = '%~dp0'; $s.Description = 'ArgusFace Studio Pozadinski API Poslužitelj'; $s.Save()"
echo.
echo [OK] Automatsko pokretanje je uspješno UKLJUČENO!
echo Prečac je dodan u Windows Startup mapu.
echo.
pause
goto menu

:disable_autostart
if exist "%SHORTCUT_PATH%" (
    del /f /q "%SHORTCUT_PATH%"
    echo.
    echo [OK] Automatsko pokretanje je uspješno ISKLJUČENO.
) else (
    echo.
    echo [INFO] Automatsko pokretanje već nije bilo aktivno.
)
echo.
pause
goto menu

:start_now
start "" wscript.exe "%TARGET_VBS%"
echo.
echo [OK] API poslužitelj je pokrenut u pozadini na portu 5055.
echo.
pause
goto menu
