@echo off
setlocal
chcp 65001 >nul 2>&1
title Gestor Unificado de Portabilidad y Base de Datos - ERP Corporativo Colombia

set "BASE_DIR=%~dp0"
set "PY_EXE=%BASE_DIR%App\runtime\windows\python.exe"

if not exist "%PY_EXE%" (
    echo [INFO] Descargando entorno base portable para Windows...
    powershell -NoProfile -ExecutionPolicy Bypass -File "%BASE_DIR%App\scripts\portabilizar_windows.ps1"
)

if "%~1"=="" (
    "%PY_EXE%" "%BASE_DIR%App\scripts\portabilizar_entorno.py" --menu
) else (
    "%PY_EXE%" "%BASE_DIR%App\scripts\portabilizar_entorno.py" %*
)
pause
