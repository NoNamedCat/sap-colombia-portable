@echo off
setlocal
chcp 65001 >nul 2>&1
title Panel de Control y Configuración - ERP Corporativo Colombia

:: ==============================================================================
:: PANEL DE CONTROL Y CONFIGURADOR ERP CORPORATIVO COLOMBIA (WINDOWS)
:: - Sin argumentos: Abre el Menú Interactivo en consola con 10 opciones.
:: - Con argumentos: Pasa los parámetros a gestor_sistema.py
:: ==============================================================================

set "BASE_DIR=%~dp0"
set "APP_DIR=%BASE_DIR%App"
set "PY_EXE=%APP_DIR%\runtime\windows\python.exe"

if not exist "%PY_EXE%" (
    echo [INFO] Descargando entorno base portable para Windows...
    powershell -NoProfile -ExecutionPolicy Bypass -File "%APP_DIR%\scripts\portabilizar_windows.ps1"
)

if "%~1"=="" (
    "%PY_EXE%" "%APP_DIR%\scripts\gestor_sistema.py" --menu
) else (
    "%PY_EXE%" "%APP_DIR%\scripts\gestor_sistema.py" %*
)
pause
