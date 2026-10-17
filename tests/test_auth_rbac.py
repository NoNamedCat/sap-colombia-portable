"""Pruebas TDD para autenticación JWT, RBAC y control de periodos contables."""

import json
from sap_colombia import dbutil
import threading
import time
from datetime import datetime
from urllib.request import urlopen, Request
from urllib.error import HTTPError
import pytest
from http.server import HTTPServer

import sap_colombia.database as db
from sap_colombia import auth
from sap_colombia import period_control
from sap_colombia.web_server import SapWebHandler


TEST_PORT = 8091


@pytest.fixture(scope="module")
def web_server():
    db.init_db()
    auth.seed_usuarios()
    from sap_colombia import rbac
    rbac.ensure_rbac()
    server = HTTPServer(("127.0.0.1", TEST_PORT), SapWebHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.5)
    yield f"http://127.0.0.1:{TEST_PORT}"
    server.shutdown()
    server.server_close()


def _reset_periodos():
    conn = db.get_connection()
    dbutil.query(conn, "DELETE FROM periodos_contables")
    conn.commit()
    conn.close()


@pytest.fixture(autouse=True)
def setup_db():
    db.init_db()
    auth.seed_usuarios()
    from sap_colombia import rbac
    rbac.ensure_rbac()
    _reset_periodos()
    conn = db.get_connection()
    try:
        dbutil.query(conn, "DELETE FROM usuarios WHERE email LIKE 'nuevo_%' OR email LIKE '%@test.co' OR email LIKE '%@ui.test'")
        conn.commit()
    finally:
        conn.close()
    yield
    conn = db.get_connection()
    try:
        dbutil.query(conn, "DELETE FROM clientes WHERE nit IN ('900999999')")
        dbutil.query(conn, "DELETE FROM productos WHERE codigo = 'P-ALERTA'")
        dbutil.query(conn, "UPDATE usuarios SET password_changed_at = NULL")
        conn.commit()
    finally:
        conn.close()


def _get(url, headers=None):
    req = Request(url, headers=headers or {})
    try:
        with urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


