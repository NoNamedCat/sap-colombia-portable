"""Pruebas unitarias y de integración para la API REST del Servidor Web SAP Colombia."""

import json
from sap_colombia import dbutil
from datetime import datetime, timezone
import threading
import time
from urllib.request import urlopen, Request
import pytest
from sap_colombia import database as db
from sap_colombia import auth
from sap_colombia.web_server import run_web_server, SapWebHandler
from http.server import HTTPServer

TEST_PORT = 8089

@pytest.fixture(scope="module")
def web_server():
    from sap_colombia import database as db
    from sap_colombia import auth
    from sap_colombia import rbac
    _reset_db()
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


def _reset_db():
    from sap_colombia import database as db
    conn = db.get_connection()
    with conn:
        for tabla in ["empresas", "clientes", "productos"]:
            try:
                dbutil.query(conn, f"DELETE FROM {tabla}")
            except Exception:
                pass
    conn.close()

def _get(url, headers=None):
    req = Request(url, headers=headers or {})
    with urlopen(req) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))

def _post(url, data, headers=None):
    req = Request(url, data=json.dumps(data).encode("utf-8"), headers={"Content-Type": "application/json", **(headers or {})})
    with urlopen(req) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


def _get_admin_token(web_server):
    """Login del admin con una contraseña conocida y propia del test.

    ``auth.seed_usuarios()`` ya no reescribe el hash en cada arranque (solo crea
    al usuario si no existe), por lo que esta suite no puede asumir que la
    contraseña sigue siendo ``admin123``: otros archivos de la suite la rotan.
    Resetear explícitamente hace el test determinista y aislado.
    """
    conn = db.get_connection()
    with conn:
        h, salt = auth.hash_password("admin123")
        dbutil.query(
            conn,
            "UPDATE usuarios SET hash_password = ?, salt = ?, activo = 1, "
            "password_changed_at = ? WHERE email = 'admin@saluki.com'",
            (h, salt, datetime.now(timezone.utc).isoformat(sep=" ")),
        )
    conn.close()
    status, data = _post(f"{web_server}/api/auth/login", {"email": "admin@saluki.com", "password": "admin123"})
    assert status == 200
    return data["token"]

def test_api_empresa(web_server):
    token = _get_admin_token(web_server)
    status, data = _get(f"{web_server}/api/empresa", headers={"Authorization": f"Bearer {token}"})
    assert status == 200
    assert "nit" in data
    assert data["razon_social"] == "Empresa Corporativa S.A.S."
    assert "color_primario" in data
    assert "fuente_nombre" in data
    assert "logo_data" in data

def test_api_clientes(web_server):
    token = _get_admin_token(web_server)
    status, data = _get(f"{web_server}/api/clientes", headers={"Authorization": f"Bearer {token}"})
    assert status == 200
    assert len(data) >= 3

def test_api_productos(web_server):
    token = _get_admin_token(web_server)
    status, data = _get(f"{web_server}/api/productos", headers={"Authorization": f"Bearer {token}"})
    assert status == 200
    assert len(data) >= 5

def test_api_liquidar(web_server):
    token = _get_admin_token(web_server)
    payload = {
        "lineas": [
            {
                "producto_codigo": "P001",
                "descripcion": "Laptop Dell",
                "cantidad": 1,
                "valor_unitario": 1000000,
                "tarifa_iva": "IVA_19",
                "tipo_bien_servicio": "BIENES"
            }
        ]
    }
    status, data = _post(f"{web_server}/api/liquidar", payload, headers={"Authorization": f"Bearer {token}"})
    assert status == 200
    assert data["base_total"] == "1000000.00"
    assert data["iva_19"] == "190000.00"
    assert data["total_iva"] == "190000.00"
    assert data["retefuente"] == "25000.00"  # 2.5% sobre base
    assert data["reteiva"] == "28500.00"     # 15% sobre IVA
    assert data["reteica"] == "6900.00"      # 6.9x1000 sobre base
    assert data["total_factura"] == "1129600.00"

def test_api_emitir_factura_completa(web_server):
    from sap_colombia import auth
    auth.seed_usuarios()
    token = _get_admin_token(web_server)
    payload = {
        "cliente_nit": "1234567890",
        "tipo_operacion": "01",
        "lineas": [
            {
                "producto_codigo": "P001",
                "descripcion": "Servicio Consultoría SAP",
                "cantidad": 2,
                "valor_unitario": 500000,
                "tarifa_iva": "IVA_19",
                "tipo_bien_servicio": "SERVICIOS"
            }
        ]
    }
    status, data = _post(f"{web_server}/api/emitir", payload, headers={"Authorization": f"Bearer {token}"})
    assert status == 200
    assert "consecutivo" in data
    assert "cufe" in data
    assert len(data["cufe"]) == 96  # SHA-384
    assert data["estado_dian"] == "Aceptada"
    assert data["status_code"] == "00"
    assert "track_id" in data

    # Consultar historial
    status, facturas = _get(f"{web_server}/api/facturas", headers={"Authorization": f"Bearer {token}"})
    assert status == 200
    assert len(facturas) >= 1


def test_api_exogena_1003(web_server):
    from sap_colombia import auth
    from sap_colombia import database as db
    auth.seed_usuarios()
    token = _get_admin_token(web_server)
    
    conn = db.get_connection()
    row = dbutil.query(conn, "SELECT id FROM empresas ORDER BY id LIMIT 1").fetchone()
    empresa_id = row["id"] if row else 1
    dbutil.query(conn, 
        "INSERT INTO clientes (nit, dv, tipo_documento, razon_social, direccion, municipio, empresa_id) "
        "VALUES ('800987656', '9', 'NIT', 'Cliente Exogena', 'Cra 5 #6', 'Bogotá', ?) "
        "ON CONFLICT (empresa_id, nit) DO UPDATE SET razon_social = 'Cliente Exogena'",
        (empresa_id,),
    )
    conn.commit()
    db.guardar_factura({
        "consecutivo": "FAC004", "fecha": "2026-10-04", "hora": "12:00:00-05:00",
        "subtotal": "30000.00", "iva_19": "5700.00", "iva_5": "0.00", "iva_0": "0.00",
        "total_iva": "5700.00", "total_factura": "35700.00",
        "cliente_nit": "800987656", "cufe": "f" * 96, "estado": "EXITOSA",
        "saldo_pendiente": "35700.00", "prefijo": "F",
    }, [])
    conn.close()

    status, data = _get(f"{web_server}/api/exogena/formato-1003?ano=2026", headers={"Authorization": f"Bearer {token}"})
    assert status == 200
    # El formato 1003 se entrega como archivo plano radicable (Res. 000162/2023),
    # no como XML: la DIAN no ingiere XML para exógena.
    assert data["formato"] == "1003"
    assert data["nombre_archivo"].startswith("1003012026")
    assert data["nombre_archivo"].endswith(".TXT")
    assert data["encabezado"].startswith("000|")
    assert data["delimitador"] == "|"
    assert data["total_registros"] >= 1
    # Regresión del consecutivo duplicado: el prefijo "F" + consecutivo
    # "FAC004" producía "FFAC004" en la exógena.
    consecutivos = [l.split("|")[6] for l in data["registros"]]
    assert "FAC004" in consecutivos
    assert "FFAC004" not in consecutivos
    assert not any(c.startswith(c[:1] * 2) and c[1:4].isalpha() for c in consecutivos)
