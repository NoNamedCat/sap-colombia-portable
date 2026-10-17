"""Tests para seguridad de primera ejecucion: seed aleatorio + cambio forzoso."""
import json
import urllib.request
import urllib.error


from sap_colombia import auth
from sap_colombia import database as db
import psycopg2
from sap_colombia import dbutil
from sap_colombia import rbac


def _post(path, payload=None, headers=None):
    data = json.dumps(payload).encode() if payload else b""
    h = {"Content-Type": "application/json"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(f"{web_server}/api{path}", data=data, headers=h, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())


def test_seed_cre_un_admin_con_password_aleatoria():
    """seed_usuarios crea admin@saluki.com con password_changed_at NULL (forzar cambio)."""
    auth.seed_usuarios()
    conn = db.get_connection()
    row = dbutil.query(conn, 
        "SELECT email, rol, password_changed_at FROM usuarios WHERE email = 'admin@saluki.com'"
    ).fetchone()
    conn.close()
    assert row is not None
    assert row["rol"] in ("SUPERADMIN", "ADMIN")
    assert row["password_changed_at"] is None


def test_login_admin_sin_password_cambio_devuelve_flag():
    """verificar_credenciales de admin (password_changed_at=NULL) devuelve el flag."""
    auth.seed_usuarios()
    conn = db.get_connection()
    row = dbutil.query(conn, "SELECT id FROM usuarios WHERE email = 'admin@saluki.com'").fetchone()
    uid = row["id"]
    conn.close()
    # Cambiamos a una password conocida y luego la volvemos a NULL para simular primer ingreso
    auth.cambiar_password(uid, "pass_de_prueba")
    conn = db.get_connection()
    dbutil.query(conn, "UPDATE usuarios SET password_changed_at = NULL WHERE email = 'admin@saluki.com'")
    conn.commit()
    conn.close()
    user = auth.verificar_credenciales("admin@saluki.com", "pass_de_prueba")
    assert user is not None
    assert user["password_changed_at"] is None


def test_cambiar_password_setea_password_changed_at():
    """cambiar_password setea password_changed_at (ya implementado)."""
    auth.seed_usuarios()
    conn = db.get_connection()
    row = dbutil.query(conn, "SELECT id FROM usuarios WHERE email = 'admin@saluki.com'").fetchone()
    uid = row["id"]
    conn.close()
    result = auth.cambiar_password(uid, "nueva_password_segura")
    assert result["ok"] is True
    conn = db.get_connection()
    row = dbutil.query(conn, 
        "SELECT password_changed_at FROM usuarios WHERE email = 'admin@saluki.com'"
    ).fetchone()
    conn.close()
    assert row is not None
    assert row["password_changed_at"] is not None


def test_seed_no_crea_usarios_secundarios():
    """seed_usuarios no crea (ni preserva) contador/vendedor/almacenista."""
    auth.seed_usuarios()
    conn = db.get_connection()
    for email in ("contador@saluki.com", "vendedor@saluki.com", "almacenista@saluki.com"):
        # Borrar auditoria primero (FK) y luego al usuario
        for row in dbutil.query(conn, "SELECT id FROM usuarios WHERE email = ?", (email,)).fetchall():
            uid = row["id"]
            dbutil.query(conn, "DELETE FROM auditoria WHERE usuario_id = ?", (uid,))
            dbutil.query(conn, "DELETE FROM usuarios WHERE id = ?", (uid,))
    conn.commit()
    conn.close()
    # Reiniciar seed: no debe re-crear los secundarios
    auth.seed_usuarios()
    conn = db.get_connection()
    for email in ("contador@saluki.com", "vendedor@saluki.com", "almacenista@saluki.com"):
        row = dbutil.query(conn, "SELECT 1 FROM usuarios WHERE email = ?", (email,)).fetchone()
        assert row is None, f"{email} no debe ser creado por seed"
    conn.close()


def test_verificar_credenciales_incluye_password_changed_at():
    """verificar_credenciales devuelve el flag password_changed_at."""
    auth.seed_usuarios()
    conn = db.get_connection()
    row = dbutil.query(conn, "SELECT id FROM usuarios WHERE email = 'admin@saluki.com'").fetchone()
    uid = row["id"]
    conn.close()
    # Cambiamos la password a un valor conocido para poder hacer login
    auth.cambiar_password(uid, "pass_de_prueba")
    # Ahora password_changed_at NO es NULL, así que verificar_credenciales debería
    # devolver password_changed_at != None
    user = auth.verificar_credenciales("admin@saluki.com", "pass_de_prueba")
    assert user is not None
    assert "password_changed_at" in user
    assert user["password_changed_at"] is not None
