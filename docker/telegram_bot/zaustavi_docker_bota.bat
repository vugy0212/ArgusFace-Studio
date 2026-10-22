@echo off
chcp 65001 >nul
title ArgusFace Telegram Bot - Zaustavljanje
cd /d "%~dp0"

echo [*] Zaustavljam Docker kontejner 'argusface-telegram-bot' ...
docker compose down
echo [*] Kontejner je uspješno zaustavljen.
pause
