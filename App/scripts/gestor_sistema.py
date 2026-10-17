#!/usr/bin/env python3
"""
================================================================================
 GESTOR UNIFICADO DE PORTABILIDAD, BASE DE DATOS Y ENTORNO - ERP COLOMBIA
================================================================================
Unifica en una sola herramienta multiplataforma (Linux y Windows):
  1. Descarga y portabilización automática de PostgreSQL 17.2 y Python 3.12 + librerías
     dentro de App/engine/ y App/runtime/.
  2. Gestión de Base de Datos:
     - Modo A: Base de Datos Portable Embebida (guardada en Data/db o Data/db_windows).
     - Modo B: PostgreSQL Externo (Servidor en red local, Docker, AWS RDS, Supabase, etc.).
  3. Separación Global de Entorno (Pruebas vs. Trabajo Real DIAN):
     - Entorno de Pruebas (mock): Usa el Simulador Local sin transmitir a internet y permite
       aislar los datos en una base de datos de pruebas.
     - Entorno de Trabajo Real (real): Conecta globalmente con los Web Services SOAP oficiales
       de la DIAN (Producción o Set de Habilitación).
  4. Exportación e Importación de Respaldo Universal (Data/backups/respaldo_universal.json)
     para migrar datos entre Linux, Windows o un servidor PostgreSQL externo.
  5. Lanzador unificado del ERP (arranca motor si es embebido, verifica BD y lanza Web UI).

Uso por línea de comandos:
  python3 App/scripts/gestor_sistema.py --menu
  python3 App/scripts/gestor_sistema.py --start
  python3 App/scripts/gestor_sistema.py --target all
  python3 App/scripts/gestor_sistema.py --set-db embedded --port 54329
  python3 App/scripts/gestor_sistema.py --set-db external --host 192.168.1.50 --port 5432 --user postgres --password secret --dbname sap_colombia
  python3 App/scripts/gestor_sistema.py --set-dian mock
  python3 App/scripts/gestor_sistema.py --set-dian real --dian-ambiente 2
  python3 App/scripts/gestor_sistema.py --export-backup
  python3 App/scripts/gestor_sistema.py --import-backup
"""

import argparse
import getpass
import io
import json
import os
import platform
import shutil
import signal
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
import webbrowser
import zipfile
from datetime import datetime
from urllib.parse import quote_plus

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
BASE_DIR = os.path.abspath(os.path.join(APP_DIR, ".."))
DATA_DIR = os.path.join(BASE_DIR, "Data")
LOGS_DIR = os.path.join(DATA_DIR, "logs")
BACKUPS_DIR = os.path.join(DATA_DIR, "backups")
CONFIG_PATH = os.path.join(DATA_DIR, "config.json")
REQ_FILE = os.path.join(APP_DIR, "src", "requirements.txt")

PG_LINUX_URL = (
    "https://repo1.maven.org/maven2/io/zonky/test/postgres/"
    "embedded-postgres-binaries-linux-amd64/17.2.0/"
    "embedded-postgres-binaries-linux-amd64-17.2.0.jar"
)
PG_WIN_URL = (
    "https://repo1.maven.org/maven2/io/zonky/test/postgres/"
    "embedded-postgres-binaries-windows-amd64/17.2.0/"
    "embedded-postgres-binaries-windows-amd64-17.2.0.jar"
)
PY_LINUX_URL = (
    "https://github.com/indygreg/python-build-standalone/releases/download/20241016/"
    "cpython-3.12.7+20241016-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz"
)
PY_WIN_URL = "https://www.python.org/ftp/python/3.12.8/python-3.12.8-embed-amd64.zip"


def is_windows_os() -> bool:
    return platform.system().lower().startswith("win")


