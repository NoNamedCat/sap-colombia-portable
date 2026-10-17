"""Pruebas TDD para remediación de seguridad local: hashing, JWT, RBAC, auditoría."""

import json
from sap_colombia import dbutil
import threading
import time
import os
from datetime import datetime, timedelta, timezone
from urllib.request import urlopen, Request
from urllib.error import HTTPError

import jwt as pyjwt
import pytest
from http.server import HTTPServer

import sap_colombia.database as db
from sap_colombia import auth
from sap_colombia import rbac
from sap_colombia import audit
from sap_colombia import web_server as srv
from sap_colombia.web_server import SapWebHandler

TEST_PORT = 8092


@pytest.fixture(scope="module")
def web_server():
    db.init_db()
    auth.seed_usuarios()
    rbac.ensure_rbac()
    server = HTTPServer(("127.0.0.1", TEST_PORT), SapWebHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.5)
    yield f"http://127.0.0.1:{TEST_PORT}"
    server.shutdown()
    server.server_close()


@pytest.fixture(autouse=True)
def _clean():
    db.init_db()
    auth.seed_usuarios()
    rbac.ensure_rbac()
    yield
    conn = db.get_connection()
    dbutil.query(conn, "UPDATE usuarios SET password_changed_at = NULL")
    # Restaurar contraseña admin tras cada test
    h, salt = auth.hash_password("admin123")
    dbutil.query(conn, 
        "UPDATE usuarios SET hash_password = ?, salt = ? WHERE email = 'admin@saluki.com'",
        (h, salt),
    )
    conn.commit()
    conn.close()


def _req(url, method="GET", data=None, headers=None):
    body = json.dumps(data).encode("utf-8") if data is not None else None
    req = Request(url, data=body,
                  headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urlopen(req) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, (json.loads(raw) if raw else None)
    except HTTPError as e:
        raw = e.read().decode("utf-8")
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"raw": raw}


def _get(url, headers=None):
    return _req(url, "GET", headers=headers)


def _post(url, data, headers=None):
    return _req(url, "POST", data, headers)


def _put(url, data, headers=None):
    return _req(url, "PUT", data, headers)


def _delete(url, data=None, headers=None):
    return _req(url, "DELETE", data, headers)


def _login(base, email, password):
    status, data = _post(f"{base}/api/auth/login", {"email": email, "password": password})
    assert status == 200, f"Login falló: {data}"
    return data["token"]


# ============================================================
# TASK 1: Hashing PBKDF2, expiración, invalidación de tokens
# ============================================================

def test_hash_password_pbkdf2_formato():
    h, salt = auth.hash_password("admin123")
    assert salt and len(salt) == 16
    assert h.startswith("pbkdf2_sha256")
    assert ":" in h
    parts = h.split(":")
    assert len(parts) == 4
    iteraciones = int(parts[1])
    assert iteraciones >= 100000


def test_verificar_credenciales_pbkdf2():
    user = auth.verificar_credenciales("admin@saluki.com", "admin123")
    assert user is not None
    assert user["rol"] in ("ADMIN", "SUPERADMIN")


def test_verificar_credenciales_pbkdf2_invalido():
    assert auth.verificar_credenciales("admin@saluki.com", "password_incorrecta") is None


def test_token_expiracion_60_min():
    user = auth.verificar_credenciales("admin@saluki.com", "admin123")
    token = auth.generar_token(user)
    payload = auth.validar_token(token)
    assert payload["exp"] - payload["iat"] == 3600


def test_secret_dinamico_desde_bd():
    assert auth.SECRET_KEY
    assert auth.SECRET_KEY != "saluki_sap_colombia_secret_key_v1"


