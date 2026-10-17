#!/usr/bin/env bash
# ==============================================================================
# LANZADOR PORTABLE LINUX - ERP CORPORATIVO COLOMBIA
# Delega en el Gestor Unificado (App/scripts/portabilizar_entorno.py --start),
# que decide la base de datos según el entorno global activo:
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
    python3 "${APP_DIR}/scripts/portabilizar_entorno.py" --target linux
fi
if [ ! -x "${PYTHON_BIN}" ]; then
    PYTHON_BIN="python3"
fi

exec "${PYTHON_BIN}" "${APP_DIR}/scripts/portabilizar_entorno.py" --start "$@"
