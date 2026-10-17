#!/usr/bin/env bash
# ==============================================================================
# PORTABILIZADOR MULTIPLATAFORMA (LINUX + WINDOWS)
# Descarga automáticamente PostgreSQL 17.2 y Python 3.12 + librerías
# tanto para Linux como para Windows dentro de App/engine y App/runtime.
# ==============================================================================
set -e

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET="${1:-all}"

python3 "${BASE_DIR}/App/scripts/portabilizar_entorno.py" --target "${TARGET}"
