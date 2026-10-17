#!/usr/bin/env bash
# ==============================================================================
# PANEL DE CONTROL Y CONFIGURADOR ERP CORPORATIVO COLOMBIA (LINUX)
# - Sin argumentos: Abre el Menú Interactivo (Portabilizar entornos, Conmutar
#   entornos Real vs Pruebas, Clonar BD Real a Pruebas, BD Embebida vs Externa,
#   Respaldos Universales JSON y Arranque).
# - Con argumentos: Ejecuta acciones directas (ej: ./Configurar_ERP_Linux.sh --clone-to-test)
# ==============================================================================
set -e

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="${BASE_DIR}/App"
PYTHON_BIN="${APP_DIR}/runtime/linux/bin/python3"
if [ ! -x "${PYTHON_BIN}" ]; then
    PYTHON_BIN="python3"
fi

if [ $# -eq 0 ]; then
    "${PYTHON_BIN}" "${APP_DIR}/scripts/gestor_sistema.py" --menu
elif [ "$1" = "all" ] || [ "$1" = "linux" ] || [ "$1" = "windows" ]; then
    "${PYTHON_BIN}" "${APP_DIR}/scripts/gestor_sistema.py" --target "$1"
else
    "${PYTHON_BIN}" "${APP_DIR}/scripts/gestor_sistema.py" "$@"
fi
