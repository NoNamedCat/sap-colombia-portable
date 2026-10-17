#!/usr/bin/env python3
"""
Script de Portabilización Automática (Linux y Windows) para ERP Corporativo Colombia.
Descarga y empaqueta dentro de App/engine/ y App/runtime/:
  1. PostgreSQL 17.2 Portable (Linux x86_64 y/o Windows x86_64)
  2. Python 3.12 Portable + todas las librerías requeridas (Linux x86_64 y/o Windows x86_64)

Uso:
  python3 App/scripts/portabilizar_entorno.py --target all
  python3 App/scripts/portabilizar_entorno.py --target linux
  python3 App/scripts/portabilizar_entorno.py --target windows
"""

import argparse
import io
import os
import platform
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
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

    print("📦 Instalando librerías requeridas dentro de App/runtime/linux...")
    subprocess.run(
        [py_bin, "-m", "pip", "install", "--quiet", "--upgrade", "-r", REQ_FILE],
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

        # Configurar python312._pth para habilitar site-packages y App/src
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


def ensure_database_exists(host: str, port: int, user: str, dbname: str):
    """Crea la base de datos en PostgreSQL usando psycopg2 sin depender de createdb/psql."""
    import psycopg2
    from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

    conn = psycopg2.connect(host=host, port=port, user=user, dbname="postgres")
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (dbname,))
    exists = cur.fetchone() is not None
    if not exists:
        print(f"🗄️  Creando base de datos '{dbname}' en puerto {port}...")
        cur.execute(f'CREATE DATABASE "{dbname}" ENCODING \'UTF8\'')
    cur.close()
    conn.close()


def main():
    parser = argparse.ArgumentParser(description="Portabilizador automático de PostgreSQL + Python")
    parser.add_argument(
        "--target",
        choices=["linux", "windows", "all", "auto"],
        default="auto",
        help="Sistema operativo a portabilizar (linux, windows, all, auto)",
    )
    parser.add_argument("--force", action="store_true", help="Re-descargar aunque ya exista")
    parser.add_argument("--ensure-db", action="store_true", help="Asegurar que la BD sap_colombia exista")
    args = parser.parse_args()

    if args.ensure_db:
        port = int(os.environ.get("SAP_DB_PORT", "54329"))
        user = os.environ.get("SAP_DB_USER", "sap")
        dbname = os.environ.get("SAP_DB_NAME", "sap_colombia")
        ensure_database_exists("127.0.0.1", port, user, dbname)
        return

    target = args.target
    if target == "auto":
        target = "windows" if platform.system().lower().startswith("win") else "linux"

    print("==================================================================")
    print(f" 📦 PORTABILIZADOR AUTOMÁTICO ERP COLOMBIA (Objetivo: {target.upper()})")
    print("==================================================================")

    if target in ("linux", "all"):
        setup_linux_postgres(force=args.force)
        setup_linux_python(force=args.force)

    if target in ("windows", "all"):
        setup_windows_postgres(force=args.force)
        setup_windows_python(force=args.force)

    print("==================================================================")
    print(" 🎉 ¡Portabilización completada exitosamente!")
    print("==================================================================")


if __name__ == "__main__":
    main()
