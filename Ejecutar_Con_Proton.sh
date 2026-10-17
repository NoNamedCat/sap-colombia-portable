#!/usr/bin/env bash
# ==============================================================================
# LANZADOR PROTON - EJECUTAR ENTORNO WINDOWS DENTRO DE LINUX
# Utiliza tu proton-runner configurado
# ==============================================================================

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Iniciando ERP SAP Colombia usando el entorno Proton de tu sistema..."
if [ -x "/usr/local/bin/proton-runner" ]; then
    /usr/local/bin/proton-runner "${BASE_DIR}/Iniciar_ERP_Windows.bat"
else
    echo "No se encontró /usr/local/bin/proton-runner"
fi
