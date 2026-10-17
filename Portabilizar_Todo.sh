#!/usr/bin/env bash
# ==============================================================================
# GESTOR UNIFICADO DE PORTABILIDAD, BASE DE DATOS Y ARRANQUE (LINUX / WINDOWS)
# - Sin argumentos: Abre el Menú Interactivo (Portabilizar, BD Portable vs
#   PostgreSQL Externo, Respaldos Universales e Inicio del ERP).
# - Con argumentos: Ejecuta la acción directa (ej: ./Portabilizar_Todo.sh --target all)
# ==============================================================================
set -e

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY_BIN="${BASE_DIR}/App/runtime/linux/bin/python3"
if [ ! -x "${PY_BIN}" ]; then
    PY_BIN="python3"
fi

if [ $# -eq 0 ]; then
    "${PY_BIN}" "${BASE_DIR}/App/scripts/portabilizar_entorno.py" --menu
elif [ "$1" = "all" ] || [ "$1" = "linux" ] || [ "$1" = "windows" ]; then
    "${PY_BIN}" "${BASE_DIR}/App/scripts/portabilizar_entorno.py" --target "$1"
else
    "${PY_BIN}" "${BASE_DIR}/App/scripts/portabilizar_entorno.py" "$@"
fi
