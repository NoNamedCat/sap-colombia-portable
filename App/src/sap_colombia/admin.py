import psycopg2
from sap_colombia import dbutil
import threading
from datetime import datetime

from sap_colombia import auth
from sap_colombia import database as db

EMPREASAS_COLUMNS = [
    "id", "nit", "dv", "razon_social", "direccion", "municipio", "departamento",
    "prefijo_resolucion", "resolucion_dian", "fecha_resolucion",
    "rango_desde", "rango_hasta", "clave_tecnica", "tipo_ambiente",
    "ruta_certificado", "password_certificado", "url_dian",
    "en_contingencia", "motivo_contingencia", "fecha_contingencia",
    "nombre_marca", "logo_data", "color_primario", "color_secundario",
    "color_sidebar", "color_fondo", "fuente_nombre", "fuente_data",
]

_migrated = False
_migrate_lock = threading.Lock()


def _ensure_migrations(conn: psycopg2.extensions.connection) -> None:
    global _migrated
    if _migrated:
        return
    with _migrate_lock:
        if _migrated:
            return
        cols = set(dbutil.table_columns(conn, 'usuarios'))
        if "empresa_id" not in cols:
            dbutil.query(conn, "ALTER TABLE usuarios ADD COLUMN empresa_id INTEGER")
        cols_roles = set(dbutil.table_columns(conn, 'roles'))
        if "tipo" not in cols_roles:
            dbutil.query(conn, "ALTER TABLE roles ADD COLUMN tipo TEXT DEFAULT 'EMPRESA'")
        dbutil.query(conn, """
            CREATE TABLE IF NOT EXISTS roles_empresas (
                role_id INTEGER NOT NULL,
                empresa_id INTEGER NOT NULL,
                PRIMARY KEY (role_id, empresa_id),
                FOREIGN KEY (role_id) REFERENCES roles(id) ON DELETE CASCADE,
                FOREIGN KEY (empresa_id) REFERENCES empresas(id) ON DELETE CASCADE
            )
        """)
        conn.commit()
        _migrated = True


def _row_to_dict(row: dict) -> dict:
    return dict(row)


