@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul 2>&1
title ERP Corporativo Colombia - Sistema Portable Autonomo (Windows)

:: ==============================================================================
:: LANZADOR PORTABLE WINDOWS - ERP CORPORATIVO COLOMBIA (DIAN UBL 2.1)
:: 100% Autonomo: Si no encuentra PostgreSQL 17 o Python 3.12 en App\,
:: los descarga y portabiliza automaticamente sin requerir instaladores.
:: ==============================================================================

set "BASE_DIR=%~dp0"
set "APP_DIR=%BASE_DIR%App"
set "DATA_DIR=%BASE_DIR%Data"
set "DB_DIR=%DATA_DIR%\db_windows"
set "LOGS_DIR=%DATA_DIR%\logs"

if not exist "%DATA_DIR%" mkdir "%DATA_DIR%"
if not exist "%LOGS_DIR%" mkdir "%LOGS_DIR%"

set "DB_PORT=54329"
set "HTTP_PORT=8000"

set "PG_BIN=%APP_DIR%\engine\windows\bin"
set "PY_EXE=%APP_DIR%\runtime\windows\python.exe"

:: 0. Auto-portabilizar si faltan los binarios embebidos de Windows
if not exist "%PG_BIN%\postgres.exe" (
    echo [INFO] Descargando y preparando entorno portable para Windows...
    powershell -NoProfile -ExecutionPolicy Bypass -File "%APP_DIR%\scripts\portabilizar_windows.ps1"
)
if not exist "%PY_EXE%" (
    echo [INFO] Descargando y preparando Python portable para Windows...
    powershell -NoProfile -ExecutionPolicy Bypass -File "%APP_DIR%\scripts\portabilizar_windows.ps1"
)

echo ==================================================================
echo   ERP CORPORATIVO COLOMBIA - SISTEMA PORTABLE (WINDOWS 10/11)
echo ==================================================================
echo  Directorio Base : %BASE_DIR%
echo  Datos Windows   : %DB_DIR%
echo  Motor Embebido  : PostgreSQL 17.2 Portable (Puerto %DB_PORT%)
echo  Python Runtime  : %PY_EXE%
echo  Servidor Web    : http://127.0.0.1:%HTTP_PORT%
echo ==================================================================

:: 1. Inicializar cluster PostgreSQL de Windows si no existe
if not exist "%DB_DIR%\PG_VERSION" (
    echo [INFO] Inicializando cluster de base de datos PostgreSQL para Windows...
    "%PG_BIN%\initdb.exe" -D "%DB_DIR%" -U sap --auth=trust -E UTF8 --no-locale > "%LOGS_DIR%\initdb_win.log" 2>&1
    if !errorlevel! neq 0 (
        echo [ERROR] Fallo la inicializacion de la base de datos. Revisa %LOGS_DIR%\initdb_win.log
        pause
        exit /b 1
    )
    echo [OK] Cluster inicializado correctamente.
)

:: 2. Iniciar PostgreSQL en el puerto aislado 54329
echo [INFO] Iniciando motor PostgreSQL embebido en puerto %DB_PORT%...
"%PG_BIN%\pg_ctl.exe" -D "%DB_DIR%" status >nul 2>&1
if !errorlevel! neq 0 (
    "%PG_BIN%\pg_ctl.exe" -D "%DB_DIR%" -l "%LOGS_DIR%\postgres_win.log" -o "-p %DB_PORT% -h 127.0.0.1" -w start
)

:: 3. Variables de entorno que lee el backend
set "SAP_DB_HOST=127.0.0.1"
set "SAP_DB_PORT=%DB_PORT%"
set "SAP_DB_USER=sap"
set "SAP_DB_PASSWORD="
set "SAP_DB_NAME=sap_colombia"
set "PYTHONPATH=%APP_DIR%\src"
set "PORT=%HTTP_PORT%"

:: 4. Crear base de datos sap_colombia si no existe usando Python + psycopg2
"%PY_EXE%" "%APP_DIR%\scripts\portabilizar_entorno.py" --ensure-db

:: 5. Abrir navegador y ejecutar servidor
echo [OK] Abriendo http://127.0.0.1:%HTTP_PORT% en tu navegador...
start "" "http://127.0.0.1:%HTTP_PORT%"

cd /d "%APP_DIR%\src"
echo [INFO] Servidor activo en http://127.0.0.1:%HTTP_PORT% (Presiona Ctrl+C para detener y cerrar).
"%PY_EXE%" web_server.py %HTTP_PORT% 0.0.0.0

:: 6. Apagar PostgreSQL limpiamente al salir
echo [INFO] Deteniendo motor PostgreSQL...
"%PG_BIN%\pg_ctl.exe" -D "%DB_DIR%" -m fast -w stop
echo [OK] Sistema cerrado correctamente.
pause
