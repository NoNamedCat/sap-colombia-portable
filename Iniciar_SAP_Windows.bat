@echo off
setlocal enabledelayedexpansion
title ERP SAP Colombia - Sistema Portable

:: ==============================================================================
:: LANZADOR PORTABLE WINDOWS - ERP SAP COLOMBIA
:: 100% Autonomo: Arranca PostgreSQL embebido y Servidor Web/API
:: ==============================================================================

set "BASE_DIR=%~dp0"
set "APP_DIR=%BASE_DIR%App"
set "DATA_DIR=%BASE_DIR%Data"
set "DB_DIR=%DATA_DIR%\db"
set "LOGS_DIR=%DATA_DIR%\logs"
set "PG_BIN=%APP_DIR%\engine\windows\bin"

if not exist "%LOGS_DIR%" mkdir "%LOGS_DIR%"

set "DB_PORT=54329"
set "HTTP_PORT=8000"

echo ==================================================================
echo   ERP SAP COLOMBIA - SISTEMA PORTABLE AUTONOMO (WINDOWS)
echo ==================================================================
echo  Directorio Base : %BASE_DIR%
echo  Datos y BD      : %DATA_DIR%
echo  Motor Embebido  : PostgreSQL 17 (Puerto %DB_PORT%)
echo  Servidor Web    : http://127.0.0.1:%HTTP_PORT%
echo ==================================================================

:: 1. Verificar e inicializar cluster si no existe
if not exist "%DB_DIR%\PG_VERSION" (
    echo [INFO] Inicializando cluster de base de datos embebida...
    "%PG_BIN%\initdb.exe" -D "%DB_DIR%" -U sap --auth=trust -E UTF8 > "%LOGS_DIR%\initdb.log" 2>&1
    echo [OK] Base de datos inicializada.
)

:: 2. Iniciar PostgreSQL Embebido
echo [INFO] Iniciando motor de base de datos embebido en puerto %DB_PORT%...
"%PG_BIN%\pg_ctl.exe" -D "%DB_DIR%" -l "%LOGS_DIR%\postgres.log" -o "-p %DB_PORT%" -w start

:: 3. Configurar entorno para la aplicacion
set "SAP_PG_DSN=postgresql://sap@localhost:%DB_PORT%/sap_colombia"
set "PORT=%HTTP_PORT%"

:: 4. Abrir navegador por defecto
start http://127.0.0.1:%HTTP_PORT%

:: 5. Ejecutar Python Embebido
cd /d "%APP_DIR%\src"
echo [INFO] Sistema en ejecucion. No cierres esta ventana.
"%APP_DIR%\runtime\windows\python.exe" web_server.py %HTTP_PORT% 0.0.0.0

:: Al cerrar la ejecucion, detener PostgreSQL limpiamente
echo [INFO] Deteniendo motor de base de datos embebido...
"%PG_BIN%\pg_ctl.exe" -D "%DB_DIR%" -w stop
echo [OK] Sistema cerrado correctamente.
pause
