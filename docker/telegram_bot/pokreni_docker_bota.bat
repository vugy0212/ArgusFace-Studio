@echo off
chcp 65001 >nul
title ArgusFace Telegram Bot - Docker
cd /d "%~dp0"

if not exist ".env" (
    echo [UPOZORENJE] Datoteka .env ne postoji!
    echo Kopiram .env.example u .env ...
    copy .env.example .env >nul
    echo.
    echo Otvorite datoteku .env i unesite svoj TELEGRAM_BOT_TOKEN dobiven od @BotFather-a!
    notepad .env
    echo Nakon unosa i spremanja tokena, ponovno pokrenite ovu skriptu.
    pause
    exit /b 1
)

echo [*] Gradim i pokrećem Docker kontejner 'argusface-telegram-bot' ...
docker compose up -d --build
echo.
echo [*] Stanje kontejnera:
docker ps --filter "name=argusface-telegram-bot"
echo.
echo [INFO] Bot radi 24/7 u pozadini.
echo Za pregled logova pokrenite: docker logs -f argusface-telegram-bot
pause
