@echo off
setlocal
chcp 65001 >nul 2>&1
title Portabilizador Automatico Windows - ERP Corporativo Colombia

set "BASE_DIR=%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%BASE_DIR%App\scripts\portabilizar_windows.ps1"
pause