def get_empresas() -> list[dict]:
    conn = db.get_connection()
    try:
        _ensure_migrations(conn)
        rows = dbutil.query(conn, "SELECT * FROM empresas ORDER BY id").fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def get_empresa(empresa_id: int) -> dict | None:
    conn = db.get_connection()
    try:
        row = dbutil.query(conn, "SELECT * FROM empresas WHERE id = ?", (empresa_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def create_empresa(data: dict, creado_por: int) -> dict | None:
    required = ["nit", "razon_social"]
    if not data.get("nit") or not data.get("razon_social"):
        return None
    conn = db.get_connection()
    try:
        allowed = [c for c in EMPREASAS_COLUMNS if c != "id" and c in data]
        if not allowed:
            return None
        cols = ", ".join(allowed)
        placeholders = ", ".join("?" for _ in allowed)
        values = [data[c] for c in allowed]
        cur = dbutil.query(conn, f"INSERT INTO empresas ({cols}) VALUES ({placeholders}) RETURNING id", values)
        conn.commit()
        new_id = cur.fetchone()["id"]
        row = dbutil.query(conn, "SELECT * FROM empresas WHERE id = ?", (new_id,)).fetchone()
        return dict(row) if row else None
    except psycopg2.IntegrityError:
        return None
    finally:
        conn.close()


def update_empresa(empresa_id: int, data: dict) -> dict | None:
    conn = db.get_connection()
    try:
        existing = dbutil.query(conn, "SELECT * FROM empresas WHERE id = ?", (empresa_id,)).fetchone()
        if existing is None:
            return None
        allowed = [c for c in EMPREASAS_COLUMNS if c not in ("id",) and c in data]
        if not allowed:
            return dict(existing)
        sets = ", ".join(f"{c} = ?" for c in allowed)
        values = [data[c] for c in allowed]
        values.append(empresa_id)
        dbutil.query(conn, f"UPDATE empresas SET {sets} WHERE id = ?", values)
        conn.commit()
        row = dbutil.query(conn, "SELECT * FROM empresas WHERE id = ?", (empresa_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def delete_empresa(empresa_id: int) -> bool:
    conn = db.get_connection()
    try:
        count = dbutil.query(conn, 
            "SELECT COUNT(*) AS n FROM usuarios WHERE empresa_id = ?", (empresa_id,)
        ).fetchone()["n"]
        if count > 0:
            return False
        dbutil.query(conn, "DELETE FROM empresas WHERE id = ?", (empresa_id,))
        conn.commit()
        return True
    except Exception:
        return False
    finally:
        conn.close()


def get_empresas_summary() -> list[dict]:
    conn = db.get_connection()
    try:
        rows = dbutil.query(conn, 
            """SELECT e.id, e.razon_social, e.nit, e.nombre_marca, e.logo_data,
                      e.color_primario, e.color_secundario, e.color_sidebar, e.color_fondo, e.fuente_nombre,
                      (SELECT COUNT(*) FROM usuarios u WHERE u.empresa_id = e.id) AS user_count,
                      (SELECT COUNT(*) FROM usuarios u WHERE u.empresa_id = e.id AND u.activo = 1) AS active_users
               FROM empresas e ORDER BY e.id"""
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_system_users() -> list[dict]:
    conn = db.get_connection()
    try:
        rows = dbutil.query(conn, 
            "SELECT id, email, nombre, rol, activo, empresa_id, created_at FROM usuarios ORDER BY id"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_system_user(user_id: int) -> dict | None:
    conn = db.get_connection()
    try:
        row = dbutil.query(conn, 
            "SELECT id, email, nombre, rol, activo, empresa_id, created_at FROM usuarios WHERE id = ?",
            (user_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def create_system_user(data: dict) -> dict | None:
    required = ["email", "nombre", "password", "rol"]
    if not all(data.get(f) for f in required):
        return None
    password = data["password"]
    h, salt = auth.hash_password(password)
    empresa_id = data.get("empresa_id")
    created_at = datetime.now().isoformat()
    conn = db.get_connection()
    try:
        cur = dbutil.query(conn, 
            "INSERT INTO usuarios (email, nombre, rol, hash_password, salt, activo, created_at, empresa_id) VALUES (?, ?, ?, ?, ?, 1, ?, ?) RETURNING id",
            (data["email"], data["nombre"], data["rol"], h, salt, created_at, empresa_id),
        )
        conn.commit()
        new_id = cur.fetchone()["id"]
        return get_system_user(new_id)
    except psycopg2.IntegrityError:
        return None
    finally:
        conn.close()


def update_system_user(user_id: int, data: dict) -> dict | None:
    conn = db.get_connection()
    try:
        existing = dbutil.query(conn, "SELECT * FROM usuarios WHERE id = ?", (user_id,)).fetchone()
        if existing is None:
            return None
        updates = []
        values = []
        if "nombre" in data:
            updates.append("nombre = ?")
            values.append(data["nombre"])
        if "rol" in data:
            updates.append("rol = ?")
            values.append(data["rol"])
        if "activo" in data:
            updates.append("activo = ?")
            values.append(int(data["activo"]))
        if "empresa_id" in data:
            updates.append("empresa_id = ?")
            values.append(data["empresa_id"])
        if "password" in data:
            h, salt = auth.hash_password(data["password"])
            updates.append("hash_password = ?")
            values.append(h)
            updates.append("salt = ?")
            values.append(salt)
            updates.append("password_changed_at = ?")
            values.append(datetime.now().isoformat())
        if updates:
            values.append(user_id)
            dbutil.query(conn, f"UPDATE usuarios SET {', '.join(updates)} WHERE id = ?", values)
            conn.commit()
        return get_system_user(user_id)
    finally:
        conn.close()


def set_user_password(user_id: int, new_password: str) -> bool:
    if not new_password:
        return False
    h, salt = auth.hash_password(new_password)
    now = datetime.utcnow().isoformat(sep=" ", timespec="seconds")
    conn = db.get_connection()
    try:
        cur = dbutil.query(conn, 
            "UPDATE usuarios SET hash_password = ?, salt = ?, password_changed_at = ? WHERE id = ?",
            (h, salt, now, user_id),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def delete_system_user(user_id: int) -> bool:
    conn = db.get_connection()
    try:
        user = dbutil.query(conn, "SELECT rol FROM usuarios WHERE id = ?", (user_id,)).fetchone()
        if user is None:
            return False
        if user["rol"] in ("ADMIN", "SUPERADMIN"):
            remaining = dbutil.query(conn, 
                "SELECT COUNT(*) AS n FROM usuarios WHERE rol IN ('ADMIN', 'SUPERADMIN')"
            ).fetchone()["n"]
            if remaining <= 1:
                return False
        cur = dbutil.query(conn, "DELETE FROM usuarios WHERE id = ?", (user_id,))
        conn.commit()
        return cur.rowcount > 0
    except Exception:
        return False
    finally:
        conn.close()


def get_roles() -> list[dict]:
    conn = db.get_connection()
    try:
        rows = dbutil.query(conn, "SELECT * FROM roles ORDER BY id").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_role(role_id: int) -> dict | None:
    conn = db.get_connection()
    try:
        row = dbutil.query(conn, "SELECT * FROM roles WHERE id = ?", (role_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_roles_for_empresa(empresa_id: int) -> list[dict]:
    conn = db.get_connection()
    try:
        _ensure_migrations(conn)
        rows = dbutil.query(conn, 
            """SELECT r.* FROM roles r
               JOIN roles_empresas re ON re.role_id = r.id
               WHERE re.empresa_id = ? ORDER BY r.id""",
            (empresa_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def create_role(data: dict, creado_por: int | None = None) -> dict | None:
    if not data.get("nombre"):
        return None
    empresa_id = data.get("empresa_id")
    created_at = datetime.now().isoformat()
    conn = db.get_connection()
    try:
        cur = dbutil.query(conn, 
            "INSERT INTO roles (nombre, descripcion, activo, creado_por, created_at) VALUES (?, ?, 1, ?, ?) RETURNING id",
            (data["nombre"], data.get("descripcion"), creado_por, created_at),
        )
        conn.commit()
        new_id = cur.fetchone()["id"]
        if empresa_id is not None:
            dbutil.query(conn, 
                "INSERT INTO roles_empresas (role_id, empresa_id) VALUES (?, ?) ON CONFLICT DO NOTHING",
                (new_id, empresa_id),
            )
            conn.commit()
        row = dbutil.query(conn, "SELECT * FROM roles WHERE id = ?", (new_id,)).fetchone()
        return dict(row) if row else None
    except psycopg2.IntegrityError:
        return None
    finally:
        conn.close()


def update_role(role_id: int, data: dict) -> dict | None:
    conn = db.get_connection()
    try:
        existing = dbutil.query(conn, "SELECT * FROM roles WHERE id = ?", (role_id,)).fetchone()
        if existing is None:
            return None
        updates = []
        values = []
        if "nombre" in data:
            updates.append("nombre = ?")
            values.append(data["nombre"])
        if "descripcion" in data:
            updates.append("descripcion = ?")
            values.append(data["descripcion"])
        if "activo" in data:
            updates.append("activo = ?")
            values.append(int(data["activo"]))
        if updates:
            values.append(role_id)
            dbutil.query(conn, f"UPDATE roles SET {', '.join(updates)} WHERE id = ?", values)
            conn.commit()
        row = dbutil.query(conn, "SELECT * FROM roles WHERE id = ?", (role_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def delete_role(role_id: int) -> bool:
    conn = db.get_connection()
    try:
        count = dbutil.query(conn, 
            "SELECT COUNT(*) AS n FROM usuarios WHERE rol = (SELECT nombre FROM roles WHERE id = ?)",
            (role_id,),
        ).fetchone()["n"]
        if count > 0:
            return False
        _ensure_migrations(conn)
        dbutil.query(conn, "DELETE FROM roles_empresas WHERE role_id = ?", (role_id,))
        dbutil.query(conn, "DELETE FROM roles WHERE id = ?", (role_id,))
        conn.commit()
        return True
    except Exception:
        return False
    finally:
        conn.close()


def get_role_permissions(role_id: int) -> list[str]:
    conn = db.get_connection()
    try:
        rows = dbutil.query(conn, 
            "SELECT p.recurso || ':' || p.accion AS permiso "
            "FROM role_permissions rp "
            "JOIN roles r ON r.id = rp.role_id "
            "JOIN permisos p ON p.id = rp.permission_id "
            "WHERE r.id = ? "
            "ORDER BY p.recurso, p.accion",
            (role_id,),
        ).fetchall()
        return [r["permiso"] for r in rows]
    finally:
        conn.close()


def set_role_permissions(role_id: int, permisos: list[str]) -> bool:
    conn = db.get_connection()
    try:
        role = dbutil.query(conn, "SELECT id FROM roles WHERE id = ?", (role_id,)).fetchone()
        if role is None:
            return False
        permisos_db = {row["recurso"] + ":" + row["accion"]: row["id"]
                       for row in dbutil.query(conn, "SELECT * FROM permisos").fetchall()}
        dbutil.query(conn, "DELETE FROM role_permissions WHERE role_id = ?", (role_id,))
        for p in permisos:
            if p in permisos_db:
                dbutil.query(conn, 
                    "INSERT INTO role_permissions (role_id, permission_id) VALUES (?, ?) "
                    "ON CONFLICT DO NOTHING",
                    (role_id, permisos_db[p]),
                )
        conn.commit()
        return True
    finally:
        conn.close()


def assign_role_to_empresa(role_id: int, empresa_id: int) -> bool:
    conn = db.get_connection()
    try:
        role = dbutil.query(conn, "SELECT id FROM roles WHERE id = ?", (role_id,)).fetchone()
        empresa = dbutil.query(conn, "SELECT id FROM empresas WHERE id = ?", (empresa_id,)).fetchone()
        if role is None or empresa is None:
            return False
        _ensure_migrations(conn)
        dbutil.query(conn, 
            "INSERT INTO roles_empresas (role_id, empresa_id) VALUES (?, ?) ON CONFLICT DO NOTHING",
            (role_id, empresa_id),
        )
        conn.commit()
        return True
    except Exception:
        return False
    finally:
        conn.close()


def unassign_role_from_empresa(role_id: int, empresa_id: int) -> bool:
    conn = db.get_connection()
    try:
        _ensure_migrations(conn)
        cur = dbutil.query(conn, 
            "DELETE FROM roles_empresas WHERE role_id = ? AND empresa_id = ?",
            (role_id, empresa_id),
        )
        conn.commit()
        return cur.rowcount > 0
    except Exception:
        return False
    finally:
        conn.close()


def get_roles_for_user(user_id: int) -> list[dict]:
    conn = db.get_connection()
    try:
        user = dbutil.query(conn, "SELECT rol, empresa_id FROM usuarios WHERE id = ?", (user_id,)).fetchone()
        if user is None:
            return []
        results = []
        _ensure_migrations(conn)
        rows = dbutil.query(conn, 
            """SELECT r.* FROM roles r
               WHERE r.nombre = ?
               AND (r.id IN (SELECT role_id FROM roles_empresas WHERE empresa_id = ?) OR ? IS NULL)""",
            (user["rol"], user["empresa_id"], user["empresa_id"]),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def assign_user_role(user_id: int, rol: str) -> bool:
    if not rol:
        return False
    conn = db.get_connection()
    try:
        cur = dbutil.query(conn, 
            "UPDATE usuarios SET rol = ? WHERE id = ?",
            (rol, user_id),
        )
        conn.commit()
        return cur.rowcount > 0
    except Exception:
        return False
    finally:
        conn.close()


def get_empresas_for_user(usuario_id: int) -> list[dict]:
    """Obtiene las empresas a las que un usuario tiene acceso autorizado."""
    conn = db.get_connection()
    try:
        user = dbutil.query(conn, "SELECT rol, empresa_id FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()
        if not user:
            return []
        # Si es SUPERADMIN, ADMIN_SISTEMA o ADMIN, tiene acceso a todas las empresas
        if user["rol"] in ("SUPERADMIN", "ADMIN_SISTEMA", "ADMIN"):
            rows = dbutil.query(conn, "SELECT * FROM empresas ORDER BY id").fetchall()
            return [dict(r) for r in rows]
        
        # Consultar tabla usuario_empresas
        _ensure_migrations(conn)
        rows = dbutil.query(
            conn,
            """SELECT e.*, ue.rol_en_empresa, ue.es_predeterminada
               FROM empresas e
               JOIN usuario_empresas ue ON ue.empresa_id = e.id
               WHERE ue.usuario_id = ?
               ORDER BY e.id""",
            (usuario_id,),
        ).fetchall()
        if rows:
            return [dict(r) for r in rows]
        
        # Fallback si tiene empresa_id asignado directamente en usuarios
        if user["empresa_id"]:
            row = dbutil.query(conn, "SELECT * FROM empresas WHERE id = ?", (user["empresa_id"],)).fetchone()
            if row:
                return [dict(row)]
        return []
    finally:
        conn.close()


def assign_user_to_empresa(usuario_id: int, empresa_id: int, rol_en_empresa: str = "ADMIN_EMPRESA", es_predeterminada: bool = False) -> bool:
    """Asigna un usuario a una empresa con un rol específico."""
    conn = db.get_connection()
    try:
        _ensure_migrations(conn)
        now = datetime.now().isoformat()
        dbutil.query(
            conn,
            """INSERT INTO usuario_empresas (usuario_id, empresa_id, rol_en_empresa, es_predeterminada, created_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT (usuario_id, empresa_id) DO UPDATE SET rol_en_empresa = EXCLUDED.rol_en_empresa, es_predeterminada = EXCLUDED.es_predeterminada""",
            (usuario_id, empresa_id, rol_en_empresa, 1 if es_predeterminada else 0, now),
        )
        conn.commit()
        return True
    except Exception:
        return False
    finally:
        conn.close()


def unassign_user_from_empresa(usuario_id: int, empresa_id: int) -> bool:
    """Remueve el acceso de un usuario a una empresa."""
    conn = db.get_connection()
    try:
        _ensure_migrations(conn)
        cur = dbutil.query(
            conn,
            "DELETE FROM usuario_empresas WHERE usuario_id = ? AND empresa_id = ?",
            (usuario_id, empresa_id),
        )
        conn.commit()
        return cur.rowcount > 0
    except Exception:
        return False
    finally:
        conn.close()


def get_user_empresas_mapping() -> list[dict]:
    """Retorna el mapeo completo de usuarios y empresas asignadas para la consola de administración."""
    conn = db.get_connection()
    try:
        _ensure_migrations(conn)
        rows = dbutil.query(
            conn,
            """SELECT u.id AS usuario_id, u.email, u.nombre AS usuario_nombre, u.rol AS rol_global,
                      e.id AS empresa_id, e.razon_social, e.nit, ue.rol_en_empresa, ue.es_predeterminada
               FROM usuario_empresas ue
               JOIN usuarios u ON ue.usuario_id = u.id
               JOIN empresas e ON ue.empresa_id = e.id
               ORDER BY u.id, e.id"""
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
