"""Autenticación, JWT y RBAC para ERP SAP Colombia."""

import hashlib
import hmac
import os
import psycopg2
from sap_colombia import dbutil
import time
import secrets
import base64
import struct
from datetime import datetime, timedelta, timezone

import jwt

from sap_colombia import database as db

TOKEN_EXPIRE_MINUTES = 60
PBKDF2_ITERATIONS = 100_000

ROLES = {
    "ADMIN": "Administrador",
    "VENDEDOR": "Vendedor",
    "ALMACENISTA": "Almacenista",
    "CONTADOR": "Contador",
}


def _crear_tablas_seguridad(conn) -> None:
    dbutil.query(conn, 
        "CREATE TABLE IF NOT EXISTS config (clave TEXT PRIMARY KEY, valor TEXT)")
    dbutil.query(conn, 
        "CREATE TABLE IF NOT EXISTS auditoria (id SERIAL PRIMARY KEY,"
        " usuario_id INTEGER, email TEXT, evento TEXT NOT NULL, detalle TEXT,"
        " ip TEXT, created_at TEXT NOT NULL)")


def _get_secret() -> str:
    """Secret JWT: env var SAP_JWT_SECRET o generado y persistido en la BD."""
    from sap_colombia import config as sap_config
    env_secret = sap_config.jwt_secret()
    if env_secret:
        return env_secret
    conn = db.get_connection()
    _crear_tablas_seguridad(conn)
    row = dbutil.query(conn, "SELECT valor FROM config WHERE clave = 'jwt_secret'").fetchone()
    if row and row["valor"]:
        conn.close()
        return row["valor"]
    nuevo = secrets.token_hex(32)
    dbutil.query(conn, 
        "INSERT INTO config (clave, valor) VALUES ('jwt_secret', ?) ON CONFLICT (clave) DO UPDATE SET valor = EXCLUDED.valor",
        (nuevo,),
    )
    conn.commit()
    conn.close()
    return nuevo


SECRET_KEY = _get_secret()


def _hash_legacy(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


_PASSWORD_WEAK = (
    "password", "admin", "123456", "qwerty", "12345678", "123456789",
    "1234567890", "letmein", "welcome", "abc123", "iloveyou", "monkey",
    "dragon", "master", "login", "princess", "starwars", "passw0rd",
)


def validar_fuerteza_password(password: str) -> tuple[bool, str]:
    """Valida la fortaleza de una contraseña.

    Devuelve ``(ok, mensaje)``: si ``ok`` es ``False``, ``mensaje``
    describe la razón de la validez.

    Regla mínima: 8 caracteres, no ser de la lista de contraseñas comunes.
    """
    if len(password) < 8:
        return False, "La contraseña debe tener al menos 8 caracteres"
    if password.lower() in _PASSWORD_WEAK:
        return False, "La contraseña es demasiado común"
    return True, ""


def hash_password(password: str) -> tuple[str, str]:
    """Devuelve (hash, salt) en formato pbkdf2_sha256:iteraciones:salt:hash."""
    salt = secrets.token_hex(8)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), PBKDF2_ITERATIONS)
    h = f"pbkdf2_sha256:{PBKDF2_ITERATIONS}:{salt}:{dk.hex()}"
    return h, salt


def _verificar_hash(password: str, stored: str, salt: str) -> bool:
    if stored.startswith("pbkdf2_sha256:"):
        parts = stored.split(":", 3)
        try:
            iteraciones = int(parts[1])
            salt_val = parts[2]
            hash_val = parts[3]
        except (IndexError, ValueError):
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt_val.encode("utf-8"), iteraciones)
        return hmac.compare_digest(dk.hex(), hash_val)
    # HMAC legado: salt = hex del urandom de 16 bytes (32 chars)
    if salt and len(salt) == 32:
        legacy = hmac.new(password.encode("utf-8"), salt.encode("utf-8"), hashlib.sha256).hexdigest()
        return hmac.compare_digest(legacy, stored)
    return hmac.compare_digest(_hash_legacy(password), stored)


