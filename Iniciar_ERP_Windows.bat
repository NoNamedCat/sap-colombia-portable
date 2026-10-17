@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul 2>&1
title ERP Corporativo Colombia - Sistema Portable Autónomo (Windows)

:: ==============================================================================
:: LANZADOR PORTABLE WINDOWS - ERP CORPORATIVO COLOMBIA (DIAN UBL 2.1)
:: Inicia el sistema ERP en 1 clic delegando en gestor_sistema.py (--start).
:: Soporta BD Portable en Data\db_windows o PostgreSQL Externo (Data\config.json).
:: ==============================================================================

set "BASE_DIR=%~dp0"
set "APP_DIR=%BASE_DIR%App"
set "PY_EXE=%APP_DIR%\runtime\windows\python.exe"

if not exist "%PY_EXE%" (
    echo [INFO] Descargando y preparando entorno portable para Windows...
    powershell -NoProfile -ExecutionPolicy Bypass -File "%APP_DIR%\scripts\portabilizar_windows.ps1"
)

"%PY_EXE%" "%APP_DIR%\scripts\gestor_sistema.py" --start %*
pause