def load_config() -> dict:
    os.makedirs(DATA_DIR, exist_ok=True)
    default_cfg = {
        "server": {
            "host": "127.0.0.1",
            "http_port": 8000,
        },
        "database": {
            "engine": "embedded_postgresql",
            "host": "127.0.0.1",
            "port": 54329,
            "user": "sap",
            "password": "",
            "dbname": "sap_colombia",
            "test_dbname": "",
            "sslmode": "",
            "dsn": "",
        },
        "dian": {
            "mode": "mock",
            "ambiente": "2",
            "test_set_id": "",
            "user": "",
            "password": "",
            "transmit_url": "",
        },
    }
    if os.path.isfile(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            default_cfg["server"].update(loaded.get("server", {}))
            default_cfg["database"].update(loaded.get("database", {}))
            default_cfg["dian"].update(loaded.get("dian", {}))
        except Exception:
            pass
    return default_cfg


def save_config(cfg: dict) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


def build_dsn_from_cfg(db_cfg: dict, override_dbname: str | None = None) -> str:
    custom_dsn = (db_cfg.get("dsn") or "").strip()
    if custom_dsn and not override_dbname:
        return custom_dsn
    host = db_cfg.get("host") or "127.0.0.1"
    port = int(db_cfg.get("port") or 54329)
    user = db_cfg.get("user") or "sap"
    password = db_cfg.get("password") or ""
    dbname = override_dbname or db_cfg.get("dbname") or "sap_colombia"
    sslmode = db_cfg.get("sslmode") or ""

    auth = quote_plus(str(user))
    if password:
        auth += f":{quote_plus(str(password))}"
    dsn = f"postgresql://{auth}@{host}:{port}/{dbname}"
    if sslmode:
        dsn += f"?sslmode={quote_plus(str(sslmode))}"
    return dsn


# ==============================================================================
# 1. DESCARGA Y PORTABILIZACIÓN DE MOTORES (POSTGRESQL 17.2 + PYTHON 3.12)
# ==============================================================================
def _download_bytes(url: str, desc: str) -> bytes:
    print(f"⬇️  Descargando {desc}...\n   URL: {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "SAP-Colombia-Portabilizer/2.0"})
    with urllib.request.urlopen(req, timeout=180) as resp:
        total = int(resp.headers.get("Content-Length") or 0)
        chunks = []
        downloaded = 0
        while True:
            buf = resp.read(1024 * 256)
            if not buf:
                break
            chunks.append(buf)
            downloaded += len(buf)
            if total > 0:
                pct = (downloaded * 100) // total
                mb = downloaded / (1024 * 1024)
                tmb = total / (1024 * 1024)
                sys.stdout.write(f"\r   Progreso: {mb:.1f} MB / {tmb:.1f} MB ({pct}%)")
                sys.stdout.flush()
        if total > 0:
            sys.stdout.write("\n")
    return b"".join(chunks)


def _extract_zonky_pg(jar_bytes: bytes, dest_dir: str, is_windows: bool):
    os.makedirs(dest_dir, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(jar_bytes)) as zf:
        txz_names = [n for n in zf.namelist() if n.endswith(".txz")]
        if not txz_names:
            raise RuntimeError("No se encontró archivo .txz dentro del paquete de PostgreSQL")
        txz_bytes = zf.read(txz_names[0])

    print(f"📦 Extrayendo PostgreSQL 17.2 en {dest_dir}...")
    with tarfile.open(fileobj=io.BytesIO(txz_bytes), mode="r:xz") as tf:
        tf.extractall(dest_dir)

    if not is_windows:
        bin_dir = os.path.join(dest_dir, "bin")
        if os.path.isdir(bin_dir):
            for fname in os.listdir(bin_dir):
                fpath = os.path.join(bin_dir, fname)
                if os.path.isfile(fpath):
                    st = os.stat(fpath)
                    os.chmod(fpath, st.st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def setup_linux_postgres(force: bool = False):
    dest = os.path.join(APP_DIR, "engine", "linux")
    pg_bin = os.path.join(dest, "bin", "postgres")
    if os.path.exists(pg_bin) and not force:
        print(f"✅ PostgreSQL Portable Linux ya está instalado en: {dest}")
        return
    jar_bytes = _download_bytes(PG_LINUX_URL, "PostgreSQL 17.2 Portable (Linux x86_64)")
    _extract_zonky_pg(jar_bytes, dest, is_windows=False)
    print(f"✅ PostgreSQL 17.2 Linux listo en: {dest}")


def setup_windows_postgres(force: bool = False):
    dest = os.path.join(APP_DIR, "engine", "windows")
    pg_bin = os.path.join(dest, "bin", "postgres.exe")
    if os.path.exists(pg_bin) and not force:
        print(f"✅ PostgreSQL Portable Windows ya está instalado en: {dest}")
        return
    jar_bytes = _download_bytes(PG_WIN_URL, "PostgreSQL 17.2 Portable (Windows x86_64)")
    _extract_zonky_pg(jar_bytes, dest, is_windows=True)
    print(f"✅ PostgreSQL 17.2 Windows listo en: {dest}")


def setup_linux_python(force: bool = False):
    dest = os.path.join(APP_DIR, "runtime", "linux")
    py_bin = os.path.join(dest, "bin", "python3")
    if not os.path.exists(py_bin) or force:
        tar_bytes = _download_bytes(PY_LINUX_URL, "Python 3.12.7 Standalone (Linux x86_64)")
        if os.path.exists(dest):
            shutil.rmtree(dest)
        os.makedirs(dest, exist_ok=True)
        print(f"📦 Extrayendo Python 3.12 Linux en {dest}...")
        with tempfile.TemporaryDirectory() as tmpdir:
            with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:gz") as tf:
                tf.extractall(tmpdir)
            extracted_py = os.path.join(tmpdir, "python")
            if os.path.isdir(extracted_py):
                for item in os.listdir(extracted_py):
                    shutil.move(os.path.join(extracted_py, item), os.path.join(dest, item))
    else:
        print(f"✅ Python Portable Linux ya existe en: {dest}")

    print("📦 Verificando librerías requeridas dentro de App/runtime/linux...")
    subprocess.run(
        [py_bin, "-m", "pip", "install", "--quiet", "-r", REQ_FILE],
        check=True,
    )
    print(f"✅ Python 3.12 Linux + librerías listos en: {dest}")


def setup_windows_python(force: bool = False):
    dest = os.path.join(APP_DIR, "runtime", "windows")
    py_exe = os.path.join(dest, "python.exe")
    site_packages = os.path.join(dest, "Lib", "site-packages")

    if not os.path.exists(py_exe) or force:
        zip_bytes = _download_bytes(PY_WIN_URL, "Python 3.12.8 Embeddable (Windows x86_64)")
        if os.path.exists(dest):
            shutil.rmtree(dest)
        os.makedirs(dest, exist_ok=True)
        print(f"📦 Extrayendo Python 3.12.8 Windows en {dest}...")
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            zf.extractall(dest)

        pth_file = os.path.join(dest, "python312._pth")
        pth_content = (
            "python312.zip\n"
            ".\n"
            "Lib\\site-packages\n"
            "..\\..\\src\n"
            "import site\n"
        )
        with open(pth_file, "w", encoding="utf-8") as f:
            f.write(pth_content)

    os.makedirs(site_packages, exist_ok=True)
    if os.path.exists(os.path.join(site_packages, "psycopg2")) and not force:
        print(f"✅ Librerías Windows ya instaladas en: {site_packages}")
        return

    print("📦 Descargando e instalando paquetes binarios Windows x64 (wheels) en App/runtime/windows/Lib/site-packages...")
    win_packages = [
        "psycopg2-binary>=2.9",
        "pyjwt>=2.7",
        "cryptography>=41.0",
        "lxml>=5.0",
        "qrcode>=7.0",
        "reportlab>=4.0",
        "requests>=2.31",
    ]
    with tempfile.TemporaryDirectory() as wheel_dir:
        pip_cmd = [
            sys.executable,
            "-m",
            "pip",
            "download",
            "--quiet",
            "--dest",
            wheel_dir,
            "--platform",
            "win_amd64",
            "--python-version",
            "312",
            "--implementation",
            "cp",
            "--abi",
            "cp312",
            "--only-binary=:all:",
        ] + win_packages
        subprocess.run(pip_cmd, check=True)

        for fname in os.listdir(wheel_dir):
            if fname.endswith(".whl"):
                wpath = os.path.join(wheel_dir, fname)
                with zipfile.ZipFile(wpath) as wf:
                    wf.extractall(site_packages)

    print(f"✅ Python 3.12.8 Windows + librerías nativas (win_amd64) listos en: {dest}")


# ==============================================================================
# 2. GESTIÓN DE BASE DE DATOS (EMBEBIDA PORTABLE vs POSTGRESQL EXTERNO)
# ==============================================================================
def ensure_database_exists(db_cfg: dict | None = None):
    """Verifica conexión al servidor PostgreSQL (embebido o externo) y crea la BD si no existe."""
    import psycopg2
    from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

    if db_cfg is None:
        db_cfg = active_db_cfg()

    dbname = db_cfg.get("dbname") or os.environ.get("SAP_DB_NAME") or "sap_colombia"
    target_dsn = build_dsn_from_cfg(db_cfg)
    admin_dsn = build_dsn_from_cfg(db_cfg, override_dbname="postgres")

    try:
        conn = psycopg2.connect(target_dsn)
        conn.close()
        return True
    except Exception:
        pass

    conn = psycopg2.connect(admin_dsn)
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (dbname,))
    exists = cur.fetchone() is not None
    if not exists:
        print(f"🗄️  Creando base de datos '{dbname}'...")
        cur.execute(f'CREATE DATABASE "{dbname}" ENCODING \'UTF8\'')
    cur.close()
    conn.close()
    return True


# ------------------------------------------------------------------------------
# Separación de bases de datos: PRUEBAS vs REAL
# ------------------------------------------------------------------------------
def is_test_mode(cfg: dict | None = None) -> bool:
    cfg = cfg or load_config()
    return cfg.get("dian", {}).get("mode") != "real"


def real_dbname(cfg: dict) -> str:
    return cfg["database"].get("dbname") or "sap_colombia"


def test_dbname(cfg: dict) -> str:
    name = (cfg["database"].get("test_dbname") or "").strip()
    return name or f"{real_dbname(cfg)}_pruebas"


def db_cfg_for(cfg: dict, which: str) -> dict:
    """Devuelve una copia de la configuración de BD apuntando a 'real' o 'test'."""
    db = dict(cfg["database"])
    db["dbname"] = test_dbname(cfg) if which == "test" else real_dbname(cfg)
    if which == "test":
        db["dsn"] = ""  # un DSN personalizado siempre apunta a la BD real
    return db


def active_db_cfg(cfg: dict | None = None) -> dict:
    """BD que usa el ERP según el entorno global: pruebas -> BD de pruebas; real -> BD real."""
    cfg = cfg or load_config()
    return db_cfg_for(cfg, "test" if is_test_mode(cfg) else "real")


def active_dbname(cfg: dict | None = None) -> str:
    """Retorna el nombre de la BD activa actual."""
    return active_db_cfg(cfg)["dbname"]


def clone_real_to_test(assume_yes: bool = False) -> bool:
    """Copia TODA la base de datos real sobre la base de datos de pruebas.

    La BD real solo se LEE; la BD de pruebas se borra y se recrea.
    1) Intento rápido: CREATE DATABASE <pruebas> TEMPLATE <real> (copia binaria exacta).
    2) Si la BD real tiene conexiones activas (ERP en ejecución), copia tabla por tabla
       con COPY, preservando el esquema y reajustando las secuencias.
    """
    import io as _io
    import psycopg2
    from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

    cfg = load_config()
    src_cfg = db_cfg_for(cfg, "real")
    dst_cfg = db_cfg_for(cfg, "test")
    src, dst = src_cfg["dbname"], dst_cfg["dbname"]
    if src == dst:
        print("⛔ La BD de pruebas no puede tener el mismo nombre que la BD real.")
        return False

    print(f"\n🔁 Migrar BD REAL '{src}'  ➜  BD de PRUEBAS '{dst}'")
    print(f"   ⚠️  Todo el contenido actual de '{dst}' será reemplazado. '{src}' NO se modifica.")
    if not assume_yes:
        ok = input("   ¿Continuar? escribe 'si' para confirmar: ").strip().lower()
        if ok not in ("si", "sí", "s", "y", "yes"):
            print("   Operación cancelada.")
            return False

    ensure_database_exists(src_cfg)
    admin = psycopg2.connect(build_dsn_from_cfg(src_cfg, override_dbname="postgres"))
    admin.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    acur = admin.cursor()

    # Cerrar conexiones a la BD de pruebas y eliminarla
    acur.execute(
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
        "WHERE datname = %s AND pid <> pg_backend_pid()", (dst,)
    )
    acur.execute(f'DROP DATABASE IF EXISTS "{dst}"')

    # 1) Copia binaria vía TEMPLATE
    try:
        acur.execute(f'CREATE DATABASE "{dst}" TEMPLATE "{src}" ENCODING \'UTF8\'')
        acur.close()
        admin.close()
        print(f"✅ BD de pruebas '{dst}' clonada exactamente desde '{src}' (TEMPLATE).")
        return True
    except psycopg2.Error as e:
        print(f"ℹ️  Copia rápida no disponible ({str(e).strip().splitlines()[0]}). Usando copia tabla por tabla...")
        acur.execute(f'DROP DATABASE IF EXISTS "{dst}"')
        acur.execute(f'CREATE DATABASE "{dst}" ENCODING \'UTF8\'')
    acur.close()
    admin.close()

    # 2) Crear el esquema del ERP en la BD de pruebas
    dst_dsn = build_dsn_from_cfg(dst_cfg)
    sys.path.insert(0, os.path.join(APP_DIR, "src"))
    prev_dsn = os.environ.get("SAP_PG_DSN")
    os.environ["SAP_PG_DSN"] = dst_dsn
    try:
        from sap_colombia import database as sap_db
        if hasattr(sap_db, "init_db"):
            sap_db.init_db(seed=False)
        elif hasattr(sap_db, "inicializar_base_datos"):
            sap_db.inicializar_base_datos()
    finally:
        if prev_dsn is None:
            os.environ.pop("SAP_PG_DSN", None)
        else:
            os.environ["SAP_PG_DSN"] = prev_dsn

    s_conn = psycopg2.connect(build_dsn_from_cfg(src_cfg))
    s_conn.set_session(readonly=True)
    d_conn = psycopg2.connect(dst_dsn)
    s_cur, d_cur = s_conn.cursor(), d_conn.cursor()

    s_cur.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema='public' AND table_type='BASE TABLE' ORDER BY table_name"
    )
    tables = [r[0] for r in s_cur.fetchall()]
    d_cur.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema='public' AND table_type='BASE TABLE'"
    )
    dst_tables = {r[0] for r in d_cur.fetchall()}

    # Desactivar FKs/triggers durante la carga (requiere superusuario; en BD portable lo es)
    try:
        d_cur.execute("SET session_replication_role = replica")
    except psycopg2.Error:
        d_conn.rollback()

    if dst_tables:
        d_cur.execute("TRUNCATE " + ", ".join(f'"{t}"' for t in dst_tables) + " RESTART IDENTITY CASCADE")

    total = 0
    for t in tables:
        if t not in dst_tables:
            continue
        # Solo columnas comunes, en el orden de la BD real
        s_cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name=%s ORDER BY ordinal_position", (t,)
        )
        s_cols = [r[0] for r in s_cur.fetchall()]
        d_cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name=%s", (t,)
        )
        d_cols = {r[0] for r in d_cur.fetchall()}
        cols = ", ".join(f'"{c}"' for c in s_cols if c in d_cols)
        buf = _io.StringIO()
        s_cur.copy_expert(f'COPY "{t}" ({cols}) TO STDOUT', buf)
        buf.seek(0)
        d_cur.copy_expert(f'COPY "{t}" ({cols}) FROM STDIN', buf)
        total += d_cur.rowcount if d_cur.rowcount and d_cur.rowcount > 0 else 0

    # Reajustar secuencias (serial / identity) al MAX(id) copiado
    d_cur.execute(
        "SELECT table_name, column_name FROM information_schema.columns "
        "WHERE table_schema='public' AND (column_default LIKE 'nextval(%%' OR is_identity='YES')"
    )
    for t, c in d_cur.fetchall():
        d_cur.execute("SELECT pg_get_serial_sequence(%s, %s)", (f'public."{t}"', c))
        seq = d_cur.fetchone()[0]
        if seq:
            d_cur.execute(
                f'SELECT setval(%s, COALESCE((SELECT MAX("{c}") FROM "{t}"), 0) + 1, false)', (seq,)
            )

    d_conn.commit()
    s_cur.close(); d_cur.close(); s_conn.close(); d_conn.close()
    print(f"✅ BD de pruebas '{dst}' poblada desde '{src}' ({len(tables)} tablas, {total} registros).")
    return True


