@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul 2>&1
title ERP Corporativo Colombia - Sistema Portable Autonomo (Windows)

:: ==============================================================================
:: LANZADOR PORTABLE WINDOWS - ERP CORPORATIVO COLOMBIA (DIAN UBL 2.1)
:: Delega al Gestor Unificado (soporta BD Portable en Data\db_windows
:: o PostgreSQL Externo configurado en Data\config.json).
:: ==============================================================================

set "BASE_DIR=%~dp0"
set "APP_DIR=%BASE_DIR%App"
set "PY_EXE=%APP_DIR%\runtime\windows\python.exe"

if not exist "%PY_EXE%" (
    echo [INFO] Descargando y preparando entorno portable para Windows...
    powershell -NoProfile -ExecutionPolicy Bypass -File "%APP_DIR%\scripts\portabilizar_windows.ps1"
)

"%PY_EXE%" "%APP_DIR%\scripts\portabilizar_entorno.py" --start
pause