def _migrar_hashes_legado() -> None:
    """Migra hashes HMAC-SHA256 legacy a PBKDF2 (best-effort, una sola pasada)."""
    conn = db.get_connection()
    usuarios = dbutil.query(conn, 
        "SELECT email, salt, hash_password FROM usuarios "
        "WHERE hash_password NOT LIKE 'pbkdf2_sha256:%'"
    ).fetchall()
    for u in usuarios:
        if u["salt"] and len(u["salt"]) == 32:
            legacy = hmac.new(u["email"].encode("utf-8"), u["salt"].encode("utf-8"), hashlib.sha256).hexdigest()
            if legacy == u["hash_password"]:
                nuevo_h, nuevo_salt = hash_password(u["email"])
                dbutil.query(conn, 
                    "UPDATE usuarios SET hash_password = ?, salt = ? WHERE email = ?",
                    (nuevo_h, nuevo_salt, u["email"]),
                )
    conn.commit()
    conn.close()


def _hash_dummy(password: str) -> None:
    """PBKDF2 con iteraciones reales para igualar el tiempo de respuesta
    cuando el usuario no existe (previene timing attacks)."""
    salt = "0" * 16
    hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), PBKDF2_ITERATIONS)


def verificar_credenciales(email: str, password: str) -> dict | None:
    """Verifica credenciales y devuelve el usuario si son válidas.

    El tiempo de respuesta es el mismo con o sin usuario en la BD
    (se ejecuta PBKDF2 en ambos casos) para evitar que un atacante
    determine la existencia de un email por el tiempo de respuesta.
    """
    conn = db.get_connection()
    row = dbutil.query(conn, 
        "SELECT * FROM usuarios WHERE email = ? AND activo = 1", (email,)
    ).fetchone()
    conn.close()
    if row is None:
        _hash_dummy(password)
        return None
    stored_hash = row["hash_password"]
    salt = row["salt"]
    if not _verificar_hash(password, stored_hash, salt):
        return None
    # La migración de hashes legacy se ejecuta una sola vez al inicio
    # (ver main.py / seed_usuarios), no en cada login.
    return {
        "id": row["id"],
        "email": row["email"],
        "nombre": row["nombre"],
        "rol": row["rol"],
        "password_changed_at": row["password_changed_at"],
        "totp_enabled": bool(row.get("totp_enabled", 0)),
        "totp_secret": row.get("totp_secret"),
    }


def generar_token(usuario: dict, empresa_id: int | None = None) -> str:
    """Genera un JWT para el usuario (expiración 60 min)."""
    # exp/iat como epoch UTC: son absolutos y no dependen de la zona horaria
    # del servidor que emite el token.
    exp = datetime.now(timezone.utc) + timedelta(minutes=TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": usuario["email"],
        "nombre": usuario["nombre"],
        "rol": usuario["rol"],
        "exp": int(exp.timestamp()),
        "iat": int(time.time()),
    }
    if empresa_id is not None:
        payload["empresa_id"] = empresa_id
    return jwt.encode(payload, SECRET_KEY, algorithm="HS256")


def _ahora_utc() -> datetime:
    """Instante actual en UTC, con granularidad de segundo.

    ``iat`` del JWT es un epoch entero (segundos), así que ``password_changed_at``
    se guarda también truncado al segundo: comparar un iat truncado contra un
    pcd con microsegundos invalidaba tokens emitidos justo después del cambio
    ("Token invalidado" con credenciales correctas).
    """
    return datetime.now(timezone.utc)