def reset_test_db(assume_yes: bool = False) -> bool:
    """Borra la BD de pruebas y la deja vacía (esquema limpio)."""
    import psycopg2
    from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

    cfg = load_config()
    dst_cfg = db_cfg_for(cfg, "test")
    dst = dst_cfg["dbname"]
    if not assume_yes:
        ok = input(f"⚠️  Se borrará por completo la BD de pruebas '{dst}'. Escribe 'si' para confirmar: ").strip().lower()
        if ok not in ("si", "sí", "s", "y", "yes"):
            print("   Operación cancelada.")
            return False
    admin = psycopg2.connect(build_dsn_from_cfg(dst_cfg, override_dbname="postgres"))
    admin.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    cur = admin.cursor()
    cur.execute(
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
        "WHERE datname = %s AND pid <> pg_backend_pid()", (dst,)
    )
    cur.execute(f'DROP DATABASE IF EXISTS "{dst}"')
    cur.execute(f'CREATE DATABASE "{dst}" ENCODING \'UTF8\'')
    cur.close()
    admin.close()

    # Inicializar el esquema limpio en la BD de pruebas
    dst_dsn = build_dsn_from_cfg(dst_cfg)
    sys.path.insert(0, os.path.join(APP_DIR, "src"))
    prev_dsn = os.environ.get("SAP_PG_DSN")
    os.environ["SAP_PG_DSN"] = dst_dsn
    try:
        from sap_colombia import database as sap_db
        sap_db.PG_DSN = dst_dsn
        sap_db.init_db(seed=False)
        from sap_colombia import auth
        auth.seed_usuarios()
        if not assume_yes:
            pob = input("\n¿Deseas poblar la BD de pruebas con datos demo para ensayar de inmediato? (s/n) [s]: ").strip().lower()
            if pob in ("", "s", "si", "y", "yes"):
                from sap_colombia import demo_data
                demo_data.sembrar_datos_demo()
                print("🌱 Datos de demostración sembrados en la BD de pruebas.")
            else:
                print("✨ BD de pruebas inicializada limpia (sin datos demo).")
        else:
            print(f"✅ BD de pruebas '{dst}' reiniciada limpia.")
    finally:
        if prev_dsn is None:
            os.environ.pop("SAP_PG_DSN", None)
        else:
            os.environ["SAP_PG_DSN"] = prev_dsn
    return True


