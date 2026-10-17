# ==============================================================================
# PORTABILIZADOR NATIVO WINDOWS (PowerShell) - ERP CORPORATIVO COLOMBIA
# Descarga Python 3.12 Embeddable + pip + PostgreSQL 17.2 Portable en App\
# No requiere tener Python ni PostgreSQL preinstalados en Windows.
# ==============================================================================
$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$AppDir = (Resolve-Path (Join-Path $ScriptDir "..")).Path
$RuntimeWin = Join-Path $AppDir "runtime\windows"
$PyExe = Join-Path $RuntimeWin "python.exe"

Write-Host "==================================================================" -ForegroundColor Cyan
Write-Host " PORTABILIZADOR AUTOMATICO WINDOWS - ERP CORPORATIVO COLOMBIA" -ForegroundColor Cyan
Write-Host "==================================================================" -ForegroundColor Cyan

# 1. Descargar Python 3.12.8 Embeddable si no existe
if (-Not (Test-Path $PyExe)) {
    Write-Host "[1/3] Descargando Python 3.12.8 Portable para Windows x64..." -ForegroundColor Yellow
    New-Item -ItemType Directory -Force -Path $RuntimeWin | Out-Null
    $PyZip = Join-Path $env:TEMP "python-3.12.8-embed-amd64.zip"
    Invoke-WebRequest -Uri "https://www.python.org/ftp/python/3.12.8/python-3.12.8-embed-amd64.zip" -OutFile $PyZip
    Expand-Archive -Path $PyZip -DestinationPath $RuntimeWin -Force
    Remove-Item $PyZip -Force -ErrorAction SilentlyContinue

    # Habilitar site-packages y App\src en python312._pth
    $PthFile = Join-Path $RuntimeWin "python312._pth"
    $PthContent = @(
        "python312.zip",
        ".",
        "Lib\site-packages",
        "..\..\src",
        "import site"
    )
    Set-Content -Path $PthFile -Value $PthContent -Encoding ASCII

    # Descargar e instalar pip dentro del Python portable
    Write-Host "[2/3] Configurando gestor de paquetes pip en App\runtime\windows..." -ForegroundColor Yellow
    $GetPip = Join-Path $env:TEMP "get-pip.py"
    Invoke-WebRequest -Uri "https://bootstrap.pypa.io/get-pip.py" -OutFile $GetPip
    & $PyExe $GetPip --no-warn-script-location
    Remove-Item $GetPip -Force -ErrorAction SilentlyContinue
}

# 2. Ejecutar portabilizar_entorno.py con el Python portable para instalar wheels y PostgreSQL 17.2 Windows
Write-Host "[3/3] Descargando PostgreSQL 17.2 Portable y librerias en App\..." -ForegroundColor Yellow
$PortScript = Join-Path $ScriptDir "portabilizar_entorno.py"
& $PyExe $PortScript --target windows

Write-Host "✅ Entorno Windows 100% portabilizado en App\engine\windows y App\runtime\windows" -ForegroundColor Green