def _a_naive_utc(dt: datetime) -> datetime:
    """Normaliza a UTC naive para poder comparar fechas de fuentes distintas.

    ``password_changed_at`` es una columna TEXT: su formato depende de quién la
    escribió. ``cambiar_password`` guarda un string ISO naive, pero cualquier
    otro escritor (SQL ``now()``, otro cliente, una migración) deja un offset
    como ``-05``. Comparar eso contra ``datetime.fromtimestamp()`` (naive) lanza
    ``TypeError`` y el token se rechazaba con un 401 sin explicación.
    """
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def validar_token(token: str) -> dict:
    """Valida un JWT y devuelve su payload. Lanza jwt.InvalidTokenError si es inválido."""
    payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
    # Validar contra la BD
    conn = db.get_connection()
    row = dbutil.query(conn, 
        "SELECT password_changed_at FROM usuarios WHERE email = ?", (payload.get("sub"),)
    ).fetchone()
    conn.close()
    if row and row["password_changed_at"]:
        bruto = row["password_changed_at"]
        if isinstance(bruto, str):
            try:
                pcd = datetime.fromisoformat(bruto.strip().replace(" ", "T", 1))
            except ValueError:
                pcd = None
        elif isinstance(bruto, datetime):
            pcd = bruto
        else:
            pcd = None
        if pcd is not None:
            iat_dt = datetime.fromtimestamp(payload.get("iat", 0), timezone.utc).replace(tzinfo=None)
            # Ambas partes a granularidad de segundo (ver _ahora_utc).
            pcd_seg = _a_naive_utc(pcd).replace(microsecond=0)
            if iat_dt < pcd_seg:
                raise jwt.InvalidTokenError("Token invalidado: contraseña cambiada")
    return payload