def _post(url, data, headers=None):
    req = Request(url, data=json.dumps(data).encode("utf-8"),
                  headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


def _get_admin_id():
    auth.seed_usuarios()
    admin = auth.verificar_credenciales("admin@saluki.com", "admin123")
    return admin["id"]


# --- Unit Tests: auth.py ---

def test_seed_usuarios_creacion():
    usuarios = db.get_usuarios()
    emails = {u["email"] for u in usuarios}
    assert "admin@saluki.com" in emails


def test_seed_usuarios_idempotente():
    auth.seed_usuarios()
    usuarios = db.get_usuarios()
    assert "admin@saluki.com" in {u["email"] for u in usuarios}


def test_verificar_credenciales_valido():
    user = auth.verificar_credenciales("admin@saluki.com", "admin123")
    assert user is not None
    assert user["rol"] in ("ADMIN", "SUPERADMIN")


def test_verificar_credenciales_invalido():
    user = auth.verificar_credenciales("admin@saluki.com", "password_incorrecta")
    assert user is None


def test_generar_token_y_validar():
    user = auth.verificar_credenciales("admin@saluki.com", "admin123")
    token = auth.generar_token(user)
    payload = auth.validar_token(token)
    assert payload["rol"] in ("ADMIN", "SUPERADMIN")
    assert payload["sub"] == "admin@saluki.com"


def test_validar_token_invalido():
    with pytest.raises(Exception):
        auth.validar_token("token_inválido")


def test_validar_token_expirado():
    import jwt as pyjwt
    from datetime import datetime, timedelta
    exp = datetime.now() - timedelta(hours=1)
    payload = {"sub": "test@saluki.com", "rol": "ADMIN", "exp": int(exp.timestamp())}
    token = pyjwt.encode(payload, auth.SECRET_KEY, algorithm="HS256")
    with pytest.raises(Exception):
        auth.validar_token(token)


# --- Unit Tests: period_control.py ---

def test_periodo_actual_abierto_por_defecto():
    p = period_control.get_periodo_actual()
    assert p["estado"] == "ABIERTO"


def test_cerrar_periodo_exitoso():
    admin_id = _get_admin_id()
    periodo = "2026-09"
    result = period_control.cerrar_periodo(periodo, usuario_id=admin_id, justificacion="Cierre mensual septiembre")
    assert result["estado"] == "CERRADO"
    assert result["justificacion"] == "Cierre mensual septiembre"


def test_cerrar_periodo_sin_justificacion_falla():
    admin_id = _get_admin_id()
    with pytest.raises(ValueError, match="justificación"):
        period_control.cerrar_periodo("2026-08", usuario_id=admin_id, justificacion="")


def test_cerrar_periodo_duplicado_falla():
    admin_id = _get_admin_id()
    periodo = "2026-08"
    period_control.cerrar_periodo(periodo, usuario_id=admin_id, justificacion="Primera vez")
    with pytest.raises(ValueError, match="ya está cerrado"):
        period_control.cerrar_periodo(periodo, usuario_id=admin_id, justificacion="Segunda vez")


def test_reabrir_periodo_admin():
    admin_id = _get_admin_id()
    periodo = "2026-09"
    period_control.cerrar_periodo(periodo, usuario_id=admin_id, justificacion="Cierre")
    result = period_control.reabrir_periodo(periodo, usuario_id=admin_id, justificacion="Ajuste contable")
    assert result["estado"] == "ABIERTO"


def test_reabrir_periodo_no_admin_falla():
    admin_id = _get_admin_id()
    conn = db.get_connection()
    h, salt = auth.hash_password("noadmin123")
    now = datetime.now().isoformat()
    dbutil.query(conn, 
        "INSERT INTO usuarios (email, nombre, rol, hash_password, salt, activo, created_at) "
        "VALUES ('noadmin@saluki.com', 'No Admin', 'VENDEDOR', ?, ?, 1, ?) "
        "ON CONFLICT (email) DO NOTHING",
        (h, salt, now),
    )
    conn.commit()
    row = dbutil.query(conn, "SELECT id FROM usuarios WHERE email = 'noadmin@saluki.com'").fetchone()
    no_admin_id = row["id"]
    conn.close()
    periodo = "2026-10"
    period_control.cerrar_periodo(periodo, usuario_id=admin_id, justificacion="Cierre")
    with pytest.raises(PermissionError, match="ADMIN"):
        period_control.reabrir_periodo(periodo, usuario_id=no_admin_id, justificacion="Intento")


def test_validar_periodo_abierto_ok():
    periodo = period_control.get_periodo_actual()["periodo"]
    result = period_control.validar_periodo_abierto(periodo)
    assert result["estado"] == "ABIERTO"


def test_validar_periodo_cerrado_falla():
    admin_id = _get_admin_id()
    periodo = "2026-11"
    period_control.cerrar_periodo(periodo, usuario_id=admin_id, justificacion="Cierre")
    with pytest.raises(period_control.PeriodoCerradoError):
        period_control.validar_periodo_abierto(periodo)


# --- Integration Tests: API Auth ---

def _get_admin_token(web_server):
    status, data = _post(f"{web_server}/api/auth/login", {"email": "admin@saluki.com", "password": "admin123"})
    assert status == 200, f"Login falló: {data}"
    return data["token"]


def test_api_login_valido(web_server):
    status, data = _post(f"{web_server}/api/auth/login", {"email": "admin@saluki.com", "password": "admin123"})
    assert status == 200
    assert "token" in data
    assert data["rol"] in ("ADMIN", "SUPERADMIN")


def test_api_login_invalido(web_server):
    status, data = _post(f"{web_server}/api/auth/login", {"email": "admin@saluki.com", "password": "wrong"})
    assert status == 401
    assert "error" in data


def test_api_me_valido(web_server):
    token = _get_admin_token(web_server)
    status, data = _get(f"{web_server}/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert status == 200
    assert data["email"] == "admin@saluki.com"
    assert data["rol"] in ("ADMIN", "SUPERADMIN")


def test_api_me_sin_token(web_server):
    req = Request(f"{web_server}/api/auth/me")
    try:
        with urlopen(req) as resp:
            assert False
    except Exception as e:
        assert e.code == 401


def test_api_emitir_sin_token(web_server):
    req = Request(f"{web_server}/api/emitir",
                  data=json.dumps({"cliente_nit": "1234567890", "lineas": [{"producto_codigo": "P001", "descripcion": "Test", "cantidad": 1, "valor_unitario": 100000, "tarifa_iva": "IVA_19"}]}).encode("utf-8"),
                  headers={"Content-Type": "application/json"})
    try:
        with urlopen(req) as resp:
            assert False
    except Exception as e:
        assert e.code == 401


def test_api_emitir_con_token_admin(web_server):
    token = _get_admin_token(web_server)
    payload = {
        "cliente_nit": "1234567890",
        "tipo_operacion": "01",
        "lineas": [
            {"producto_codigo": "P001", "descripcion": "Test Auth", "cantidad": 1, "valor_unitario": 100000, "tarifa_iva": "IVA_19"}
        ]
    }
    status, data = _post(f"{web_server}/api/emitir", payload, headers={"Authorization": f"Bearer {token}"})
    assert status == 200
    assert "cufe" in data


def test_api_cerrar_periodo_admin(web_server):
    token = _get_admin_token(web_server)
    periodo = "2026-12"
    status, data = _post(
        f"{web_server}/api/periodos/cerrar",
        {"periodo": periodo, "justificacion": "Cierre anual"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert status == 200
    assert data["estado"] == "CERRADO"


def test_api_reabrir_periodo_admin(web_server):
    token = _get_admin_token(web_server)
    periodo = "2026-12"
    _post(f"{web_server}/api/periodos/cerrar",
          {"periodo": periodo, "justificacion": "Cierre"},
          headers={"Authorization": f"Bearer {token}"})
    status, data = _post(
        f"{web_server}/api/periodos/reabrir",
        {"periodo": periodo, "justificacion": "Reapertura"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert status == 200
    assert data["estado"] == "ABIERTO"


def test_api_emitir_con_periodo_cerrado_falla(web_server):
    token = _get_admin_token(web_server)
    admin_id = _get_admin_id()
    periodo_actual = period_control.get_periodo_actual()["periodo"]
    period_control.cerrar_periodo(periodo_actual, usuario_id=admin_id, justificacion="Bloqueo de prueba")
    payload = {
        "cliente_nit": "1234567890",
        "tipo_operacion": "01",
        "lineas": [
            {"producto_codigo": "P001", "descripcion": "Test Periodo Cerrado", "cantidad": 1, "valor_unitario": 100000, "tarifa_iva": "IVA_19"}
        ]
    }
    status, data = _post(f"{web_server}/api/emitir", payload, headers={"Authorization": f"Bearer {token}"})
    assert status >= 400
    period_control.reabrir_periodo(periodo_actual, usuario_id=admin_id, justificacion="Reabrir post-test")


# --- RBAC Tests ---

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
    status, data = _post(f"{web_server}/api/auth/login", {"email": "vendedor@saluki.com", "password": "vendedor123"})
    assert status == 200
    vendedor_token = data["token"]
    status, data = _post(f"{web_server}/api/periodos/cerrar",
                         {"periodo": "2027-01", "justificacion": "Intento vendedor"},
                         headers={"Authorization": f"Bearer {vendedor_token}"})
    assert status == 403
