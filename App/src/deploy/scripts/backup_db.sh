#!/usr/bin/env bash
# ==============================================================================
# Script de Respaldo Automatizado de Base de Datos PostgreSQL para SAP Colombia
# ==============================================================================
# Diseñado para ejecutarse periódicamente mediante Cron (ej. diario a las 02:00 AM)
# Genera dumps comprimidos .sql.gz y rota los respaldos reteniendo los últimos 14 días.

set -euo pipefail

# Configuración
BACKUP_DIR="${SAP_BACKUP_DIR:-/var/backups/sap_colombia}"
DB_NAME="${SAP_DB_NAME:-sap_colombia}"
DB_USER="${SAP_DB_USER:-sap}"
DB_HOST="${SAP_DB_HOST:-localhost}"
DB_PORT="${SAP_DB_PORT:-5432}"
RETENTION_DAYS=14

# Crear directorio de respaldos si no existe
mkdir -p "${BACKUP_DIR}"

# Timestamp para el nombre de archivo
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_FILE="${BACKUP_DIR}/${DB_NAME}_backup_${TIMESTAMP}.sql.gz"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Iniciando respaldo de la base de datos: ${DB_NAME}..."

# Ejecutar pg_dump con compresión gzip en flujo directo
PGPASSWORD="${PGPASSWORD:-}" pg_dump -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" -d "${DB_NAME}" \
    --no-owner \
    --clean \
    --if-exists \
    --format=plain | gzip -9 > "${BACKUP_FILE}"

# Verificar integridad del respaldo
if [ -s "${BACKUP_FILE}" ]; then
    SIZE=$(du -h "${BACKUP_FILE}" | cut -f1)
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Respaldo completado con éxito: ${BACKUP_FILE} (Tamaño: ${SIZE})"
else
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: El archivo de respaldo está vacío o falló la creación." >&2
    exit 1
fi

# Rotación de respaldos antiguos (más de RETENTION_DAYS días)
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Rotando respaldos con más de ${RETENTION_DAYS} días de antigüedad..."
find "${BACKUP_DIR}" -type f -name "${DB_NAME}_backup_*.sql.gz" -mtime +"${RETENTION_DAYS}" -exec rm -f {} +

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Tarea de respaldo finalizada exitosamente."