def cambiar_password(usuario_id: int, new_password: str) -> dict:
    """Cambia la contraseña de un usuario e invalida sus tokens vigentes."""
    h, salt = hash_password(new_password)
    conn = db.get_connection()
    fila = dbutil.query(conn, "SELECT id FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()
    if fila is None:
        conn.close()
        raise ValueError("El usuario no existe")
    dbutil.query(conn, 
        "UPDATE usuarios SET hash_password = ?, salt = ?, password_changed_at = ? WHERE id = ?",
        # Se guarda un instante en el pasado para que el propio token de esta
        # operación no quede invalidado, y en ISO naive UTC (formato estable
        # para el campo TEXT, sin offset de zona horaria).
        (h, salt,
         _ahora_utc().replace(microsecond=0).isoformat(sep=" "),
         usuario_id),
    )
    conn.commit()
    conn.close()
    return {"ok": True}


def seed_usuarios() -> None:
    """Inserta usuarios iniciales si no existen (PBKDF2).

    Solo se crea admin@saluki.com. Los usuarios secundarios (contador,
    vendedor, almacenista) no se crean automáticamente: deben crearse
    manualmente vía la interfaz de administración.

    El usuario semilla se marca con ``password_changed_at = NULL`` únicamente
    en su **primer** arranque. En arranques posteriores se respeta la
    contraseña ya cambiada por el usuario: forzar el cambio en cada boot
    dejaba el sistema inutilizable y re-hasheaba la clave en cada inicio.
    """
    conn = db.get_connection()
    now = datetime.now().isoformat()
    emp_row = dbutil.query(conn, "SELECT id FROM empresas ORDER BY id LIMIT 1").fetchone()
    first_emp_id = emp_row["id"] if emp_row else None

    usuarios_seed = [
        {"email": "admin@sistema.com", "nombre": "Superadministrador de Plataforma", "rol": "SUPERADMIN", "password": "admin123", "empresa_id": None},
        {"email": "admin@saluki.com", "nombre": "Superadministrador de Sistema", "rol": "SUPERADMIN", "password": "admin123", "empresa_id": None},
        {"email": "gerente@empresa.com", "nombre": "Gerente General", "rol": "ADMIN_EMPRESA", "password": "Gerente123!", "empresa_id": first_emp_id},
    ]
    for u in usuarios_seed:
        row = dbutil.query(
            conn,
            "SELECT id FROM usuarios WHERE email = ?",
            (u["email"],),
        ).fetchone()
        if row is None:
            h, salt = hash_password(u["password"])
            cur = dbutil.query(conn, 
                "INSERT INTO usuarios (email, nombre, rol, hash_password, salt, activo, created_at, empresa_id) VALUES (?, ?, ?, ?, ?, 1, ?, ?) RETURNING id",
                (u["email"], u["nombre"], u["rol"], h, salt, now, u.get("empresa_id")),
            )
            new_uid = cur.fetchone()["id"]
            if u["email"] == "admin@saluki.com":
                dbutil.query(
                    conn,
                    "UPDATE usuarios SET password_changed_at = NULL WHERE email = ?",
                    (u["email"],),
                )
            if u.get("empresa_id"):
                try:
                    dbutil.query(
                        conn,
                        """INSERT INTO usuario_empresas (usuario_id, empresa_id, rol_en_empresa, es_predeterminada, created_at)
                           VALUES (?, ?, ?, 1, ?) ON CONFLICT DO NOTHING""",
                        (new_uid, u["empresa_id"], u["rol"], now),
                    )
                except Exception:
                    pass
        else:
            if u["email"] == "admin@saluki.com":
                dbutil.query(
                    conn,
                    "UPDATE usuarios SET rol = 'SUPERADMIN', nombre = 'Superadministrador de Sistema' WHERE email = ?",
                    (u["email"],),
                )
    conn.commit()
    conn.close()
    _migrar_hashes_legado()


# ============================================================================
# Autenticación Multifactor 2FA / TOTP (RFC 6238)
# ============================================================================

def generar_totp_secret() -> str:
    """Genera un secreto TOTP seguro de 160 bits codificado en Base32."""
    return base64.b32encode(secrets.token_bytes(20)).decode("utf-8").replace("=", "")


def generar_totp_uri(email: str, secret: str, issuer: str = "SAP Colombia ERP") -> str:
    """Construye la URI otpauth:// estándar compatible con Google Authenticator y Authy."""
    return f"otpauth://totp/{issuer}:{email}?secret={secret}&issuer={issuer}&algorithm=SHA1&digits=6&period=30"


def _calcular_totp(secret: str, interval: int) -> str:
    padding = "=" * ((8 - len(secret) % 8) % 8)
    key = base64.b32decode(secret + padding, casefold=True)
    msg = struct.pack(">Q", interval)
    h = hmac.new(key, msg, hashlib.sha1).digest()
    offset = h[-1] & 0x0F
    code = (struct.unpack(">I", h[offset:offset+4])[0] & 0x7FFFFFFF) % 1_000_000
    return f"{code:06d}"


def verificar_totp(secret: str, codigo: str, ventana: int = 1) -> bool:
    """Valida un token TOTP de 6 dígitos con ventana de tolerancia de ±30 segundos."""
    if not secret or not codigo:
        return False
    codigo_str = str(codigo).strip()
    if len(codigo_str) != 6 or not codigo_str.isdigit():
        return False

    ahora = int(time.time()) // 30
    for i in range(-ventana, ventana + 1):
        if _calcular_totp(secret, ahora + i) == codigo_str:
            return True
    return False


def habilitar_2fa(usuario_id: int, secret: str, codigo: str) -> bool:
    """Activa 2FA para el usuario si el código de verificación es válido."""
    if not verificar_totp(secret, codigo):
        return False

    conn = db.get_connection()
    try:
        dbutil.query(
            conn,
            "UPDATE usuarios SET totp_secret = ?, totp_enabled = 1 WHERE id = ?",
            (secret, usuario_id),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def deshabilitar_2fa(usuario_id: int) -> bool:
    """Desactiva 2FA para el usuario."""
    conn = db.get_connection()
    try:
        dbutil.query(
            conn,
            "UPDATE usuarios SET totp_secret = NULL, totp_enabled = 0 WHERE id = ?",
            (usuario_id,),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def obtener_estado_2fa(usuario_id: int) -> dict:
    conn = db.get_connection()
    try:
        row = dbutil.query(
            conn,
            "SELECT email, totp_enabled FROM usuarios WHERE id = ?",
            (usuario_id,),
        ).fetchone()
        if not row:
            return {"enabled": False}
        return {
            "email": row["email"],
            "enabled": bool(row.get("totp_enabled", 0)),
        }
    finally:
        conn.close()