def export_universal_backup(custom_path: str | None = None) -> str:
    """Exporta todas las tablas de la base de datos activa a un archivo JSON portable universal."""
    import psycopg2
    import psycopg2.extras

    os.makedirs(BACKUPS_DIR, exist_ok=True)
    cfg = load_config()
    dsn = build_dsn_from_cfg(active_db_cfg(cfg))
    conn = psycopg2.connect(dsn, cursor_factory=psycopg2.extras.RealDictCursor)
    cur = conn.cursor()

    cur.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_type = 'BASE TABLE' ORDER BY table_name"
    )
    tables = [r["table_name"] for r in cur.fetchall()]

    dump_data = {
        "exported_at": datetime.now().isoformat(),
        "database_engine": cfg["database"].get("engine"),
        "tables": {},
    }

    for tbl in tables:
        cur.execute(f'SELECT * FROM "{tbl}"')
        rows = [dict(r) for r in cur.fetchall()]
        dump_data["tables"][tbl] = rows

    cur.close()
    conn.close()

    out_path = custom_path or os.path.join(BACKUPS_DIR, "respaldo_universal.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(dump_data, f, indent=2, ensure_ascii=False, default=str)

    total_rows = sum(len(v) for v in dump_data["tables"].values())
    print(f"✅ Respaldo portable universal exportado: {out_path} ({len(tables)} tablas, {total_rows} registros)")
    return out_path


def import_universal_backup(custom_path: str | None = None) -> None:
    """Restaura un respaldo portable universal en la base de datos activa (portable o externa)."""
    import psycopg2

    in_path = custom_path or os.path.join(BACKUPS_DIR, "respaldo_universal.json")
    if not os.path.isfile(in_path):
        print(f"⚠️ No se encontró el archivo de respaldo en: {in_path}")
        return

    with open(in_path, "r", encoding="utf-8") as f:
        dump_data = json.load(f)

    cfg = load_config()
    ensure_database_exists(active_db_cfg(cfg))
    dsn = build_dsn_from_cfg(active_db_cfg(cfg))

    # Asegurar que el esquema esté creado antes de importar
    sys.path.insert(0, os.path.join(APP_DIR, "src"))
    os.environ["SAP_PG_DSN"] = dsn
    from sap_colombia import database as sap_db
    if hasattr(sap_db, "init_db"):
        sap_db.init_db(seed=False)
    elif hasattr(sap_db, "inicializar_base_datos"):
        sap_db.inicializar_base_datos()

    conn = psycopg2.connect(dsn)
    cur = conn.cursor()
    tables_data = dump_data.get("tables", {})

    for tbl, rows in tables_data.items():
        if not rows:
            continue
        cols = list(rows[0].keys())
        col_list = ", ".join(f'"{c}"' for c in cols)
        placeholders = ", ".join(["%s"] * len(cols))
        cur.execute(f'TRUNCATE TABLE "{tbl}" RESTART IDENTITY CASCADE')
        for r in rows:
            vals = [r[c] for c in cols]
            cur.execute(
                f'INSERT INTO "{tbl}" ({col_list}) VALUES ({placeholders}) ON CONFLICT DO NOTHING',
                vals,
            )
    conn.commit()
    cur.close()
    conn.close()
    print(f"✅ Respaldo universal restaurado exitosamente desde: {in_path}")


# ==============================================================================
# 3. ARRANQUE UNIFICADO DEL SISTEMA (EMBEBIDO O EXTERNO)
# ==============================================================================
def ensure_db_server_running(cfg: dict | None = None):
    """Arranca el motor PostgreSQL portable si corresponde.

    Devuelve (started, pg_ctl_bin, db_dir). En modo externo no hace nada.
    """
    cfg = cfg or load_config()
    db_cfg = cfg["database"]
    if db_cfg.get("engine", "embedded_postgresql") != "embedded_postgresql":
        return False, None, None

    win = is_windows_os()
    os.makedirs(LOGS_DIR, exist_ok=True)
    db_port = int(db_cfg.get("port", 54329))
    db_user = db_cfg.get("user", "sap")
    if win:
        setup_windows_postgres()
        pg_bin_dir = os.path.join(APP_DIR, "engine", "windows", "bin")
        initdb_bin = os.path.join(pg_bin_dir, "initdb.exe")
        pg_ctl_bin = os.path.join(pg_bin_dir, "pg_ctl.exe")
        db_dir = os.path.join(DATA_DIR, "db_windows")
    else:
        setup_linux_postgres()
        pg_bin_dir = os.path.join(APP_DIR, "engine", "linux", "bin")
        pg_lib_dir = os.path.join(APP_DIR, "engine", "linux", "lib")
        os.environ["LD_LIBRARY_PATH"] = f"{pg_lib_dir}:{os.environ.get('LD_LIBRARY_PATH', '')}"
        initdb_bin = os.path.join(pg_bin_dir, "initdb")
        pg_ctl_bin = os.path.join(pg_bin_dir, "pg_ctl")
        db_dir = os.path.join(DATA_DIR, "db")

    os.makedirs(db_dir, exist_ok=True)
    if not win:
        try:
            os.chmod(db_dir, 0o700)
        except Exception:
            pass

    if not os.path.isfile(os.path.join(db_dir, "PG_VERSION")):
        print(f"📦 Inicializando cluster de Base de Datos Portable en: {db_dir}...")
        init_cmd = [initdb_bin, "-D", db_dir, "-U", db_user, "--auth=trust", "-E", "UTF8"]
        if win:
            init_cmd.append("--no-locale")
        with open(os.path.join(LOGS_DIR, "initdb.log"), "w") as logf:
            subprocess.run(init_cmd, stdout=logf, stderr=subprocess.STDOUT, check=True)
        print("✅ Cluster portable inicializado.")

    status_res = subprocess.run([pg_ctl_bin, "-D", db_dir, "status"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if status_res.returncode == 0:
        print("ℹ️  Motor PostgreSQL Portable ya se encontraba en ejecución.")
        return False, pg_ctl_bin, db_dir

    print(f"⚡ Arrancando motor PostgreSQL Portable en puerto {db_port}...")
    pg_log = os.path.join(LOGS_DIR, "postgres.log")
    pg_opts = f"-p {db_port} -h 127.0.0.1" if win else f"-p {db_port} -k {db_dir}"
    subprocess.run([pg_ctl_bin, "-D", db_dir, "-l", pg_log, "-o", pg_opts, "-w", "start"], check=True)
    print("✅ Motor PostgreSQL Portable activo.")
    return True, pg_ctl_bin, db_dir


def stop_db_server(started: bool, pg_ctl_bin: str | None, db_dir: str | None) -> None:
    if started and pg_ctl_bin and db_dir:
        subprocess.run([pg_ctl_bin, "-D", db_dir, "-m", "fast", "-w", "stop"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def with_db_server(fn, *args, **kwargs):
    """Ejecuta fn con el motor de BD disponible y lo apaga después si lo arrancamos aquí."""
    started, pg_ctl_bin, db_dir = ensure_db_server_running()
    try:
        return fn(*args, **kwargs)
    finally:
        stop_db_server(started, pg_ctl_bin, db_dir)


def start_erp_system():
    cfg = load_config()
    srv_cfg = cfg["server"]
    db_cfg = active_db_cfg(cfg)
    engine_mode = db_cfg.get("engine", "embedded_postgresql")
    http_host = srv_cfg.get("host", "127.0.0.1")
    http_port = int(srv_cfg.get("http_port", 8000))

    os.makedirs(LOGS_DIR, exist_ok=True)
    win = is_windows_os()

    # Asegurar que el runtime Python del SO actual esté listo
    if win:
        py_bin = os.path.join(APP_DIR, "runtime", "windows", "python.exe")
        if not os.path.isfile(py_bin):
            setup_windows_python()
        if not os.path.isfile(py_bin):
            py_bin = sys.executable
    else:
        py_bin = os.path.join(APP_DIR, "runtime", "linux", "bin", "python3")
        if not os.path.isfile(py_bin):
            setup_linux_python()
        if not os.path.isfile(py_bin):
            py_bin = sys.executable

    started_embedded_pg, pg_ctl_bin, db_dir = ensure_db_server_running(cfg)
    if engine_mode == "embedded_postgresql":
        db_cfg["host"] = "127.0.0.1"
    else:
        print(f"🌐 Modo PostgreSQL EXTERNO activo -> {db_cfg.get('host')}:{db_cfg.get('port')}/{db_cfg.get('dbname')}")

    # 3. Asegurar que la base de datos exista (embebida o externa)
    ensure_database_exists(db_cfg)
    dsn = build_dsn_from_cfg(db_cfg)
    dian_cfg = cfg.get("dian", {})
    dian_mode_val = "real" if dian_cfg.get("mode") == "real" else "mock"
    if dian_mode_val == "real":
        amb_label = "Producción Oficial" if str(dian_cfg.get("ambiente")) == "2" else "Habilitación DIAN"
        dian_desc = f"🚀 TRABAJO REAL — SERVIDOR DIAN ({amb_label})"
    else:
        dian_desc = "🧪 ENTORNO DE PRUEBAS — SIMULADOR LOCAL (Sin envío a DIAN)"

    print("==================================================================")
    print(" 🚀 ERP CORPORATIVO COLOMBIA - SISTEMA EN EJECUCIÓN")
    print("==================================================================")
    print(f"📂 Directorio Base : {BASE_DIR}")
    if engine_mode == "embedded_postgresql":
        print(f"🗄️  Base de Datos   : PORTABLE EMBEBIDA ({db_dir} - Puerto {db_cfg.get('port')} - BD: {db_cfg.get('dbname')})")
    else:
        print(f"🗄️  Base de Datos   : POSTGRESQL EXTERNO ({db_cfg.get('host')}:{db_cfg.get('port')}/{db_cfg.get('dbname')})")
    print(f"🏛️  Entorno Global  : {dian_desc}")
    print(f"🐍 Python Runtime  : {py_bin}")
    print(f"🌐 Interfaz Web    : http://127.0.0.1:{http_port}")
    print(f"📖 Tutorial Visual : http://127.0.0.1:{http_port}/tutorial/index.html")
    print("==================================================================")

    env = os.environ.copy()
    env["SAP_PG_DSN"] = dsn
    env["SAP_DB_HOST"] = str(db_cfg.get("host", "127.0.0.1"))
    env["SAP_DB_PORT"] = str(db_cfg.get("port", 54329))
    env["SAP_DB_USER"] = str(db_cfg.get("user", "sap"))
    env["SAP_DB_PASSWORD"] = str(db_cfg.get("password", ""))
    env["SAP_DB_NAME"] = str(db_cfg.get("dbname", "sap_colombia"))
    env["SAP_DIAN_MODE"] = str(dian_mode_val)
    if dian_cfg.get("ambiente"):
        env["SAP_DIAN_AMBIENTE"] = str(dian_cfg["ambiente"])
    if dian_cfg.get("test_set_id"):
        env["SAP_DIAN_TEST_SET_ID"] = str(dian_cfg["test_set_id"])
    if dian_cfg.get("user"):
        env["SAP_DIAN_USER"] = str(dian_cfg["user"])
    if dian_cfg.get("password"):
        env["SAP_DIAN_PASSWORD"] = str(dian_cfg["password"])
    if dian_cfg.get("transmit_url"):
        env["SAP_DIAN_TRANSMIT_URL"] = str(dian_cfg["transmit_url"])
    env["PORT"] = str(http_port)
    env["PYTHONPATH"] = os.path.join(APP_DIR, "src")

    def _stop_pg():
        if started_embedded_pg and pg_ctl_bin and db_dir:
            print("\n🛑 Deteniendo motor PostgreSQL Portable de forma segura...")
            subprocess.run([pg_ctl_bin, "-D", db_dir, "-m", "fast", "-w", "stop"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print("👋 Sistema cerrado correctamente.")

    # Abrir navegador tras 1.2 segundos
    def _open_browser():
        time.sleep(1.2)
        try:
            webbrowser.open(f"http://127.0.0.1:{http_port}")
        except Exception:
            pass

    import threading
    threading.Thread(target=_open_browser, daemon=True).start()

    try:
        subprocess.run(
            [py_bin, "web_server.py", str(http_port), http_host],
            cwd=os.path.join(APP_DIR, "src"),
            env=env,
        )
    except KeyboardInterrupt:
        pass
    finally:
        _stop_pg()


def poblar_demo_wrapper(assume_yes: bool = False):
    cfg = load_config()
    db_cfg = active_db_cfg(cfg)
    ensure_database_exists(db_cfg)
    dsn = build_dsn_from_cfg(db_cfg)
    prev = os.environ.get("SAP_PG_DSN")
    os.environ["SAP_PG_DSN"] = dsn
    try:
        sys.path.insert(0, os.path.join(APP_DIR, "src"))
        from sap_colombia import database as sap_db
        sap_db.PG_DSN = dsn
        sap_db.init_db(seed=False)
        from sap_colombia import demo_data
        print(f"\n🌱 Sembrando datos de demostración en '{db_cfg['dbname']}'...")
        res = demo_data.sembrar_datos_demo()
        print("✅ Datos de demostración sembrados con éxito:")
        print(f"   • Empresas creadas : {res.get('empresas', 0)} (Empresa Corporativa y Inversiones Andinas)")
        print(f"   • Clientes creados : {res.get('clientes', 0)}")
        print(f"   • Productos creados: {res.get('productos', 0)} (P001 - P005 con tarifas IVA)")
        print(f"   • Empleados creados: {res.get('empleados', 0)}")
        print(f"   • Usuarios creados : {res.get('usuarios', 0)} (gerente, contador, vendedor, etc.)")
    finally:
        if prev is None:
            os.environ.pop("SAP_PG_DSN", None)
        else:
            os.environ["SAP_PG_DSN"] = prev


def limpiar_demo_wrapper(assume_yes: bool = False, full: bool = False):
    cfg = load_config()
    db_cfg = active_db_cfg(cfg)
    ensure_database_exists(db_cfg)
    dsn = build_dsn_from_cfg(db_cfg)
    db_name = db_cfg['dbname']
    print(f"\n⚠️  ATENCIÓN: Se procederá a LIMPIAR los datos de demostración de '{db_name}'.")
    print("   Se preservará siempre el catálogo PUC, parámetros DIAN y el Superadministrador (admin@sistema.com).")
    if not assume_yes:
        confirm = input(f"¿Estás seguro de que deseas limpiar los datos demo de '{db_name}'? (s/n) [n]: ").strip().lower()
        if confirm not in ("s", "si", "y", "yes"):
            print("   Operación cancelada.")
            return
    prev = os.environ.get("SAP_PG_DSN")
    os.environ["SAP_PG_DSN"] = dsn
    try:
        sys.path.insert(0, os.path.join(APP_DIR, "src"))
        from sap_colombia import database as sap_db
        sap_db.PG_DSN = dsn
        from sap_colombia import demo_data
        demo_data.limpiar_datos_demo(solo_ficticios=not full)
        print(f"✨ Base de datos '{db_name}' limpia con éxito. Lista para producción.")
        print("   Acceso inicial preservado: admin@sistema.com / admin123")
    finally:
        if prev is None:
            os.environ.pop("SAP_PG_DSN", None)
        else:
            os.environ["SAP_PG_DSN"] = prev


def estado_demo_wrapper():
    cfg = load_config()
    db_cfg = active_db_cfg(cfg)
    ensure_database_exists(db_cfg)
    dsn = build_dsn_from_cfg(db_cfg)
    prev = os.environ.get("SAP_PG_DSN")
    os.environ["SAP_PG_DSN"] = dsn
    try:
        sys.path.insert(0, os.path.join(APP_DIR, "src"))
        from sap_colombia import database as sap_db
        sap_db.PG_DSN = dsn
        from sap_colombia import demo_data
        st = demo_data.estado_datos_demo()
        print(f"\n📊 Estado de la base de datos activa: '{db_cfg['dbname']}'")
        print(f"   • Empresas registradas : {st['total_empresas']} (Demo: {st['empresas_demo']})")
        print(f"   • Clientes registrados : {st['total_clientes']}")
        print(f"   • Productos registrados: {st['total_productos']}")
        print(f"   • Usuarios registrados : {st['total_usuarios']} (Demo: {st['usuarios_demo']})")
        if st["tiene_demo"]:
            print("   👉 Diagnóstico: 🌱 CONTIENE DATOS DE DEMOSTRACIÓN (Para vaciar: --clean-demo)")
        elif st["es_limpio"]:
            print("   👉 Diagnóstico: ✨ SISTEMA LIMPIO / PRODUCCIÓN (Para poblar demo: --seed-demo)")
        else:
            print("   👉 Diagnóstico: 🏢 DATOS DE PRODUCCIÓN REALES REGISTRADOS")
    finally:
        if prev is None:
            os.environ.pop("SAP_PG_DSN", None)
        else:
            os.environ["SAP_PG_DSN"] = prev


# ==============================================================================
# 4. MENÚ INTERACTIVO UNIFICADO DE CONFIGURACIÓN Y PORTABILIZACIÓN
# ==============================================================================
def print_status_banner():
    cfg = load_config()
    db_cfg = cfg["database"]
    srv_cfg = cfg["server"]
    dian_cfg = cfg.get("dian", {})
    engine = db_cfg.get("engine", "embedded_postgresql")
    dian_mode = "real" if dian_cfg.get("mode") == "real" else "mock"
    if dian_mode == "real":
        amb_txt = "Producción Oficial (2)" if str(dian_cfg.get("ambiente")) == "2" else "Habilitación DIAN (1)"
        dian_label = f"🚀 TRABAJO REAL — SERVIDOR DIAN ({amb_txt})"
    else:
        dian_label = "🧪 ENTORNO DE PRUEBAS — SIMULADOR LOCAL (Sin envío a DIAN)"

    linux_pg_ok = os.path.isfile(os.path.join(APP_DIR, "engine", "linux", "bin", "postgres"))
    linux_py_ok = os.path.isfile(os.path.join(APP_DIR, "runtime", "linux", "bin", "python3"))
    win_pg_ok = os.path.isfile(os.path.join(APP_DIR, "engine", "windows", "bin", "postgres.exe"))
    win_py_ok = os.path.isfile(os.path.join(APP_DIR, "runtime", "windows", "python.exe"))

    demo_status_txt = "—"
    try:
        sys.path.insert(0, os.path.join(APP_DIR, "src"))
        from sap_colombia import demo_data
        dsn_act = build_dsn_from_cfg(active_db_cfg(cfg))
        prev_dsn = os.environ.get("SAP_PG_DSN")
        os.environ["SAP_PG_DSN"] = dsn_act
        from sap_colombia import database as sap_db
        sap_db.PG_DSN = dsn_act
        st = demo_data.estado_datos_demo()
        if prev_dsn is None:
            os.environ.pop("SAP_PG_DSN", None)
        else:
            os.environ["SAP_PG_DSN"] = prev_dsn
        if st["tiene_demo"]:
            demo_status_txt = f"🌱 Con Datos Demo ({st['total_empresas']} emp, {st['total_clientes']} cli, {st['total_productos']} prod)"
        elif st["es_limpio"]:
            demo_status_txt = "✨ Sistema Limpio (Listo para Producción · 0 empresas)"
        else:
            demo_status_txt = f"🏢 Datos Reales de Producción ({st['total_empresas']} emp registradas)"
    except Exception:
        pass

    print("\n======================================================================")
    print(" 🎛️  PANEL DE CONTROL Y PORTABILIDAD — ERP CORPORATIVO COLOMBIA")
    print("======================================================================")
    if engine == "embedded_postgresql":
        print(f" 🗄️  Servidor de BD     : PORTABLE EMBEBIDO en Data/ (Puerto {db_cfg.get('port', 54329)})")
    else:
        print(f" 🗄️  Servidor de BD     : POSTGRESQL EXTERNO ({db_cfg.get('user')}@{db_cfg.get('host')}:{db_cfg.get('port')})")
    real_mark = "  ◀ ACTIVA" if dian_mode == "real" else ""
    test_mark = "  ◀ ACTIVA" if dian_mode != "real" else ""
    print(f" 🏢 BD Real           : {real_dbname(cfg)}{real_mark}")
    print(f" 🧪 BD de Pruebas     : {test_dbname(cfg)}{test_mark}")
    print(f" 📊 Estado BD Activa   : {demo_status_txt}")
    print(f" 🏛️  Entorno Global     : {dian_label}")
    print(f" 🌐 Servidor Web HTTP  : http://{srv_cfg.get('host', '127.0.0.1')}:{srv_cfg.get('http_port', 8000)}")
    print(f" 🐧 Motor Portable Linux   : PostgreSQL [{'✅ LISTO' if linux_pg_ok else '⚠️ PENDIENTE'}] | Python [{'✅ LISTO' if linux_py_ok else '⚠️ PENDIENTE'}]")
    print(f" 🪟 Motor Portable Windows : PostgreSQL [{'✅ LISTO' if win_pg_ok else '⚠️ PENDIENTE'}] | Python [{'✅ LISTO' if win_py_ok else '⚠️ PENDIENTE'}]")
    print("======================================================================")


def configure_embedded_db_interactive():
    cfg = load_config()
    port_in = input(f"Puerto local para PostgreSQL Portable [{cfg['database'].get('port', 54329)}]: ").strip()
    port = int(port_in) if port_in.isdigit() else int(cfg["database"].get("port", 54329))
    dbname = input(f"Nombre de la base de datos [{cfg['database'].get('dbname', 'sap_colombia')}]: ").strip() or cfg["database"].get("dbname", "sap_colombia")

    cfg["database"].update({
        "engine": "embedded_postgresql",
        "host": "127.0.0.1",
        "port": port,
        "user": "sap",
        "password": "",
        "dbname": dbname,
        "sslmode": "",
        "dsn": "",
    })
    save_config(cfg)
    print(f"\n✅ Configurado en MODO PORTABLE EMBEBIDO (Data/db en puerto {port}).")


def configure_external_db_interactive():
    cfg = load_config()
    db_cfg = cfg["database"]
    print("\n--- CONFIGURAR SERVIDOR POSTGRESQL EXTERNO ---")
    host = input(f"Host o IP del servidor PostgreSQL [{db_cfg.get('host', 'localhost')}]: ").strip() or db_cfg.get("host", "localhost")
    port_in = input("Puerto PostgreSQL [5432]: ").strip()
    port = int(port_in) if port_in.isdigit() else 5432
    user = input(f"Usuario de PostgreSQL [{db_cfg.get('user', 'postgres')}]: ").strip() or "postgres"
    password = getpass.getpass("Contraseña de PostgreSQL (vacío si no tiene): ")
    dbname = input(f"Nombre de la base de datos [{db_cfg.get('dbname', 'sap_colombia')}]: ").strip() or "sap_colombia"
    sslmode = input("Modo SSL (vacío, disable, prefer, require) []: ").strip()

    new_db_cfg = {
        "engine": "external_postgresql",
        "host": host,
        "port": port,
        "user": user,
        "password": password,
        "dbname": dbname,
        "sslmode": sslmode,
        "dsn": "",
    }

    print(f"\n🔌 Probando conexión a {user}@{host}:{port}/{dbname}...")
    try:
        ensure_database_exists(new_db_cfg)
        cfg["database"] = new_db_cfg
        save_config(cfg)
        print(f"✅ Conexión exitosa. Configuración guardada en Data/config.json para usar PostgreSQL Externo.")
    except Exception as e:
        print(f"⚠️ No se pudo conectar en este momento ({e}).")
        save_anyway = input("¿Deseas guardar esta configuración de todos modos? (s/n) [s]: ").strip().lower()
        if save_anyway in ("", "s", "si", "y", "yes"):
            cfg["database"] = new_db_cfg
            save_config(cfg)
            print("✅ Configuración guardada en Data/config.json.")


def configure_dian_mode_interactive():
    cfg = load_config()
    dian_cfg = cfg.setdefault("dian", {})
    print("\n======================================================================")
    print(" 🏛️  SEPARACIÓN GLOBAL DE ENTORNO: PRUEBAS vs. TRABAJO REAL DIAN")
    print("======================================================================")
    print("  1) 🧪 ENTORNO DE PRUEBAS (Simulador Mockup Local)")
    print("     Todo el sistema opera en modo de pruebas locales sin transmitir")
    print("     documentos a internet.")
    print("  2) 🚀 ENTORNO DE TRABAJO REAL (Servidor Oficial DIAN)")
    print("     Todo el sistema se conecta directamente con los Web Services SOAP")
    print("     de la DIAN (Producción Oficial o Set de Habilitación).")
    choice = input("\n👉 Selecciona el entorno global del sistema [1]: ").strip() or "1"

    if choice == "2":
        dian_cfg["mode"] = "real"
        amb_in = input("Ambiente DIAN (1 = Habilitación Set de Pruebas, 2 = Producción Oficial) [2]: ").strip() or "2"
        is_prod = amb_in == "2"
        dian_cfg["ambiente"] = "2" if is_prod else "1"
        default_url = (
            "https://vpfe.dian.gov.co/WcfDianCustomerServices.svc"
            if is_prod
            else "https://vpfe-hab.dian.gov.co/WcfDianCustomerServices.svc"
        )
        url_in = input(f"URL Web Service DIAN [{default_url}]: ").strip() or default_url
        dian_cfg["transmit_url"] = url_in
        if not is_prod:
            ts_in = input(f"TestSetId de Habilitación DIAN [{dian_cfg.get('test_set_id', '')}]: ").strip()
            if ts_in:
                dian_cfg["test_set_id"] = ts_in
        usr_in = input(f"Usuario WS DIAN / NIT Software [{dian_cfg.get('user', '')}]: ").strip()
        if usr_in:
            dian_cfg["user"] = usr_in
        pwd_in = getpass.getpass("Clave Técnica / Password Software WS DIAN (Enter para mantener actual): ").strip()
        if pwd_in:
            dian_cfg["password"] = pwd_in
        save_config(cfg)
        print(f"✅ Sistema configurado globalmente en: 🚀 TRABAJO REAL DIAN ({'Producción' if is_prod else 'Habilitación'}).")
    else:
        dian_cfg["mode"] = "mock"
        dian_cfg["transmit_url"] = ""
        save_config(cfg)
        print("✅ Sistema configurado globalmente en: 🧪 ENTORNO DE PRUEBAS (Simulador Mockup Local).")
        print(f"   Base de datos activa: '{test_dbname(cfg)}' (aislada de la BD real '{real_dbname(cfg)}')")
        preg = input("\n¿Deseas clonar ahora todos los datos de la BD REAL hacia la BD de PRUEBAS? (s/n) [s]: ").strip().lower()
        if preg in ("", "s", "si", "y", "yes"):
            with_db_server(clone_real_to_test, assume_yes=True)


def interactive_menu():
    while True:
        print_status_banner()
        print("  1) 🚀 Iniciar el ERP Corporativo Ahora")
        print("  2) 🏠 Cambiar a Base de Datos PORTABLE Embebida (guardada en Data/)")
        print("  3) 🌐 Cambiar a Servidor PostgreSQL EXTERNO (Red Local / Nube / Docker)")
        print("  4) 🏛️  Cambiar Entorno Global (🧪 Pruebas Mockup vs. 🚀 Trabajo Real DIAN)")
        print("  5) 🔁 Migrar / Clonar BD REAL  ➜  BD de PRUEBAS (Sandbox Seguro)")
        print("  6) 🧹 Reiniciar BD de PRUEBAS (Vaciar base de datos de pruebas)")
        print("  7) 🌱 Poblar Base de Datos Activa con Datos Demo (Demostración)")
        print("  8) 🗑️  Limpiar Datos Demo de la Base de Datos Activa (Dejar BD Limpia para Producción)")
        print("  9) 📦 Portabilizar / Descargar Motores (Linux + Windows para USB)")
        print("  10) 💾 Exportar Respaldo Universal de Datos (Data/backups/respaldo_universal.json)")
        print("  11) 📥 Importar / Restaurar Respaldo Universal en la Base de Datos Activa")
        print("  12) 🔧 Cambiar Puerto Web HTTP / Acceso desde Red Local (LAN)")
        print("  0) Salir")
        choice = input("\n👉 Selecciona una opción [1]: ").strip() or "1"

        if choice == "1":
            start_erp_system()
            break
        elif choice == "2":
            configure_embedded_db_interactive()
        elif choice == "3":
            configure_external_db_interactive()
        elif choice == "4":
            configure_dian_mode_interactive()
        elif choice == "5":
            with_db_server(clone_real_to_test, assume_yes=False)
        elif choice == "6":
            with_db_server(reset_test_db, assume_yes=False)
        elif choice == "7":
            with_db_server(poblar_demo_wrapper, assume_yes=False)
        elif choice == "8":
            with_db_server(limpiar_demo_wrapper, assume_yes=False)
        elif choice == "9":
            print("\n  a) Portabilizar AMBOS (Linux + Windows — ideal para memoria USB híbrida)")
            print("  b) Portabilizar solo Linux (PostgreSQL 17.2 + Python 3.12)")
            print("  c) Portabilizar solo Windows (PostgreSQL 17.2 + Python 3.12)")
            sub = input("  Elige opción [a]: ").strip().lower() or "a"
            if sub == "b":
                setup_linux_postgres()
                setup_linux_python()
            elif sub == "c":
                setup_windows_postgres()
                setup_windows_python()
            else:
                setup_linux_postgres()
                setup_linux_python()
                setup_windows_postgres()
                setup_windows_python()
        elif choice == "10":
            export_universal_backup()
        elif choice == "11":
            import_universal_backup()
        elif choice == "12":
            cfg = load_config()
            p_in = input(f"Puerto Web HTTP [{cfg['server'].get('http_port', 8000)}]: ").strip()
            if p_in.isdigit():
                cfg["server"]["http_port"] = int(p_in)
            lan = input("¿Permitir acceso desde otros equipos de la red local LAN? (s/n) [s]: ").strip().lower()
            cfg["server"]["host"] = "0.0.0.0" if lan in ("", "s", "si", "y", "yes") else "127.0.0.1"
            save_config(cfg)
            print("✅ Configuración de red guardada en Data/config.json.")
        elif choice == "0":
            break


def main():
    parser = argparse.ArgumentParser(description="Gestor Unificado de Portabilidad, Base de Datos y Entorno ERP Colombia")
    parser.add_argument("--menu", action="store_true", help="Abrir menú interactivo de configuración y arranque")
    parser.add_argument("--start", action="store_true", help="Iniciar el ERP directamente con la configuración actual")
    parser.add_argument("--target", choices=["linux", "windows", "all", "auto"], help="Portabilizar motores (linux, windows, all)")
    parser.add_argument("--force", action="store_true", help="Forzar re-descarga de motores")
    parser.add_argument("--ensure-db", action="store_true", help="Asegurar que la base de datos activa exista")
    parser.add_argument("--clone-to-test", action="store_true", help="Clonar BD real sobre la BD de pruebas")
    parser.add_argument("--reset-test-db", action="store_true", help="Reiniciar (vaciar) la BD de pruebas")
    parser.add_argument("--seed-demo", action="store_true", help="Poblar la base de datos activa con datos de demostración")
    parser.add_argument("--clean-demo", action="store_true", help="Limpiar datos de demostración de la base de datos activa")
    parser.add_argument("--status-demo", action="store_true", help="Consultar estado de datos demo en la base de datos activa")
    parser.add_argument("--yes", "-y", action="store_true", help="Confirmar automáticamente sin preguntar")
    parser.add_argument("--set-db", choices=["embedded", "external"], help="Configurar modo de base de datos por CLI")
    parser.add_argument("--host", help="Host de PostgreSQL externo")
    parser.add_argument("--port", type=int, help="Puerto de PostgreSQL")
    parser.add_argument("--user", help="Usuario de PostgreSQL")
    parser.add_argument("--password", help="Contraseña de PostgreSQL")
    parser.add_argument("--dbname", help="Nombre de la base de datos real")
    parser.add_argument("--test-dbname", help="Nombre personalizado de la base de datos de pruebas")
    parser.add_argument("--sslmode", default="", help="Modo SSL para PostgreSQL externo")
    parser.add_argument("--set-dian", choices=["mock", "real"], help="Configurar entorno global: mock (pruebas locales) o real (servidor DIAN)")
    parser.add_argument("--dian-ambiente", choices=["1", "2"], help="Ambiente DIAN en modo real: 1 (Habilitación) o 2 (Producción)")
    parser.add_argument("--dian-test-set-id", help="TestSetId para el set de pruebas de habilitación DIAN")
    parser.add_argument("--dian-user", help="Usuario WS DIAN")
    parser.add_argument("--dian-password", help="Contraseña WS DIAN")
    parser.add_argument("--dian-url", help="URL de transmisión SOAP DIAN")
    parser.add_argument("--export-backup", action="store_true", help="Exportar respaldo universal en Data/backups/")
    parser.add_argument("--import-backup", action="store_true", help="Importar respaldo universal desde Data/backups/")
    args = parser.parse_args()

    if args.seed_demo:
        with_db_server(poblar_demo_wrapper, assume_yes=args.yes)
        return

    if args.clean_demo:
        with_db_server(limpiar_demo_wrapper, assume_yes=args.yes)
        return

    if args.status_demo:
        with_db_server(estado_demo_wrapper)
        return

    if args.clone_to_test:
        with_db_server(clone_real_to_test, assume_yes=args.yes)
        return

    if args.reset_test_db:
        with_db_server(reset_test_db, assume_yes=args.yes)
        return

    if args.set_dian:
        cfg = load_config()
        dian_cfg = cfg.setdefault("dian", {})
        if args.set_dian == "mock":
            dian_cfg["mode"] = "mock"
            dian_cfg["transmit_url"] = ""
        else:
            dian_cfg["mode"] = "real"
            amb = args.dian_ambiente or dian_cfg.get("ambiente") or "2"
            dian_cfg["ambiente"] = amb
            dian_cfg["transmit_url"] = args.dian_url or (
                "https://vpfe.dian.gov.co/WcfDianCustomerServices.svc"
                if amb == "2"
                else "https://vpfe-hab.dian.gov.co/WcfDianCustomerServices.svc"
            )
        if args.dian_test_set_id is not None:
            dian_cfg["test_set_id"] = args.dian_test_set_id
        if args.dian_user is not None:
            dian_cfg["user"] = args.dian_user
        if args.dian_password is not None:
            dian_cfg["password"] = args.dian_password
        save_config(cfg)
        act_db = test_dbname(cfg) if dian_cfg["mode"] == "mock" else real_dbname(cfg)
        print(f"✅ Entorno global actualizado en Data/config.json -> mode='{dian_cfg['mode']}', BD activa='{act_db}'")
        return

    if args.set_db:
        cfg = load_config()
        upd = {
            "engine": "embedded_postgresql" if args.set_db == "embedded" else "external_postgresql",
            "host": args.host or ("127.0.0.1" if args.set_db == "embedded" else "localhost"),
            "port": args.port or (54329 if args.set_db == "embedded" else 5432),
            "user": args.user or ("sap" if args.set_db == "embedded" else "postgres"),
            "password": args.password or "",
            "dbname": args.dbname or "sap_colombia",
            "sslmode": args.sslmode or "",
            "dsn": "",
        }
        if args.test_dbname is not None:
            upd["test_dbname"] = args.test_dbname
        cfg["database"].update(upd)
        save_config(cfg)
        print(f"✅ Base de datos configurada en modo {args.set_db.upper()} (puerto {cfg['database']['port']}, real='{cfg['database']['dbname']}', pruebas='{test_dbname(cfg)}').")
        return

    if args.ensure_db:
        ensure_database_exists()
        return

    if args.export_backup:
        export_universal_backup()
        return

    if args.import_backup:
        import_universal_backup()
        return

    if args.target:
        target = args.target
        if target == "auto":
            target = "windows" if is_windows_os() else "linux"
        if target in ("linux", "all"):
            setup_linux_postgres(force=args.force)
            setup_linux_python(force=args.force)
        if target in ("windows", "all"):
            setup_windows_postgres(force=args.force)
            setup_windows_python(force=args.force)
        return

    if args.start:
        start_erp_system()
        return

    # Si se invoca con --menu o sin argumentos, abrir menú interactivo
    interactive_menu()


if __name__ == "__main__":
    main()
