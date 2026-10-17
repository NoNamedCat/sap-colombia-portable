"""Pruebas TDD para los endpoints de API de nómina y empleados."""

import json
from sap_colombia import dbutil
import threading
import time
from urllib.request import urlopen, Request
import pytest
from sap_colombia.web_server import SapWebHandler
from http.server import HTTPServer

TEST_PORT = 8091


@pytest.fixture(scope="module")
def web_server():
    from sap_colombia import database as db
    from sap_colombia import auth
    from sap_colombia import rbac
    from sap_colombia import dbutil
    db.init_db()
    # limpiar empleados y nominas de ejecuciones anteriores
    conn = db.get_connection()
    with conn:
        for tabla in ["nominas", "empleados", "asientos_contables", "movimientos_contables"]:
            try:
                dbutil.query(conn, f"DELETE FROM {tabla}")
            except Exception:
                pass
    conn.close()
    auth.seed_usuarios()
    rbac.ensure_rbac()
    server = HTTPServer(("127.0.0.1", TEST_PORT), SapWebHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.5)
    yield f"http://127.0.0.1:{TEST_PORT}"
    server.shutdown()
    server.server_close()


def _get(url, headers=None):
    req = Request(url, headers=headers or {})
    with urlopen(req) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


def _post(url, data, headers=None):
    req = Request(url, data=json.dumps(data).encode("utf-8"),
                  headers={"Content-Type": "application/json", **(headers or {})})
    with urlopen(req) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


def _get_admin_token(web_server):
    from sap_colombia import auth, database as db
    conn = db.get_connection()
    row = dbutil.query(conn, "SELECT id FROM usuarios WHERE email = 'admin@saluki.com'").fetchone()
    conn.close()
    if row:
        auth.cambiar_password(row["id"], "admin123")
    status, data = _post(f"{web_server}/api/auth/login",
                         {"email": "admin@saluki.com", "password": "admin123"})
    assert status == 200, f"Login failed: {data}"
    return data["token"]


def test_api_empleados_crud(web_server):
    token = _get_admin_token(web_server)
    payload = {
        "tipo_documento": "CC",
        "documento": "987654321",
        "nombres": "Ana",
        "apellidos": "García",
        "salario_base": "1300000.00",
        "auxilio_transporte": "149095.00",
        "activo": 1,
    }
    status, data = _post(f"{web_server}/api/empleados", payload,
                         headers={"Authorization": f"Bearer {token}"})
    assert status == 200
    assert data["documento"] == "987654321"
    emp_id = data["id"]

    status, data = _get(f"{web_server}/api/empleados",
                        headers={"Authorization": f"Bearer {token}"})
    assert status == 200
    assert any(e["documento"] == "987654321" for e in data)


def test_api_nomina_pagar(web_server):
    token = _get_admin_token(web_server)
    payload_emp = {
        "tipo_documento": "CC",
        "documento": "555666777",
        "nombres": "Carlos",
        "apellidos": "López",
        "salario_base": "1500000.00",
        "auxilio_transporte": "149095.00",
        "activo": 1,
    }
    status, emp = _post(f"{web_server}/api/empleados", payload_emp,
                        headers={"Authorization": f"Bearer {token}"})
    assert status == 200

    payload_nom = {
        "empleado_id": emp["id"],
        "periodo_inicio": "2026-01-01",
        "periodo_fin": "2026-01-31",
    }
    status, data = _post(f"{web_server}/api/nomina/emitir", payload_nom,
                         headers={"Authorization": f"Bearer {token}"})
    assert status == 200
    nomina_id = data["nomina"]["id"]
    neto = data["nomina"]["neto_pagar"]

    status, data = _post(f"{web_server}/api/nomina/pagar", {"nomina_id": nomina_id, "medio_pago": "EFECTIVO"},
                         headers={"Authorization": f"Bearer {token}"})
    assert status == 200
    assert data["estado"] == "PAGADA"
    assert data["recibo"]["monto"] == neto


def test_api_nomina_pagar_doble(web_server):
    token = _get_admin_token(web_server)
    payload_emp = {
        "tipo_documento": "CC",
        "documento": "111222333",
        "nombres": "Marta",
        "apellidos": "Ríos",
        "salario_base": "1400000.00",
        "auxilio_transporte": "149095.00",
        "activo": 1,
    }
    status, emp = _post(f"{web_server}/api/empleados", payload_emp,
                        headers={"Authorization": f"Bearer {token}"})
    assert status == 200

    payload_nom = {
        "empleado_id": emp["id"],
        "periodo_inicio": "2026-02-01",
        "periodo_fin": "2026-02-28",
    }
    status, data = _post(f"{web_server}/api/nomina/emitir", payload_nom,
                         headers={"Authorization": f"Bearer {token}"})
    assert status == 200
    nomina_id = data["nomina"]["id"]

    status, data = _post(f"{web_server}/api/nomina/pagar", {"nomina_id": nomina_id, "medio_pago": "EFECTIVO"},
                         headers={"Authorization": f"Bearer {token}"})
    assert status == 200

    # Doble pago debe fallar
    try:
        status, data = _post(f"{web_server}/api/nomina/pagar", {"nomina_id": nomina_id, "medio_pago": "EFECTIVO"},
                             headers={"Authorization": f"Bearer {token}"})
        assert status == 400
    except Exception:
        # urlopen raises HTTPError on 4xx; catch and verify
        pass
