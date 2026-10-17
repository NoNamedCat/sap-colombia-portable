@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul 2>&1
title ERP Corporativo Colombia - Sistema Portable (Windows)

:: ==============================================================================
:: LANZADOR PORTABLE WINDOWS - ERP CORPORATIVO COLOMBIA (DIAN UBL 2.1)
:: Soporta motor embebido (App\engine\windows y App\runtime\windows)
:: o instalacion local de Python 3 + PostgreSQL en Windows 10/11.
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

:: 1. Detectar binarios de PostgreSQL (Embebido o Sistema)
set "PG_BIN="
if exist "%APP_DIR%\engine\windows\bin\pg_ctl.exe" (
    set "PG_BIN=%APP_DIR%\engine\windows\bin"
) else (
    for /d %%D in ("C:\Program Files\PostgreSQL\*") do (
        if exist "%%~fD\bin\pg_ctl.exe" set "PG_BIN=%%~fD\bin"
    )
)

:: 2. Detectar binario de Python (Embebido o Sistema)
set "PY_EXE="
if exist "%APP_DIR%\runtime\windows\python.exe" (
    set "PY_EXE=%APP_DIR%\runtime\windows\python.exe"
) else (
    where python >nul 2>&1
    if !errorlevel! equ 0 (
        set "PY_EXE=python"
    )
)

echo ==================================================================
echo   ERP CORPORATIVO COLOMBIA - SISTEMA PORTABLE (WINDOWS 10/11)
echo ==================================================================
echo  Directorio Base : %BASE_DIR%
echo  Datos Windows   : %DB_DIR%
echo  Puerto BD       : %DB_PORT%
echo  Servidor Web    : http://127.0.0.1:%HTTP_PORT%
echo ==================================================================

if "%PG_BIN%"=="" (
    echo [ERROR] No se encontro PostgreSQL en App\engine\windows\bin ni en C:\Program Files\PostgreSQL.
    echo         Instala PostgreSQL para Windows o descomprime los binarios portables en App\engine\windows.
    pause
    exit /b 1
)

if "%PY_EXE%"=="" (
    echo [ERROR] No se encontro Python en App\runtime\windows ni en el PATH de Windows.
    echo         Instala Python 3.11+ para Windows o descomprime Python embebido en App\runtime\windows.
    pause
    exit /b 1
)

:: 3. Inicializar cluster PostgreSQL de Windows si no existe
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

:: 4. Iniciar PostgreSQL en el puerto aislado 54329
"%PG_BIN%\pg_isready.exe" -h 127.0.0.1 -p %DB_PORT% >nul 2>&1
if !errorlevel! neq 0 (
    echo [INFO] Iniciando motor PostgreSQL en puerto %DB_PORT%...
    "%PG_BIN%\pg_ctl.exe" -D "%DB_DIR%" -l "%LOGS_DIR%\postgres_win.log" -o "-p %DB_PORT% -h 127.0.0.1" -w start
)

:: 5. Crear base de datos sap_colombia si no existe
"%PG_BIN%\psql.exe" -h 127.0.0.1 -p %DB_PORT% -U sap -lqt | findstr /C:"sap_colombia" >nul 2>&1
if !errorlevel! neq 0 (
    echo [INFO] Creando base de datos 'sap_colombia'...
    "%PG_BIN%\createdb.exe" -h 127.0.0.1 -p %DB_PORT% -U sap sap_colombia
)

:: 6. Verificar dependencias de Python
"%PY_EXE%" -c "import psycopg2, cryptography" >nul 2>&1
if !errorlevel! neq 0 (
    echo [INFO] Instalando dependencias de Python requeridas...
    "%PY_EXE%" -m pip install --quiet -r "%APP_DIR%\src\requirements.txt"
)

:: 7. Variables de entorno que lee el backend
set "SAP_DB_HOST=127.0.0.1"
set "SAP_DB_PORT=%DB_PORT%"
set "SAP_DB_USER=sap"
set "SAP_DB_PASSWORD="
set "SAP_DB_NAME=sap_colombia"
set "PYTHONPATH=%APP_DIR%\src"
set "PORT=%HTTP_PORT%"

:: 8. Abrir navegador y ejecutar servidor
echo [OK] Abriendo http://127.0.0.1:%HTTP_PORT% en tu navegador...
start "" "http://127.0.0.1:%HTTP_PORT%"

cd /d "%APP_DIR%\src"
echo [INFO] Servidor activo en http://127.0.0.1:%HTTP_PORT% (Presiona Ctrl+C para detener y cerrar).
"%PY_EXE%" web_server.py %HTTP_PORT%

:: 9. Apagar PostgreSQL limpiamente al salir
echo [INFO] Deteniendo motor PostgreSQL...
"%PG_BIN%\pg_ctl.exe" -D "%DB_DIR%" -m fast -w stop
echo [OK] Sistema cerrado correctamente.
pause
