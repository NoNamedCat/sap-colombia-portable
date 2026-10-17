"""Conftest global: asegura BD de pruebas aislada (sap_colombia_test) y limpia el estado entre test files."""
import os
import subprocess
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
PORTABLE_DIR = APP_DIR.parent
SRC_DIR = APP_DIR / "src"
PKG_DIR = SRC_DIR / "sap_colombia"
TESTS_DIR = APP_DIR / "tests"

for p in (str(TESTS_DIR), str(SRC_DIR), str(PKG_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

# Varios tests rotan la contraseña de admin@saluki.com. Con el límite de
# intentos de login activo, los intentos fallidos legítimos de un test bloquean
# los logins de los siguientes (falsos positivos). El límite se desactiva solo
# dentro de la suite; en ejecución real sigue en 5.
os.environ.setdefault("SAP_LOGIN_MAX_INTENTOS", "0")


def _ensure_test_db() -> str:
    """Garantiza que PostgreSQL embebido esté activo y exista la BD aislada sap_colombia_test."""
    pg_bin = APP_DIR / "engine" / "linux" / "bin"
    pg_lib = APP_DIR / "engine" / "linux" / "lib"
    db_dir = PORTABLE_DIR / "Data" / "db"
    logs_dir = PORTABLE_DIR / "Data" / "logs"
    db_port = 54329
    test_db_name = "sap_colombia_test"

    env = os.environ.copy()
    env["LD_LIBRARY_PATH"] = f"{pg_lib}:{env.get('LD_LIBRARY_PATH', '')}"

    if (pg_bin / "pg_ctl").is_file() and (db_dir / "PG_VERSION").is_file():
        status = subprocess.run(
            [str(pg_bin / "pg_ctl"), "-D", str(db_dir), "status"],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if status.returncode != 0:
            logs_dir.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                [
                    str(pg_bin / "pg_ctl"),
                    "-D",
                    str(db_dir),
                    "-l",
                    str(logs_dir / "test_run.log"),
                    "-o",
                    f"-p {db_port} -k {db_dir}",
                    "-w",
                    "start",
                ],
                env=env,
                check=False,
            )

    import psycopg2

    # Crear sap_colombia_test si no existe para NUNCA tocar sap_colombia de producción
    try:
        conn = psycopg2.connect(f"postgresql://sap@127.0.0.1:{db_port}/postgres")
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (test_db_name,))
            if not cur.fetchone():
                cur.execute(f'CREATE DATABASE "{test_db_name}" OWNER sap ENCODING \'UTF8\'')
        conn.close()
    except Exception:
        pass

    dsn = f"postgresql://sap@127.0.0.1:{db_port}/{test_db_name}"
    os.environ["SAP_PG_DSN"] = dsn
    return dsn


_TEST_DSN = _ensure_test_db()

import pytest
from sap_colombia import dbutil
from sap_colombia import database as db

db.PG_DSN = _TEST_DSN


@pytest.fixture(scope="module", autouse=True)
def _reset_state():
    """Resetea el estado del thread-local y la BD de pruebas antes de cada test file."""
    db.PG_DSN = _TEST_DSN
    _tls = db._tls
    if hasattr(_tls, "conn"):
        delattr(_tls, "conn")
    if hasattr(_tls, "empresa_id"):
        delattr(_tls, "empresa_id")
    db.init_db()
    conn = db.get_connection()
    tablas = [
        "pos_sesiones", "pos_cajas", "remisiones_venta", "pedidos_venta", "cotizaciones",
        "comprobantes_egreso", "cuentas_por_pagar", "facturas_compra", "precios_productos", "listas_precios",
        "lineas_nota_credito", "notas_credito", "lineas_nota_debito", "notas_debito",
        "factura_lineas", "facturas", "lineas_documento_soporte", "documentos_soporte",
        "kardex", "stock_actual", "movimientos_contables", "asientos_contables",
        "recibos_caja", "eventos_radian", "nominas", "empleados", "clientes",
        "productos", "bodegas", "periodos_contables", "auditoria", "usuario_empresas",
        "usuarios", "role_permissions", "role_empresa", "permisos"
    ]
    for tabla in tablas:
        try:
            dbutil.query(conn, f"DELETE FROM {tabla}")
            conn.commit()
        except Exception:
            conn.rollback()
    conn.close()
    db.init_db(seed=True)
    from sap_colombia import auth, rbac
    auth.seed_usuarios()
    rbac.ensure_rbac()
    yield