def test_password_changed_at_invalida_tokens_antiguos():
    user = auth.verificar_credenciales("admin@saluki.com", "admin123")
    token_antiguo = auth.generar_token(user)
    conn = db.get_connection()
    # Convention del sistema: password_changed_at siempre en UTC.
    pcd = (datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat(sep=" ", timespec="seconds")
    dbutil.query(conn, "UPDATE usuarios SET password_changed_at = ? WHERE email = 'admin@saluki.com'", (pcd,))
    conn.commit()
    conn.close()
    with pytest.raises(Exception):
        auth.validar_token(token_antiguo)


# ============================================================
# TASK 2: Catálogo de permisos
# ============================================================

def test_catalogo_permisos_cubre_recursos():
    recursos = {"usuarios", "roles", "permisos", "auditoria", "periodos"}
    recursos_catalogo = {p.split(":")[0] for p in rbac.permisos_catalogo()}
    assert recursos <= recursos_catalogo


def test_permisos_por_recurso():
    perm = rbac.permisos_por_recurso("usuarios")
    assert {"usuarios:create", "usuarios:read", "usuarios:update", "usuarios:delete"} <= set(perm)


# ============================================================
# TASK 3: RBAC dinámico — API de roles y permisos
# ============================================================

def test_api_listar_roles(web_server):
    token = _login(web_server, "admin@saluki.com", "admin123")
    status, data = _get(f"{web_server}/api/roles", headers={"Authorization": f"Bearer {token}"})
    assert status == 200
    roles = [r["nombre"] for r in data]
    for esperado in ("ADMIN", "VENDEDOR", "ALMACENISTA", "CONTADOR"):
        assert esperado in roles


def test_api_reabrir_periodo_vendedor_no_autorizado(web_server):
    conn = db.get_connection()
    h, salt = auth.hash_password("vendedor123")
    now = datetime.now().isoformat()
    dbutil.query(conn, 
        "INSERT INTO usuarios (email, nombre, rol, hash_password, salt, activo, created_at) "
        "VALUES ('vendedor@saluki.com', 'Carlos Vendedor', 'VENDEDOR', ?, ?, 1, ?) "
        "ON CONFLICT (email) DO UPDATE SET hash_password = EXCLUDED.hash_password, salt = EXCLUDED.salt",
        (h, salt, now),
    )
    conn.commit()
    conn.close()
    token = _login(web_server, "vendedor@saluki.com", "vendedor123")
    status, data = _post(f"{web_server}/api/periodos/reabrir",
                         {"periodo": "2030-01", "justificacion": "Intento vendedor"},
                         headers={"Authorization": f"Bearer {token}"})
    assert status == 403


def test_api_permisos_por_recurso_requiere_usuario(web_server):
    token = _login(web_server, "admin@saluki.com", "admin123")
    status, data = _get(f"{web_server}/api/permisos/recurso/facturacion",
                        headers={"Authorization": f"Bearer {token}"})
    assert status == 200
    assert "read" in data


# ============================================================
# TASK 4: API de usuarios + auditoría
# ============================================================

def test_api_crear_usuario(web_server):
    import uuid
    token = _login(web_server, "admin@saluki.com", "admin123")
    email = f"nuevo_{uuid.uuid4().hex[:8]}@saluki.com"
    status, data = _post(f"{web_server}/api/usuarios",
                         {"email": email, "nombre": "Nuevo Usuario",
                          "rol": "VENDEDOR", "password": "clave123"},
                         headers={"Authorization": f"Bearer {token}"})
    assert status in (200, 201), data
    user = auth.verificar_credenciales(email, "clave123")
    assert user is not None
    assert user["rol"] == "VENDEDOR"


def test_api_cambiar_password(web_server):
    conn = db.get_connection()
    user_id = dbutil.query(conn, "SELECT id FROM usuarios WHERE email = 'admin@saluki.com'").fetchone()["id"]
    conn.close()
    token = _login(web_server, "admin@saluki.com", "admin123")
    status, data = _put(f"{web_server}/api/usuarios/{user_id}/password",
                        {"new_password": "admin124"},
                        headers={"Authorization": f"Bearer {token}"})
    assert status == 200, data
    user = auth.verificar_credenciales("admin@saluki.com", "admin124")
    assert user is not None


def test_api_listar_auditoria(web_server):
    token = _login(web_server, "admin@saluki.com", "admin123")
    status, data = _get(f"{web_server}/api/auditoria", headers={"Authorization": f"Bearer {token}"})
    assert status == 200
    assert isinstance(data, list)


def test_api_login_registra_auditoria(web_server):
    conn = db.get_connection()
    dbutil.query(conn, "DELETE FROM auditoria")
    conn.commit()
    conn.close()
    _login(web_server, "admin@saluki.com", "admin123")
    conn = db.get_connection()
    rows = dbutil.query(conn, "SELECT * FROM auditoria WHERE evento ILIKE '%login%'").fetchall()
    conn.close()
    assert len(rows) >= 1


# ============================================================
# TASK 5: Default-deny en /api/*
# ============================================================

def test_api_endpoints_requieren_token(web_server):
    for path in ("/api/empresa", "/api/clientes", "/api/productos",
                 "/api/facturas", "/api/usuarios", "/api/roles", "/api/auditoria"):
        status, _ = _get(f"{web_server}{path}")
        assert status == 401, f"{path} sin token debe dar 401, dio {status}"


def test_api_sin_permiso_da_403(web_server):
    conn = db.get_connection()
    h, salt = auth.hash_password("vendedor123")
    now = datetime.now().isoformat()
    dbutil.query(conn, 
        "INSERT INTO usuarios (email, nombre, rol, hash_password, salt, activo, created_at) "
        "VALUES ('vendedor@saluki.com', 'Carlos Vendedor', 'VENDEDOR', ?, ?, 1, ?) "
        "ON CONFLICT (email) DO UPDATE SET hash_password = EXCLUDED.hash_password, salt = EXCLUDED.salt",
        (h, salt, now),
    )
    conn.commit()
    conn.close()
    token = _login(web_server, "vendedor@saluki.com", "vendedor123")
    status, data = _get(f"{web_server}/api/usuarios", headers={"Authorization": f"Bearer {token}"})
    assert status == 403


# ============================================================
# TASK 6: Migración legacy
# ============================================================

def test_migrar_hashes_legado():
    import hmac, hashlib
    auth.seed_usuarios()
    conn = db.get_connection()
    # Hash HMAC-SHA256 legado (formato original del ERP)
    legacy_salt = "a" * 32
    legacy_hash = hmac.new(b"admin123", legacy_salt.encode(), hashlib.sha256).hexdigest()
    dbutil.query(conn, 
        "UPDATE usuarios SET hash_password = ?, salt = ? WHERE email = 'admin@saluki.com'",
        (legacy_hash, legacy_salt),
    )
    conn.commit()
    conn.close()
    auth._migrar_hashes_legado()
    user = auth.verificar_credenciales("admin@saluki.com", "admin123")
    assert user is not None


# ---------------------------------------------------------------------------
# Limitación de intentos de inicio de sesión (anti fuerza bruta)
# ---------------------------------------------------------------------------

def test_login_rate_limit_bloquea_tras_fallos(monkeypatch):
    """Con SAP_LOGIN_MAX_INTENTOS activo, N fallos seguidos deben dar 429."""
    monkeypatch.setenv("SAP_LOGIN_MAX_INTENTOS", "3")
    monkeypatch.setattr(srv, "_login_attempts", {})

    clave = srv._login_rate_key("10.9.9.9", "objetivo@ejemplo.com")
    srv._login_limpiar(clave)
    for _ in range(3):
        srv._login_registrar_fallo(clave)
    assert srv._login_bloqueado(clave) is True
    srv._login_limpiar(clave)
    assert srv._login_bloqueado(clave) is False


def test_login_rate_limit_deshabilitado_con_cero(monkeypatch):
    monkeypatch.setenv("SAP_LOGIN_MAX_INTENTOS", "0")
    monkeypatch.setattr(srv, "_login_attempts", {})
    clave = srv._login_rate_key("10.9.9.10", "x@ejemplo.com")
    srv._login_limpiar(clave)
    for _ in range(50):
        srv._login_registrar_fallo(clave)
    assert srv._login_bloqueado(clave) is False
    srv._login_limpiar(clave)


def test_resolver_static_path_bloquea_travesia():
    assert srv.resolver_static_path("/../config.py") is None
    assert srv.resolver_static_path("/../../etc/passwd") is None
    assert srv.resolver_static_path("/%2e%2e/config.py") is None
    assert srv.resolver_static_path("/..%2fconfig.py") is None
    assert srv.resolver_static_path("/a/../../config.py") is None
    # rutas legítimas siguen resolviendo dentro de static/
    assert srv.resolver_static_path("/") is not None
    assert srv.resolver_static_path("/app.js") is not None
