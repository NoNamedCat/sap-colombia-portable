#!/usr/bin/env bash
# ==============================================================================
# LANZADOR PORTABLE LINUX - ERP CORPORATIVO COLOMBIA
# Inicia el sistema ERP en 1 clic delegando en gestor_sistema.py (--start).
# Decide la base de datos automáticamente según el entorno activo en Data/config.json:
#   - PRUEBAS (mock)  -> base de datos de pruebas (ej. sap_colombia_pruebas)
#   - REAL    (real)  -> base de datos real       (ej. sap_colombia)
# ==============================================================================
set -e

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="${BASE_DIR}/App"
PYTHON_BIN="${APP_DIR}/runtime/linux/bin/python3"

# Auto-portabilizar Python Linux si no existe
if [ ! -x "${PYTHON_BIN}" ]; then
    echo "📦 Descargando y configurando Python 3.12 Portable automáticamente..."
    python3 "${APP_DIR}/scripts/gestor_sistema.py" --target linux
fi
if [ ! -x "${PYTHON_BIN}" ]; then
    PYTHON_BIN="python3"
fi

exec "${PYTHON_BIN}" "${APP_DIR}/scripts/gestor_sistema.py" --start "$@"
