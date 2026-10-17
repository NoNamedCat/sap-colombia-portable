#!/usr/bin/env python3
"""
================================================================================
 GESTOR UNIFICADO DE PORTABILIDAD, BASE DE DATOS, DIAN Y ARRANQUE - ERP COLOMBIA
================================================================================
Unifica en una sola herramienta multiplataforma (Linux y Windows):
  1. Descarga y portabilización automática de PostgreSQL 17.2 y Python 3.12 + librerías
     dentro de App/engine/ y App/runtime/.
  2. Gestión de Base de Datos:
     - Modo A: Base de Datos Portable Embebida (guardada en Data/db o Data/db_windows).
     - Modo B: PostgreSQL Externo (Servidor en red local, Docker, AWS RDS, Supabase, etc.).
  3. Gestión Híbrida de Facturación Electrónica DIAN:
     - Automático por Empresa (cada empresa elige Mockup, Habilitación o Producción en la Web UI).
     - Forzar Simulador Mockup Local globalmente (ideal para pruebas/capacitación sin riesgo).
     - Forzar Servidor DIAN Real globalmente (Habilitación o Producción).
  4. Exportación e Importación de Respaldo Universal (Data/backups/respaldo_universal.json)
     para migrar datos entre Linux, Windows o un servidor PostgreSQL externo.
  5. Lanzador unificado del ERP (arranca motor si es embebido, verifica BD y lanza Web UI).

Uso por línea de comandos:
  python3 App/scripts/portabilizar_entorno.py --menu
  python3 App/scripts/portabilizar_entorno.py --start
  python3 App/scripts/portabilizar_entorno.py --target all
  python3 App/scripts/portabilizar_entorno.py --set-db embedded --port 54329
  python3 App/scripts/portabilizar_entorno.py --set-db external --host 192.168.1.50 --port 5432 --user postgres --password secret --dbname sap_colombia
  python3 App/scripts/portabilizar_entorno.py --set-dian auto
  python3 App/scripts/portabilizar_entorno.py --set-dian mock
  python3 App/scripts/portabilizar_entorno.py --set-dian real --dian-ambiente 2 --dian-test-set-id "tu-test-set-id"
  python3 App/scripts/portabilizar_entorno.py --export-backup
  python3 App/scripts/portabilizar_entorno.py --import-backup
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
            "sslmode": "",
            "dsn": "",
        },
        "dian": {
            "mode": "auto",
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
        db_cfg = load_config()["database"]

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


def export_universal_backup(custom_path: str | None = None) -> str:
    """Exporta todas las tablas de la base de datos activa a un archivo JSON portable universal."""
    import psycopg2
    import psycopg2.extras

    os.makedirs(BACKUPS_DIR, exist_ok=True)
    cfg = load_config()
    dsn = build_dsn_from_cfg(cfg["database"])
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
    ensure_database_exists(cfg["database"])
    dsn = build_dsn_from_cfg(cfg["database"])

    # Asegurar que el esquema esté creado antes de importar
    sys.path.insert(0, os.path.join(APP_DIR, "src"))
    os.environ["SAP_PG_DSN"] = dsn
    from sap_colombia import database as sap_db
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
def start_erp_system():
    cfg = load_config()
    srv_cfg = cfg["server"]
    db_cfg = cfg["database"]
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

    started_embedded_pg = False
    pg_ctl_bin = None
    db_dir = None

    if engine_mode == "embedded_postgresql":
        db_cfg["host"] = "127.0.0.1"
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

        # 1. Inicializar cluster en Data/ si no existe
        pg_version_file = os.path.join(db_dir, "PG_VERSION")
        if not os.path.isfile(pg_version_file):
            print(f"📦 Inicializando cluster de Base de Datos Portable en: {db_dir}...")
            init_cmd = [initdb_bin, "-D", db_dir, "-U", db_user, "--auth=trust", "-E", "UTF8"]
            if win:
                init_cmd.append("--no-locale")
            with open(os.path.join(LOGS_DIR, "initdb.log"), "w") as logf:
                subprocess.run(init_cmd, stdout=logf, stderr= subprocess.STDOUT, check=True)
            print("✅ Cluster portable inicializado.")

        # 2. Iniciar PostgreSQL embebido si no está corriendo
        status_res = subprocess.run([pg_ctl_bin, "-D", db_dir, "status"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if status_res.returncode != 0:
            print(f"⚡ Arrancando motor PostgreSQL Portable en puerto {db_port}...")
            pg_log = os.path.join(LOGS_DIR, "postgres.log")
            pg_opts = f"-p {db_port} -h 127.0.0.1" if win else f"-p {db_port} -k {db_dir}"
            subprocess.run([pg_ctl_bin, "-D", db_dir, "-l", pg_log, "-o", pg_opts, "-w", "start"], check=True)
            started_embedded_pg = True
            print("✅ Motor PostgreSQL Portable activo.")
        else:
            print("ℹ️  Motor PostgreSQL Portable ya se encontraba en ejecución.")
    else:
        print(f"🌐 Modo PostgreSQL EXTERNO activo -> {db_cfg.get('host')}:{db_cfg.get('port')}/{db_cfg.get('dbname')}")

    # 3. Asegurar que la base de datos exista (embebida o externa)
    ensure_database_exists(db_cfg)
    dsn = build_dsn_from_cfg(db_cfg)
    dian_cfg = cfg.get("dian", {})
    dian_mode_val = dian_cfg.get("mode", "auto")
    if dian_mode_val == "mock":
        dian_desc = "🧪 FORZADO SIMULADOR MOCKUP LOCAL (Pruebas seguras)"
    elif dian_mode_val == "real":
        amb_label = "Producción" if str(dian_cfg.get("ambiente")) == "1" else "Habilitación"
        dian_desc = f"🏛️  FORZADO SERVIDOR DIAN REAL ({amb_label})"
    else:
        dian_desc = "🔄 AUTOMÁTICO POR EMPRESA (Según perfil de cada empresa en Web UI)"

    print("==================================================================")
    print(" 🚀 ERP CORPORATIVO COLOMBIA - SISTEMA EN EJECUCIÓN")
    print("==================================================================")
    print(f"📂 Directorio Base : {BASE_DIR}")
    if engine_mode == "embedded_postgresql":
        print(f"🗄️  Base de Datos   : PORTABLE EMBEBIDA ({db_dir} - Puerto {db_cfg.get('port')})")
    else:
        print(f"🗄️  Base de Datos   : POSTGRESQL EXTERNO ({db_cfg.get('host')}:{db_cfg.get('port')}/{db_cfg.get('dbname')})")
    print(f"🏛️  Servidor DIAN   : {dian_desc}")
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


# ==============================================================================
# 4. MENÚ INTERACTIVO UNIFICADO DE CONFIGURACIÓN Y PORTABILIZACIÓN
# ==============================================================================
def print_status_banner():
    cfg = load_config()
    db_cfg = cfg["database"]
    srv_cfg = cfg["server"]
    dian_cfg = cfg.get("dian", {})
    engine = db_cfg.get("engine", "embedded_postgresql")
    dian_mode = dian_cfg.get("mode", "auto")
    if dian_mode == "mock":
        dian_label = "🧪 FORZADO SIMULADOR MOCKUP LOCAL (Pruebas seguras)"
    elif dian_mode == "real":
        amb_txt = "Producción (1)" if str(dian_cfg.get("ambiente")) == "1" else "Habilitación (2)"
        dian_label = f"🏛️  FORZADO SERVIDOR DIAN REAL — {amb_txt}"
    else:
        dian_label = "🔄 AUTOMÁTICO POR EMPRESA (Según perfil en Web UI)"

    linux_pg_ok = os.path.isfile(os.path.join(APP_DIR, "engine", "linux", "bin", "postgres"))
    linux_py_ok = os.path.isfile(os.path.join(APP_DIR, "runtime", "linux", "bin", "python3"))
    win_pg_ok = os.path.isfile(os.path.join(APP_DIR, "engine", "windows", "bin", "postgres.exe"))
    win_py_ok = os.path.isfile(os.path.join(APP_DIR, "runtime", "windows", "python.exe"))

    print("\n======================================================================")
    print(" 🎛️  PANEL DE CONTROL Y PORTABILIDAD — ERP CORPORATIVO COLOMBIA")
    print("======================================================================")
    if engine == "embedded_postgresql":
        print(f" 🗄️  Modo Base de Datos : PORTABLE EMBEBIDA en Data/ (Puerto {db_cfg.get('port', 54329)})")
    else:
        print(f" 🗄️  Modo Base de Datos : POSTGRESQL EXTERNO ({db_cfg.get('user')}@{db_cfg.get('host')}:{db_cfg.get('port')}/{db_cfg.get('dbname')})")
    print(f" 🏛️  Facturación DIAN   : {dian_label}")
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
    print(" 🏛️  CONFIGURACIÓN HÍBRIDA DE FACTURACIÓN ELECTRÓNICA DIAN")
    print("======================================================================")
    print("  1) 🔄 AUTOMÁTICO POR EMPRESA (Recomendado)")
    print("     Cada empresa registrada usa su propia configuración en la UI Web:")
    print("     - Empresa A puede estar en Producción DIAN Real")
    print("     - Empresa B puede estar en Simulador Mockup Local o Habilitación")
    print("  2) 🧪 FORZAR SIMULADOR MOCKUP LOCAL GLOBALMENTE")
    print("     Todas las empresas emiten facturas simuladas localmente con CUFE/XML")
    print("     válidos sin transmitir nada a internet (ideal para pruebas/demos).")
    print("  3) 🏛️  FORZAR SERVIDOR DIAN HABILITACIÓN (Pruebas Set de Pruebas DIAN)")
    print("     Conecta con https://vpfe-hab.dian.gov.co/WcfDianCustomerServices.svc")
    print("  4) 🚀 FORZAR SERVIDOR DIAN PRODUCCIÓN REAL")
    print("     Conecta con https://vpfe.dian.gov.co/WcfDianCustomerServices.svc")
    choice = input("\n👉 Selecciona el modo de operación DIAN [1]: ").strip() or "1"

    if choice == "2":
        dian_cfg["mode"] = "mock"
        save_config(cfg)
        print("✅ Modo DIAN configurado en: 🧪 FORZADO SIMULADOR MOCKUP LOCAL.")
    elif choice in ("3", "4"):
        is_prod = choice == "4"
        dian_cfg["mode"] = "real"
        dian_cfg["ambiente"] = "1" if is_prod else "2"
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
        usr_in = input(f"Usuario WS DIAN / NIT Software (opcional) [{dian_cfg.get('user', '')}]: ").strip()
        if usr_in:
            dian_cfg["user"] = usr_in
        pwd_in = getpass.getpass("Clave Técnica / Password Software WS DIAN (Enter para mantener actual): ").strip()
        if pwd_in:
            dian_cfg["password"] = pwd_in
        save_config(cfg)
        print(f"✅ Modo DIAN configurado en: {'🚀 PRODUCCIÓN REAL' if is_prod else '🏛️ HABILITACIÓN DIAN'}.")
    else:
        dian_cfg["mode"] = "auto"
        save_config(cfg)
        print("✅ Modo DIAN configurado en: 🔄 AUTOMÁTICO POR EMPRESA (se respeta el selector de cada empresa en la Web UI).")


def interactive_menu():
    while True:
        print_status_banner()
        print("  1) 🚀 Iniciar el ERP Corporativo Ahora")
        print("  2) 🏠 Cambiar a Base de Datos PORTABLE Embebida (guardada en Data/)")
        print("  3) 🌐 Cambiar a Servidor PostgreSQL EXTERNO (Red Local / Nube / Docker)")
        print("  4) 🏛️  Configurar Modo Servidor DIAN (Mockup Local vs. DIAN Real vs. Por Empresa)")
        print("  5) 📦 Portabilizar / Descargar Motores (Linux + Windows para USB)")
        print("  6) 💾 Exportar Respaldo Universal de Datos (Data/backups/respaldo_universal.json)")
        print("  7) 📥 Importar / Restaurar Respaldo Universal en la Base de Datos Activa")
        print("  8) 🔧 Cambiar Puerto Web HTTP / Acceso desde Red Local (LAN)")
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
        elif choice == "6":
            export_universal_backup()
        elif choice == "7":
            import_universal_backup()
        elif choice == "8":
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
    parser = argparse.ArgumentParser(description="Gestor Unificado de Portabilidad, Base de Datos y DIAN ERP Colombia")
    parser.add_argument("--menu", action="store_true", help="Abrir menú interactivo de configuración y arranque")
    parser.add_argument("--start", action="store_true", help="Iniciar el ERP directamente con la configuración actual")
    parser.add_argument("--target", choices=["linux", "windows", "all", "auto"], help="Portabilizar motores (linux, windows, all)")
    parser.add_argument("--force", action="store_true", help="Forzar re-descarga de motores")
    parser.add_argument("--ensure-db", action="store_true", help="Asegurar que la base de datos activa exista")
    parser.add_argument("--set-db", choices=["embedded", "external"], help="Configurar modo de base de datos por CLI")
    parser.add_argument("--host", help="Host de PostgreSQL externo")
    parser.add_argument("--port", type=int, help="Puerto de PostgreSQL")
    parser.add_argument("--user", help="Usuario de PostgreSQL")
    parser.add_argument("--password", help="Contraseña de PostgreSQL")
    parser.add_argument("--dbname", help="Nombre de la base de datos")
    parser.add_argument("--sslmode", default="", help="Modo SSL para PostgreSQL externo")
    parser.add_argument("--set-dian", choices=["auto", "mock", "real", "dian_hab", "dian_prod"], help="Configurar modo de servidor DIAN (auto, mock, real, dian_hab, dian_prod)")
    parser.add_argument("--dian-ambiente", choices=["1", "2"], help="Ambiente DIAN: 1 (Producción) o 2 (Habilitación)")
    parser.add_argument("--dian-test-set-id", help="TestSetId para el set de pruebas de habilitación DIAN")
    parser.add_argument("--dian-user", help="Usuario WS DIAN")
    parser.add_argument("--dian-password", help="Contraseña WS DIAN")
    parser.add_argument("--dian-url", help="URL de transmisión SOAP DIAN")
    parser.add_argument("--export-backup", action="store_true", help="Exportar respaldo universal en Data/backups/")
    parser.add_argument("--import-backup", action="store_true", help="Importar respaldo universal desde Data/backups/")
    args = parser.parse_args()

    if args.set_dian:
        cfg = load_config()
        dian_cfg = cfg.setdefault("dian", {})
        if args.set_dian == "mock":
            dian_cfg["mode"] = "mock"
        elif args.set_dian == "auto":
            dian_cfg["mode"] = "auto"
        elif args.set_dian == "dian_hab":
            dian_cfg["mode"] = "real"
            dian_cfg["ambiente"] = "2"
            dian_cfg["transmit_url"] = args.dian_url or "https://vpfe-hab.dian.gov.co/WcfDianCustomerServices.svc"
        elif args.set_dian == "dian_prod":
            dian_cfg["mode"] = "real"
            dian_cfg["ambiente"] = "1"
            dian_cfg["transmit_url"] = args.dian_url or "https://vpfe.dian.gov.co/WcfDianCustomerServices.svc"
        else:
            dian_cfg["mode"] = "real"
            if args.dian_ambiente:
                dian_cfg["ambiente"] = args.dian_ambiente
            if args.dian_url:
                dian_cfg["transmit_url"] = args.dian_url
        if args.dian_test_set_id is not None:
            dian_cfg["test_set_id"] = args.dian_test_set_id
        if args.dian_user is not None:
            dian_cfg["user"] = args.dian_user
        if args.dian_password is not None:
            dian_cfg["password"] = args.dian_password
        save_config(cfg)
        print(f"✅ Modo DIAN actualizado en Data/config.json -> mode='{dian_cfg['mode']}'")
        return

    if args.set_db:
        cfg = load_config()
        if args.set_db == "embedded":
            cfg["database"].update({
                "engine": "embedded_postgresql",
                "host": "127.0.0.1",
                "port": args.port or 54329,
                "user": args.user or "sap",
                "password": "",
                "dbname": args.dbname or "sap_colombia",
                "sslmode": "",
                "dsn": "",
            })
            save_config(cfg)
            print(f"✅ Base de datos configurada en modo PORTABLE EMBEBIDA (puerto {cfg['database']['port']}).")
        else:
            cfg["database"].update({
                "engine": "external_postgresql",
                "host": args.host or "localhost",
                "port": args.port or 5432,
                "user": args.user or "postgres",
                "password": args.password or "",
                "dbname": args.dbname or "sap_colombia",
                "sslmode": args.sslmode or "",
                "dsn": "",
            })
            save_config(cfg)
            print(f"✅ Base de datos configurada en modo POSTGRESQL EXTERNO ({cfg['database']['host']}:{cfg['database']['port']}/{cfg['database']['dbname']}).")
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
