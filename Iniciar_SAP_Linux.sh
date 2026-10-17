#!/usr/bin/env bash
# ==============================================================================
# LANZADOR PORTABLE LINUX - ERP CORPORATIVO COLOMBIA
# 100% Autónomo: Auto-descarga PostgreSQL 17 + Python 3.12 si no están presentes,
# inicializa la base de datos y arranca el servidor Web/API.
# ==============================================================================

set -e

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="${BASE_DIR}/App"
DATA_DIR="${BASE_DIR}/Data"
DB_DIR="${DATA_DIR}/db"
LOGS_DIR="${DATA_DIR}/logs"
PG_BIN="${APP_DIR}/engine/linux/bin"
PG_LIB="${APP_DIR}/engine/linux/lib"

mkdir -p "${LOGS_DIR}"
chmod 0700 "${DB_DIR}" 2>/dev/null || true

# 0. Auto-portabilizar si faltan los binarios embebidos de PostgreSQL o Python
if [ ! -x "${PG_BIN}/postgres" ] || [ ! -x "${APP_DIR}/runtime/linux/bin/python3" ]; then
    echo "📦 Detectando primer arranque sin binarios portables en App/..."
    echo "⬇️  Descargando y configurando PostgreSQL 17.2 + Python 3.12 Portable automáticamente..."
    python3 "${APP_DIR}/scripts/portabilizar_entorno.py" --target linux
fi

export LD_LIBRARY_PATH="${PG_LIB}:${LD_LIBRARY_PATH:-}"
export PGSYSCONFDIR="${DATA_DIR}"
export PGDATA="${DB_DIR}"

PYTHON_BIN="${APP_DIR}/runtime/linux/bin/python3"
if [ ! -x "${PYTHON_BIN}" ]; then
    PYTHON_BIN="python3"
fi

# Leer configuración desde Data/config.json (con valores por defecto seguros)
CONFIG_FILE="${DATA_DIR}/config.json"
if [ -f "${CONFIG_FILE}" ]; then
    eval "$("${PYTHON_BIN}" - "${CONFIG_FILE}" <<'PYEOF'
import json, sys
try:
    with open(sys.argv[1]) as f:
        c = json.load(f)
    srv = c.get("server", {})
    db = c.get("database", {})
    print(f"HTTP_HOST='{srv.get('host', '127.0.0.1')}'")
    print(f"HTTP_PORT='{int(srv.get('http_port', 8000))}'")
    print(f"DB_PORT='{int(db.get('port', 54329))}'")
    print(f"DB_USER='{db.get('user', 'sap')}'")
    print(f"DB_NAME='{db.get('dbname', 'sap_colombia')}'")
except Exception:
    pass
PYEOF
)"
fi

HTTP_HOST="${HTTP_HOST:-127.0.0.1}"
HTTP_PORT="${HTTP_PORT:-8000}"
DB_PORT="${DB_PORT:-54329}"
DB_USER="${DB_USER:-sap}"
DB_NAME="${DB_NAME:-sap_colombia}"

echo "=================================================================="
echo " 🚀 ERP CORPORATIVO COLOMBIA - SISTEMA PORTABLE AUTÓNOMO (LINUX)"
echo "=================================================================="
echo "📂 Directorio Base : ${BASE_DIR}"
echo "💾 Datos & BD      : ${DATA_DIR}"
echo "⚙️  Motor Embebido  : PostgreSQL 17 (Puerto ${DB_PORT}, BD ${DB_NAME})"
echo "🐍 Python Runtime  : ${PYTHON_BIN}"
echo "🌐 Servidor Web    : http://${HTTP_HOST}:${HTTP_PORT}"
echo "=================================================================="

# 1. Verificar si la base de datos ya está inicializada; si no, inicializarla
if [ ! -f "${DB_DIR}/PG_VERSION" ]; then
    echo "📦 Inicializando nuevo cluster de base de datos embebido en Data/db..."
    mkdir -p "${DB_DIR}"
    chmod 0700 "${DB_DIR}"
    "${PG_BIN}/initdb" -D "${DB_DIR}" -U "${DB_USER}" --auth=trust -E UTF8 > "${LOGS_DIR}/initdb.log" 2>&1
    echo "✅ Cluster inicializado."
fi

# 2. Iniciar motor PostgreSQL embebido si no está corriendo
echo "🔌 Verificando estado del motor PostgreSQL embebido..."
STARTED_PG=0
if ! "${PG_BIN}/pg_ctl" -D "${DB_DIR}" status > /dev/null 2>&1; then
    echo "⚡ Arrancando motor PostgreSQL en puerto ${DB_PORT}..."
    "${PG_BIN}/pg_ctl" -D "${DB_DIR}" -l "${LOGS_DIR}/postgres.log" -o "-p ${DB_PORT} -k ${DB_DIR}" -w start
    STARTED_PG=1
    echo "✅ Motor PostgreSQL activo."
else
    echo "ℹ️  Motor PostgreSQL ya se encontraba en ejecución."
fi

# 3. Exportar variables de entorno para la aplicación Python
export SAP_DB_HOST="127.0.0.1"
export SAP_DB_PORT="${DB_PORT}"
export SAP_DB_USER="${DB_USER}"
export SAP_DB_PASSWORD=""
export SAP_DB_NAME="${DB_NAME}"
export SAP_PG_DSN="postgresql://${DB_USER}@127.0.0.1:${DB_PORT}/${DB_NAME}"
export PORT="${HTTP_PORT}"

# 4. Asegurar que la base de datos exista
"${PYTHON_BIN}" "${APP_DIR}/scripts/portabilizar_entorno.py" --ensure-db

# Función de apagado limpio al salir con Ctrl+C o cerrar terminal
cleanup() {
    echo ""
    echo "🛑 Deteniendo servicios..."
    if [ "${STARTED_PG}" -eq 1 ]; then
        "${PG_BIN}/pg_ctl" -D "${DB_DIR}" -w stop || true
    fi
    echo "👋 ERP Corporativo Colombia cerrado de forma segura."
    exit 0
}
trap cleanup SIGINT SIGTERM EXIT

# Abrir el navegador automáticamente en segundo plano después de 1 segundo
(sleep 1.2 && (xdg-open "http://127.0.0.1:${HTTP_PORT}" > /dev/null 2>&1 || sensible-browser "http://127.0.0.1:${HTTP_PORT}" > /dev/null 2>&1 || true)) &

echo "✨ Servidor listo. Presiona Ctrl+C en esta terminal para detener el sistema."
echo "------------------------------------------------------------------"

# 5. Ejecutar el servidor Python dentro de App/src
cd "${APP_DIR}/src"
"${PYTHON_BIN}" web_server.py "${HTTP_PORT}" "0.0.0.0"
