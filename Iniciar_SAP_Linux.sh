#!/usr/bin/env bash
# ==============================================================================
# LANZADOR PORTABLE LINUX - ERP CORPORATIVO COLOMBIA
# Soporta tanto Base de Datos Portable Embebida (Data/db) como PostgreSQL Externo
# configurado en Data/config.json.
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

# 0. Auto-portabilizar Python Linux si no existe
if [ ! -x "${APP_DIR}/runtime/linux/bin/python3" ]; then
    echo "📦 Descargando y configurando Python 3.12 Portable automáticamente..."
    python3 "${APP_DIR}/scripts/portabilizar_entorno.py" --target linux
fi

PYTHON_BIN="${APP_DIR}/runtime/linux/bin/python3"
if [ ! -x "${PYTHON_BIN}" ]; then
    PYTHON_BIN="python3"
fi

# Leer configuración desde Data/config.json (soporta embedded_postgresql y external_postgresql)
CONFIG_FILE="${DATA_DIR}/config.json"
eval "$("${PYTHON_BIN}" - "${CONFIG_FILE}" <<'PYEOF'
import json, os, sys
from urllib.parse import quote_plus
cfg = {}
if len(sys.argv) > 1 and os.path.isfile(sys.argv[1]):
    try:
        with open(sys.argv[1], "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception:
        pass
srv = cfg.get("server", {})
db = cfg.get("database", {})
engine = db.get("engine", "embedded_postgresql")
host = db.get("host", "127.0.0.1") if engine != "embedded_postgresql" else "127.0.0.1"
port = int(db.get("port", 54329 if engine == "embedded_postgresql" else 5432))
user = db.get("user", "sap")
password = db.get("password", "") if engine != "embedded_postgresql" else ""
dbname = db.get("dbname", "sap_colombia")
sslmode = db.get("sslmode", "")
custom_dsn = (db.get("dsn") or "").strip()
if custom_dsn:
    dsn = custom_dsn
else:
    auth = quote_plus(str(user))
    if password:
        auth += f":{quote_plus(str(password))}"
    dsn = f"postgresql://{auth}@{host}:{port}/{dbname}"
    if sslmode:
        dsn += f"?sslmode={quote_plus(str(sslmode))}"
print(f"HTTP_HOST='{srv.get('host', '127.0.0.1')}'")
print(f"HTTP_PORT='{int(srv.get('http_port', 8000))}'")
print(f"DB_ENGINE='{engine}'")
print(f"DB_HOST='{host}'")
print(f"DB_PORT='{port}'")
print(f"DB_USER='{user}'")
print(f"DB_NAME='{dbname}'")
print(f"COMPUTED_DSN='{dsn}'")
PYEOF
)"

export LD_LIBRARY_PATH="${PG_LIB}:${LD_LIBRARY_PATH:-}"
export PGSYSCONFDIR="${DATA_DIR}"
export PGDATA="${DB_DIR}"

echo "=================================================================="
echo " 🚀 ERP CORPORATIVO COLOMBIA - SISTEMA PORTABLE AUTÓNOMO (LINUX)"
echo "=================================================================="
echo "📂 Directorio Base : ${BASE_DIR}"
if [ "${DB_ENGINE}" = "embedded_postgresql" ]; then
    echo "🗄️  Base de Datos   : PORTABLE EMBEBIDA en Data/db (Puerto ${DB_PORT})"
else
    echo "🗄️  Base de Datos   : POSTGRESQL EXTERNO (${DB_HOST}:${DB_PORT}/${DB_NAME})"
fi
echo "🐍 Python Runtime  : ${PYTHON_BIN}"
echo "🌐 Servidor Web    : http://${HTTP_HOST}:${HTTP_PORT}"
echo "🔧 Configurar BD   : Ejecuta ./Portabilizar_Todo.sh para cambiar entre BD Portable o Externa"
echo "=================================================================="

STARTED_PG=0
if [ "${DB_ENGINE}" = "embedded_postgresql" ]; then
    if [ ! -x "${PG_BIN}/postgres" ]; then
        echo "📦 Descargando motor PostgreSQL 17.2 Portable para Linux..."
        "${PYTHON_BIN}" "${APP_DIR}/scripts/portabilizar_entorno.py" --target linux
    fi
    if [ ! -f "${DB_DIR}/PG_VERSION" ]; then
        echo "📦 Inicializando nuevo cluster de base de datos embebido en Data/db..."
        mkdir -p "${DB_DIR}"
        chmod 0700 "${DB_DIR}"
        "${PG_BIN}/initdb" -D "${DB_DIR}" -U "${DB_USER}" --auth=trust -E UTF8 > "${LOGS_DIR}/initdb.log" 2>&1
        echo "✅ Cluster inicializado."
    fi

    echo "🔌 Verificando estado del motor PostgreSQL embebido..."
    if ! "${PG_BIN}/pg_ctl" -D "${DB_DIR}" status > /dev/null 2>&1; then
        echo "⚡ Arrancando motor PostgreSQL en puerto ${DB_PORT}..."
        "${PG_BIN}/pg_ctl" -D "${DB_DIR}" -l "${LOGS_DIR}/postgres.log" -o "-p ${DB_PORT} -k ${DB_DIR}" -w start
        STARTED_PG=1
        echo "✅ Motor PostgreSQL activo."
    else
        echo "ℹ️  Motor PostgreSQL ya se encontraba en ejecución."
    fi
fi

# Asegurar que la base de datos exista (tanto en modo portable como externo)
export SAP_PG_DSN="${COMPUTED_DSN}"
export SAP_DB_HOST="${DB_HOST}"
export SAP_DB_PORT="${DB_PORT}"
export SAP_DB_USER="${DB_USER}"
export SAP_DB_NAME="${DB_NAME}"
export PORT="${HTTP_PORT}"

"${PYTHON_BIN}" "${APP_DIR}/scripts/portabilizar_entorno.py" --ensure-db

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

(sleep 1.2 && (xdg-open "http://127.0.0.1:${HTTP_PORT}" > /dev/null 2>&1 || sensible-browser "http://127.0.0.1:${HTTP_PORT}" > /dev/null 2>&1 || true)) &

echo "✨ Servidor listo. Presiona Ctrl+C en esta terminal para detener el sistema."
echo "------------------------------------------------------------------"

cd "${APP_DIR}/src"
"${PYTHON_BIN}" web_server.py "${HTTP_PORT}" "0.0.0.0"
