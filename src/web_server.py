"""Servidor Web y API REST para ERP SAP Colombia (Facturación Electrónica DIAN)."""

import json
from sap_colombia import dbutil
import mimetypes
import os
import posixpath
import sys
import threading
import time
import unicodedata
from decimal import Decimal
from http.server import ThreadingHTTPServer, HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse, parse_qs, unquote

# Asegurar path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(BASE_DIR)
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from sap_colombia import database as db
from sap_colombia import accounting_engine
from sap_colombia import accounts_receivable
from sap_colombia import credit_notes
from sap_colombia import support_document
from sap_colombia import inventory
from sap_colombia import payroll
from sap_colombia import exogena
from sap_colombia import exogena_flat
from sap_colombia import dashboard
from sap_colombia import excel_export
from sap_colombia import radian
from sap_colombia import debit_notes
from sap_colombia import pdf_generator
from sap_colombia import mail_notifier
from sap_colombia import massive_import
from sap_colombia import auth
from sap_colombia import period_control
from sap_colombia import rbac
from sap_colombia import numeracion
from sap_colombia import parametros
from sap_colombia import audit
from sap_colombia import admin
from sap_colombia import vendor_bills
from sap_colombia import accounts_payable
from sap_colombia import commercial_cycle
from sap_colombia import pos_system
from sap_colombia import price_lists
from sap_colombia import tax_forms
from sap_colombia.tax_engine import TaxEngine, LineaFactura
from sap_colombia.ubl_builder import Emisor, Adquirente, UblInvoiceBuilder
import logging

from sap_colombia.dian_client import DianClient
from sap_colombia.dian_factory import get_dian_client
from sap_colombia import config as sap_config
from sap_colombia.digital_signature import firmar_xml_ubl, ErrorFirma

STATIC_DIR = os.path.join(BASE_DIR, "static")
STATIC_DIR_REAL = os.path.realpath(STATIC_DIR)

# --- Limitación de intentos de inicio de sesión (anti fuerza bruta) ---
_LOGIN_ATTEMPT_DEFAULT = 5
_LOGIN_ATTEMPT_WINDOW_S = 300
_login_attempts: dict = {}
_login_lock = threading.Lock()


def _login_max_intentos() -> int:
    """Máximo de fallos permitidos por (IP, usuario) dentro de la ventana.

    Configurable con ``SAP_LOGIN_MAX_INTENTOS``. ``0`` desactiva el límite: en
    la suite de pruebas varios tests rotan la contraseña del mismo usuario
    administrador, y con el límite activo se produce el falso positivo de
    "demasiados intentos" que bloquea los logins legítimos posteriores.
    """
    try:
        return int(os.environ.get("SAP_LOGIN_MAX_INTENTOS", _LOGIN_ATTEMPT_DEFAULT))
    except ValueError:
        return _LOGIN_ATTEMPT_DEFAULT


def _login_rate_key(client_addr: str, email: str) -> str:
    return f"{client_addr}|{email.strip().lower()}"


def _login_bloqueado(clave: str) -> bool:
    maximo = _login_max_intentos()
    if maximo <= 0:
        return False
    ahora = time.monotonic()
    with _login_lock:
        intentos = [t for t in _login_attempts.get(clave, []) if ahora - t < _LOGIN_ATTEMPT_WINDOW_S]
        if intentos:
            _login_attempts[clave] = intentos
        return len(intentos) >= maximo


def _login_registrar_fallo(clave: str) -> None:
    if _login_max_intentos() <= 0:
        return
    ahora = time.monotonic()
    with _login_lock:
        intentos = [t for t in _login_attempts.get(clave, []) if ahora - t < _LOGIN_ATTEMPT_WINDOW_S]
        intentos.append(ahora)
        _login_attempts[clave] = intentos


def _login_limpiar(clave: str) -> None:
    with _login_lock:
        _login_attempts.pop(clave, None)


def resolver_static_path(path: str):
    """Resuelve una ruta solicitada dentro de ``static/``.

    Devuelve la ruta absoluta garantizada como contenida en el directorio
    estático, o ``None`` si la petición intenta escapar de ese directorio.

    ``self.path`` llega crudo y sin normalizar desde ``BaseHTTPRequestHandler``,
    por lo que ``/../secreto`` debe rechazarse explícitamente en lugar de
    confiar en ``os.path.join``.
    """
    rel = unquote(path or "")
    if "\\" in rel or "\x00" in rel:
        return None
    rel = unicodedata.normalize("NFC", rel).lstrip("/")
    if not rel or rel in (".", "./"):
        rel = "index.html"
    # posixpath.normpath colapsa "..", "." y barras duplicadas.
    rel = posixpath.normpath(rel)
    if rel == ".." or rel.startswith("../"):
        return None
    destino = os.path.realpath(os.path.join(STATIC_DIR_REAL, rel))
    if destino != STATIC_DIR_REAL and not destino.startswith(STATIC_DIR_REAL + os.sep):
        return None
    if os.path.commonpath([STATIC_DIR_REAL, destino]) != STATIC_DIR_REAL:
        return None
    if os.path.isdir(destino):
        idx = os.path.join(destino, "index.html")
        if os.path.isfile(idx):
            return idx
    return destino


def _firmar_xml(empresa: dict, xml: str) -> str:
    """Firma el XML UBL con XAdES-BES si hay certificado configurado."""
    ruta_cert = empresa.get("ruta_certificado") or ""
    password_cert = empresa.get("password_certificado") or ""
    if not ruta_cert:
        return xml
    try:
        return firmar_xml_ubl(xml, ruta_cert, password_cert)
    except ErrorFirma as e:
        logging.getLogger(__name__).error(
            "Error firmando XML UBL: %s", e
        )
        raise


class DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return str(obj)
        return super().default(obj)


def _pagina(query, defecto=1, defecto_limite=50, maximo=500):
    """Lee ``page``/``limit`` de forma tolerante y acotada.

    Antes se hacía ``int(query.get("page"))`` sin ``try``: un ``?page=abc``
    lanzaba ``ValueError`` fuera del handler y socketserver cerraba el socket
    sin responder nada. ``limit`` tampoco tenía tope superior.
    """
    def _entero(valor, por_defecto, tope):
        try:
            n = int(valor)
        except (TypeError, ValueError):
            return por_defecto
        return max(1, min(n, tope))

    page = _entero(query.get("page", [str(defecto)])[0], defecto, 1_000_000)
    limit = _entero(query.get("limit", [str(defecto_limite)])[0], defecto_limite, maximo)
    return page, limit


class SapWebHandler(BaseHTTPRequestHandler):
    def _set_headers(self, status=200, content_type="application/json", extra=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.send_header("Content-Security-Policy", (
            "default-src 'self'; script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
            "connect-src 'self'; frame-ancestors 'none'; base-uri 'self'"
        ))
        self.send_header("Access-Control-Allow-Origin", "null")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        if extra:
            for nombre, valor in extra.items():
                self.send_header(nombre, valor)
        self.end_headers()

    def do_OPTIONS(self):
        self._set_headers(204)

    def _send_json(self, data, status=200):
        body = json.dumps(data, cls=DecimalEncoder).encode("utf-8")
        self._set_headers(status, "application/json")
        self.wfile.write(body)

    def _send_error_json(self, message, status=400):
        self._send_json({"error": message}, status=status)

    def _send_bytes(self, data: bytes, nombre: str, formato: str):
        if formato == "xlsx":
            content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            ext = "xlsx"
        elif formato == "txt":
            content_type = "text/plain; charset=utf-8"
            ext = "txt"
        else:
            content_type = "text/csv; charset=utf-8"
            ext = "csv"
        safe_nombre = "".join(c for c in nombre if c.isalnum() or c in "-_")
        self._set_headers(200, content_type, extra={
            "Content-Disposition": (
                f"attachment; filename={safe_nombre}_"
                f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.{ext}"
            ),
            "Content-Length": str(len(data)),
        })
        self.wfile.write(data)

    def _require_auth(self):
        db.set_current_empresa_id(None)
        header = self.headers.get("Authorization", "")
        token = None
        if header.startswith("Bearer "):
            token = header.split("Bearer ", 1)[1].strip()
        else:
            parsed = urlparse(self.path)
            is_download = (
                parsed.path.endswith(("/xml", "/pdf", "/zip", "/exportar", "/plantilla"))
                or "/ticket/" in parsed.path
            )
            if is_download:
                q_token = parse_qs(parsed.query).get("token", [None])[0]
                if q_token:
                    token = q_token.strip()
                else:
                    cookie_hdr = self.headers.get("Cookie", "")
                    for part in cookie_hdr.split(";"):
                        if "=" in part:
                            k, v = part.strip().split("=", 1)
                            if k == "sap_token" and v:
                                token = v.strip()
                                break
        if not token or token in ("null", "undefined"):
            return None
        try:
            user = auth.validar_token(token)
            # El id de base de datos es necesario para autorizaciones propias
            if "id" not in user:
                conn = db.get_connection()
                row = dbutil.query(
                    conn, "SELECT id FROM usuarios WHERE email = ?", (user["sub"],)
                ).fetchone()
                conn.close()
                if row is None:
                    return None
                user["id"] = row["id"]

            # Contexto de Tenant: Prioridad cabecera X-Empresa-Id o token
            emp_id_hdr = self.headers.get("X-Empresa-Id")
            if emp_id_hdr and emp_id_hdr.strip().isdigit():
                requested_emp_id = int(emp_id_hdr.strip())
                allowed_empresas = admin.get_empresas_for_user(user["id"])
                if any(e["id"] == requested_emp_id for e in allowed_empresas):
                    db.set_current_empresa_id(requested_emp_id)
                    user["empresa_id"] = requested_emp_id
            elif "empresa_id" in user and user["empresa_id"]:
                db.set_current_empresa_id(user["empresa_id"])

            return user
        except Exception:
            return None

    def _require_role(self, *roles):
        user = self._require_auth()
        if user is None:
            self._send_error_json("No autenticado", 401)
            return None
        if user["rol"] not in roles:
            self._send_error_json("No autorizado", 403)
            return None
        # Look up user id from database by email (sub claim)
        conn = db.get_connection()
        row = dbutil.query(conn, "SELECT id FROM usuarios WHERE email = ?", (user["sub"],)).fetchone()
        conn.close()
        if row is None:
            self._send_error_json("Usuario no encontrado", 401)
            return None
        user["id"] = row["id"]
        return user

    def _do_login(self, payload=None):
        if payload is None:
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            try:
                payload = json.loads(body.decode("utf-8")) if body else {}
            except Exception:
                return self._send_error_json("JSON inválido", 400)
        email = payload.get("email", "")
        password = payload.get("password", "")
        if not email or not password:
            return self._send_error_json("Se requiere email y password", 400)
        rate_key = _login_rate_key(self.client_address[0], email)
        if _login_bloqueado(rate_key):
            audit.log_evento(None, email, "LOGIN_BLOQUEADO", "Rate limit excedido",
                             ip=self.client_address[0])
            return self._send_error_json(
                "Demasiados intentos fallidos. Espere 5 minutos.", 429)
        user = auth.verificar_credenciales(email, password)
        if user is None:
            _login_registrar_fallo(rate_key)
            audit.log_evento(None, email, "LOGIN_FALLIDO", "Credenciales inválidas",
                             ip=self.client_address[0])
            return self._send_error_json("Credenciales inválidas", 401)
        _login_limpiar(rate_key)

        # Verificación 2FA si está habilitado
        if user.get("totp_enabled"):
            totp_code = payload.get("totp_code")
            if not totp_code:
                return self._send_json({
                    "requiere_2fa": True,
                    "email": email,
                    "mensaje": "Se requiere código de verificación 2FA / TOTP",
                })
            if not auth.verificar_totp(user.get("totp_secret", ""), totp_code):
                audit.log_evento(user.get("id"), email, "LOGIN_2FA_FALLIDO", "Código TOTP inválido",
                                 ip=self.client_address[0])
                return self._send_error_json("Código 2FA / TOTP inválido", 401)
        # El tenant del usuario es SU empresa; nunca la primera de la lista.
        conn = db.get_connection()
        row = dbutil.query(
            conn,
            "SELECT id, empresa_id FROM usuarios WHERE email = ?",
            (email,),
        ).fetchone()
        conn.close()
        if row is None:
            return self._send_error_json("Usuario no encontrado", 401)
        empresa_id = row["empresa_id"]
        token = auth.generar_token(user, empresa_id)
        audit.log_evento(row["id"], email, "LOGIN_OK", None,
                         ip=self.client_address[0])
        return self._send_json({
            "token": token,
            "rol": user["rol"],
            "nombre": user["nombre"],
            "password_changed_at": user["password_changed_at"],
        })

    def _do_crear_usuario(self, payload):
        email = payload.get("email", "")
        nombre = payload.get("nombre", "")
        rol = payload.get("rol", "")
        password = payload.get("password", "")
        if not email or not password:
            return self._send_error_json("Se requieren email y password", 400)
        ok, msg = auth.validar_fuerteza_password(password)
        if not ok:
            return self._send_error_json(msg, 400)
        roles_validos = set(rbac.roles_existentes())
        if rol not in roles_validos:
            return self._send_error_json(
                f"Rol inválido. Roles definidos: {', '.join(sorted(roles_validos)) or '(ninguno)'}", 400)
        conn = db.get_connection()
        exists = dbutil.query(conn, "SELECT 1 FROM usuarios WHERE email = ?", (email,)).fetchone()
        conn.close()
        if exists:
            return self._send_error_json("El email ya existe", 409)
        h, salt = auth.hash_password(password)
        conn = db.get_connection()
        now = datetime.now().isoformat()
        dbutil.query(conn, 
            "INSERT INTO usuarios (email, nombre, rol, hash_password, salt, activo, created_at) VALUES (?, ?, ?, ?, ?, 1, ?)",
            (email, nombre, rol, h, salt, now),
        )
        conn.commit()
        conn.close()
        return self._send_json({"ok": True, "email": email})

    def _do_cambiar_password(self, payload, path=None, caller=None):
        """Cambia la contraseña del llamador, o la de otro usuario si es admin.

        Nunca se permite cambiar la contraseña de un tercero sin rol
        administrativo: sin esta comprobación, cualquierTitular de
        ``usuarios:update`` podía restablecer la clave del ADMIN.
        """
        usuario_id = payload.get("usuario_id")
        new_password = payload.get("password", payload.get("new_password", ""))
        if path and path.startswith("/api/usuarios/") and path.endswith("/password"):
            uid = path.split("/")[3]
            if uid.isdigit():
                usuario_id = uid
        if not new_password:
            return self._send_error_json("Se requiere password", 400)
        ok, msg = auth.validar_fuerteza_password(new_password)
        if not ok:
            return self._send_error_json(msg, 400)

        caller = caller or self._require_auth()
        if caller is None:
            return self._send_error_json("No autenticado", 401)

        es_admin = caller.get("rol") in ("ADMIN", "SUPERADMIN")
        if usuario_id is None or str(usuario_id) == str(caller.get("id")):
            objetivo = caller.get("id")
        elif es_admin:
            objetivo = int(usuario_id)
        else:
            return self._send_error_json(
                "Solo un administrador puede cambiar la contraseña de otro usuario", 403)

        if objetivo is None:
            return self._send_error_json("No autenticado", 401)
        try:
            resultado = auth.cambiar_password(int(objetivo), new_password)
        except ValueError as e:
            return self._send_error_json(str(e), 400)
        if not resultado.get("ok"):
            return self._send_error_json("No se pudo cambiar la contraseña", 400)
        audit.log_evento(caller.get("id"), caller.get("sub"),
                         "PASSWORD_CAMBIADA", f"usuario_id={objetivo}")
        return self._send_json(resultado)

    def _do_crear_rol(self, payload):
        nombre = payload.get("nombre", "")
        descripcion = payload.get("descripcion", "")
        conn = db.get_connection()
        exists = dbutil.query(conn, "SELECT 1 FROM roles WHERE nombre = ?", (nombre,)).fetchone()
        conn.close()
        if exists:
            return self._send_error_json("El rol ya existe", 409)
        conn = db.get_connection()
        now = datetime.now().isoformat()
        dbutil.query(conn, 
            "INSERT INTO roles (nombre, descripcion, activo, created_at) VALUES (?, ?, 1, ?)",
            (nombre, descripcion, now),
        )
        conn.commit()
        conn.close()
        return self._send_json({"ok": True, "nombre": nombre})

    def _do_roles_permisos(self, payload):
        rol = payload.get("rol", "")
        permisos = payload.get("permisos", [])
        if not rol:
            return self._send_error_json("Se requiere rol", 400)
        conn = db.get_connection()
        role = dbutil.query(conn, "SELECT * FROM roles WHERE nombre = ?", (rol,)).fetchone()
        if role is None:
            conn.close()
            return self._send_error_json("Rol no encontrado", 404)
        permisos_db = {row["recurso"] + ":" + row["accion"]: row["id"]
                       for row in dbutil.query(conn, "SELECT * FROM permisos").fetchall()}
        dbutil.query(conn, "DELETE FROM role_permissions WHERE role_id = ?", (role["id"],))
        for p in permisos:
            if p in permisos_db:
                dbutil.query(conn, 
                    "INSERT INTO role_permissions (role_id, permission_id) VALUES (?, ?)",
                    (role["id"], permisos_db[p]),
                )
        conn.commit()
        conn.close()
        return self._send_json({"ok": True})

    def _do_me(self):
        user = self._require_auth()
        if user is None:
            return self._send_error_json("No autenticado", 401)
        # Look up user ID from database
        conn = db.get_connection()
        row = dbutil.query(conn, 
            "SELECT id, activo, password_changed_at FROM usuarios WHERE email = ?", (user["sub"],)
        ).fetchone()
        conn.close()
        if row is None or not row["activo"]:
            return self._send_error_json("Usuario inactivo", 401)
        user["id"] = row["id"]
        conn = db.get_connection()
        try:
            perms = rbac.permisos_usuario(conn, user["id"])
        finally:
            conn.close()
        empresas = admin.get_empresas_for_user(user["id"])
        es_admin_sistema = user["rol"] in ("SUPERADMIN", "ADMIN_SISTEMA", "ADMIN")
        tipo_usuario = "SISTEMA" if (es_admin_sistema and not user.get("empresa_id")) else "EMPRESA"
        empresa_activa_id = db.get_current_empresa_id() or (empresas[0]["id"] if empresas else 1)
        recursos = {p.split(":")[0] for p in rbac.PERMISOS}
        permisos_tri_estado = {rec: rbac.resolver_permiso_tri_estado(perms, rec) for rec in recursos}
        conflictos_sod = rbac.analizar_conflictos_sod(perms)
        return self._send_json({
            "id": user["id"],
            "email": user["sub"],
            "nombre": user.get("nombre", ""),
            "rol": user["rol"],
            "es_admin_sistema": es_admin_sistema,
            "tipo_usuario": tipo_usuario,
            "empresas_autorizadas": empresas,
            "empresa_activa_id": empresa_activa_id,
            "permisos": sorted(perms),
            "permisos_tri_estado": permisos_tri_estado,
            "conflictos_sod": conflictos_sod,
            "password_changed_at": row["password_changed_at"],
        })

    def _require_permiso(self, permiso: str):
        """Default-deny: valida token + permiso RBAC. Devuelve user o None (ya respondió error)."""
        user = self._require_auth()
        if user is None:
            self._send_error_json("No autenticado", 401)
            return None
        if permiso == "__none__":
            self._send_error_json("No autorizado", 403)
            return None
        conn = db.get_connection()
        row = dbutil.query(conn, 
            "SELECT id, activo FROM usuarios WHERE email = ?", (user["sub"],)
        ).fetchone()
        conn.close()
        if row is None or not row["activo"]:
            self._send_error_json("Usuario inactivo", 401)
            return None
        user["id"] = row["id"]
        conn = db.get_connection()
        try:
            if not rbac.usuario_tiene_permiso(conn, row["id"], permiso):
                self._send_error_json("No autorizado", 403)
                return None
        finally:
            conn.close()
        return user

    # Default-deny: permisos mínimos para lectura (todo /api/* requiere token)
    # Default-deny: permisos mínimos por recurso (todo /api/* requiere token)
    _PERMISOS_GET = {
        "/api/empresa": "empresa:read",
        "/api/clientes": "clientes:read",
        "/api/productos": "productos:read",
        "/api/facturas": "facturacion:read",
        "/api/contabilidad/cuentas": "contabilidad:read",
        "/api/contabilidad/asientos": "contabilidad:read",
        "/api/contabilidad/balance": "contabilidad:read",
        "/api/notas-credito": "notas_credito:read",
        "/api/notas-debito": "notas_debito:read",
        "/api/cartera/edades": "cartera:read",
        "/api/cartera/recibos": "cartera:read",
        "/api/documento-soporte": "documento_soporte:read",
        "/api/inventario/kardex": "inventario:read",
        "/api/inventario/stock": "inventario:read",
        "/api/dashboard/kpis": "dashboard:read",
        "/api/nomina/empleados": "nominas:read",
        "/api/nomina/historial": "nominas:read",
        "/api/empleados": "nominas:read",
        "/api/exogena/formato-1001": "exogena:read",
        "/api/exogena/formato-2275": "exogena:read",
        "/api/exogena/formato-2276": "exogena:read",
        "/api/exogena/formato-1007": "exogena:read",
        "/api/exogena/formato-1003": "exogena:read",
        "/api/exogena/certificado-retencion": "exogena:read",
        "/api/reportes/cartera/exportar": "cartera:read",
        "/api/reportes/libro-diario/exportar": "contabilidad:read",
        "/api/reportes/kardex/exportar": "inventario:read",
        "/api/periodos": "periodos:read",
        "/api/roles": "roles:read",
        "/api/permisos": "permisos:read",
        "/api/permisos/por-recurso": "permisos:read",
        "/api/permisos/recurso/facturacion": "permisos:read",
        "/api/usuarios": "usuarios:read",
        "/api/auditoria": "auditoria:read",
        "/api/radian/eventos": "radian:read",
        "/api/importaciones/plantilla": "importaciones:read",
        "/api/admin/empresas": "empresas:read",
        "/api/admin/usuarios": "usuarios_sistema:read",
        "/api/admin/roles": "roles_empresa:read",
        "/api/admin/usuario-empresas": "usuarios_sistema:read",
        "/api/compras/facturas": "compras:read",
        "/api/cxp/cuentas": "cxp:read",
        "/api/cxp/edades": "cxp:read",
        "/api/cxp/egresos": "cxp:read",
        "/api/ventas/cotizaciones": "ventas:read",
        "/api/ventas/pedidos": "ventas:read",
        "/api/ventas/remisiones": "ventas:read",
        "/api/pos/cajas": "pos:read",
        "/api/pos/sesiones": "pos:read",
        "/api/listas-precios": "precios:read",
        "/api/impuestos/formulario-300": "impuestos:read",
        "/api/impuestos/formulario-350": "impuestos:read",
    }
    _PERMISOS_POST = {
        "/api/periodos/cerrar": "periodos:cerrar",
        "/api/periodos/reabrir": "periodos:reabrir",
        "/api/liquidar": "facturacion:create",
        "/api/emitir": "facturacion:create",
        "/api/notas-credito/crear": "notas_credito:create",
        "/api/cartera/recaudar": "cartera:create",
        "/api/documento-soporte/crear": "documento_soporte:create",
        "/api/nomina/liquidar": "nominas:create",
        "/api/nomina/emitir": "nominas:create",
        "/api/nomina/pagar": "nominas:create",
        "/api/nomina/pagar-todos": "nominas:create",
        "/api/empleados": "nominas:create",
        "/api/nomina/empleados": "nominas:create",
        "/api/radian/evento": "radian:create",
        "/api/notas-debito/crear": "notas_debito:create",
        "/api/importaciones/facturas": "importaciones:create",
        "/api/importaciones/saldos-iniciales": "importaciones:create",
        "/api/importaciones/saldos_iniciales": "importaciones:create",
        "/api/importaciones/toma-inventario": "importaciones:create",
        "/api/importaciones/toma_inventario": "importaciones:create",
        "/api/facturas/enviar-correo": "facturacion:update",
        "/api/usuarios": "usuarios:create",
        "/api/usuarios/cambiar-password": "usuarios:update",
        "/api/roles": "roles:create",
        "/api/roles/permisos": "roles:update",
        "/api/admin/empresas": "empresas:create",
        "/api/admin/usuarios": "usuarios_sistema:create",
        "/api/admin/roles": "roles_empresa:create",
        "/api/admin/usuario-empresas": "usuarios_sistema:create",
        "/api/compras/procesar-xml": "compras:create",
        "/api/compras/radian-evento": "compras:create",
        "/api/cxp/egreso": "cxp:create",
        "/api/ventas/cotizaciones": "ventas:create",
        "/api/pos/cajas": "pos:create",
        "/api/pos/abrir-caja": "pos:create",
        "/api/pos/cerrar-caja": "pos:create",
        "/api/listas-precios": "precios:create",
        "/api/inventario/traslados": "inventario:update",
    }

    def _permiso_para(self, path, metodo="GET"):
        # DELETE exige explícitamente el permiso ":delete". Antes caía en
        # ":update", de modo que un rol con lectura+actualización y sin
        # ":delete" explícito todavía podía eliminar registros.
        if metodo == "DELETE":
            if path.startswith("/api/admin/empresas/"):
                return "empresas:delete"
            if path.startswith("/api/admin/usuarios/"):
                return "usuarios_sistema:delete"
            if path.startswith("/api/admin/roles/"):
                return "roles_empresa:delete"
            if path == "/api/admin/usuario-empresas":
                return "usuarios_sistema:delete"
            if path.startswith("/api/clientes/"):
                return "clientes:delete"
            if path.startswith("/api/productos/"):
                return "productos:delete"
            return None
        if metodo == "PUT":
            if path.startswith("/api/admin/empresas/"):
                return "empresas:update"
            if path.startswith("/api/admin/usuarios/"):
                return "usuarios_sistema:update"
            if path.startswith("/api/admin/roles/"):
                return "roles_empresa:update"
            if path.startswith("/api/clientes/"):
                return "clientes:update"
            if path.startswith("/api/productos/"):
                return "productos:update"
            if path.startswith(("/api/empleados/", "/api/nomina/empleados/")):
                return "nominas:create"
            return None
        if path.startswith("/api/admin/empresas/") and path.split("/")[-1].isdigit():
            return "empresas:update"
        if path.startswith("/api/admin/usuarios/") and path.split("/")[-1].isdigit():
            return "usuarios_sistema:update"
        if path.startswith("/api/admin/roles/") and path.endswith("/permisos"):
            return "roles_empresa:update"
        if path.startswith("/api/admin/roles/") and path.split("/")[-1].isdigit():
            return "roles_empresa:update"
        # Facturas específicas (id) y sus recursos
        if path.startswith("/api/facturas/") and path.endswith(("/xml", "/pdf", "/zip")):
            return "facturacion:read"
        if path.startswith("/api/facturas/") and path.split("/")[-1].isdigit():
            return "facturacion:read"
        if path.startswith("/api/usuarios/") and path.endswith("/password"):
            return "usuarios:update"
        # Nuevos módulos
        if path.startswith("/api/pos/ticket/"):
            return "pos:read"
        if path.startswith("/api/listas-precios/") and path.endswith("/precios"):
            return "precios:read" if metodo == "GET" else "precios:create"
        if path.startswith("/api/ventas/cotizaciones/") and path.endswith("/convertir-pedido"):
            return "ventas:create"
        if path.startswith("/api/ventas/cotizaciones/") and path.endswith("/aprobar"):
            return "ventas:update"
        if path.startswith("/api/ventas/pedidos/") and path.endswith("/convertir-remision"):
            return "ventas:create"
        if path.startswith("/api/ventas/pedidos/") and path.endswith("/convertir-factura"):
            return "ventas:create"
        return None

    def _enforce(self, path, permisos_map, metodo="GET"):
        """Devuelve user si autorizado; si no, responde 401/403 y devuelve None."""
        if path in permisos_map:
            return self._require_permiso(permisos_map[path])
        permiso = self._permiso_para(path, metodo)
        if permiso:
            return self._require_permiso(permiso)
        return self._require_permiso("__none__")  # default-deny -> 403 (o 401)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        # === Auth (público: login) ===
        if path == "/api/auth/login":
            return self._do_login()

        # === Default-deny: todo lo demás bajo /api/* requiere token + permiso ===
        if path.startswith("/api/"):
            if path == "/api/auth/me":
                return self._do_me()
            if path == "/api/auth/empresas":
                user = self._require_auth()
                if user is None:
                    return self._send_error_json("No autenticado", 401)
                empresas = admin.get_empresas_for_user(user["id"])
                return self._send_json(empresas)
            if path == "/api/sistema/periodo-contexto":
                user = self._require_auth()
                if user is None:
                    return self._send_error_json("No autenticado", 401)
                periodo_info = period_control.get_periodo_actual()
                abierto = periodo_info.get("estado") == "ABIERTO"
                return self._send_json({
                    "periodo": periodo_info.get("periodo"),
                    "estado": periodo_info.get("estado", "ABIERTO"),
                    "abierto": abierto,
                    "mensaje": f"Periodo Fiscal {periodo_info.get('periodo')} {'Abierto para Operaciones' if abierto else 'Cerrado'}"
                })
            if path == "/api/rbac/sod-matriz":
                user = self._require_auth()
                if user is None:
                    return self._send_error_json("No autenticado", 401)
                return self._send_json({
                    "conflictos": rbac.catalogo_conflictos_sod()
                })
            user = self._enforce(path, self._PERMISOS_GET)
            if user is None:
                return

        # Rutas API
        if path == "/api/empresa":
            empresa = dict(db.get_empresa() or {})
            empresa["dian_mode"] = config.dian_mode()
            return self._send_json(empresa)

        if path == "/api/clientes":
            clientes = db.get_clientes()
            return self._send_json(clientes)

        if path == "/api/productos":
            productos = db.get_productos()
            return self._send_json(productos)

        if path == "/api/facturas":
            query = parse_qs(parsed.query)
            page, limit = _pagina(query, defecto_limite=1000)
            if page < 1:
                page = 1
            if limit < 1:
                limit = 50
            facturas = db.get_facturas_paginado(
                page=page,
                limit=limit,
                fecha_desde=query.get("fecha_desde", [None])[0],
                fecha_hasta=query.get("fecha_hasta", [None])[0],
                cliente_nit=query.get("cliente_nit", [None])[0],
                estado_cartera=query.get("estado_cartera", [None])[0],
            )
            return self._send_json(facturas)

        if path.startswith("/api/facturas/") and path.endswith("/xml"):
            try:
                fid = int(path.split("/")[3])
                factura = db.get_factura_by_id(fid)
                if not factura or not factura.get("xml_ubl"):
                    return self._send_error_json("XML no encontrado", 404)
                xml_data = factura["xml_ubl"].encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/xml; charset=utf-8")
                self.send_header("Content-Disposition", f"attachment; filename=factura_{factura.get('consecutivo', fid)}.xml")
                self.end_headers()
                self.wfile.write(xml_data)
                return
            except Exception as e:
                return self._send_error_json(str(e), 500)

        if path.startswith("/api/facturas/"):
            parts = [p for p in path.split("/") if p]
            # Solo responder JSON si es /api/facturas/<id> exacto (2 segmentos tras api)
            if len(parts) == 3 and parts[2].isdigit():
                try:
                    fid = int(parts[2])
                    factura = db.get_factura_by_id(fid)
                    if not factura:
                        return self._send_error_json("Factura no encontrada", 404)
                    return self._send_json(factura)
                except Exception as e:
                    return self._send_error_json(str(e), 500)

        if path == "/api/contabilidad/cuentas":
            return self._send_json(db.get_cuentas_puc())

        if path == "/api/contabilidad/asientos":
            query = parse_qs(parsed.query)
            page, limit = _pagina(query, defecto_limite=1000)
            if page < 1:
                page = 1
            if limit < 1:
                limit = 50
            asientos = db.get_asientos()
            total = len(asientos)
            offset = (page - 1) * limit
            data = asientos[offset : offset + limit]
            pages = (total + limit - 1) // limit if total else 0
            return self._send_json({"data": data, "total": total, "page": page, "limit": limit, "pages": pages})

        if path == "/api/contabilidad/balance":
            try:
                return self._send_json(accounting_engine.generar_balance_prueba())
            except Exception as e:
                return self._send_error_json(str(e), 500)

        if path == "/api/notas-credito":
            return self._send_json(db.get_notas_credito())

        if path == "/api/notas-debito":
            return self._send_json(db.get_notas_debito())

        if path == "/api/cartera/edades":
            try:
                reporte = accounts_receivable.calcular_edades_cartera()
                reporte["total"] = len(reporte.get("detalle", []))
                return self._send_json(reporte)
            except Exception as e:
                return self._send_error_json(str(e), 500)

        if path == "/api/cartera/recibos":
            return self._send_json(db.get_recibos_caja())

        if path == "/api/documento-soporte":
            return self._send_json(db.get_documentos_soporte())

        if path == "/api/inventario/kardex":
            return self._send_json(db.get_kardex())

        if path == "/api/inventario/stock":
            return self._send_json(db.get_stock_actual())

        if path == "/api/dashboard/kpis":
            try:
                return self._send_json(dashboard.calcular_kpis())
            except Exception as e:
                return self._send_error_json(str(e), 500)

        if path == "/api/nomina/empleados":
            return self._send_json(db.get_empleados())

        if path == "/api/empleados":
            return self._send_json(db.get_empleados())

        if path == "/api/nomina/historial":
            params = dict(p.split("=", 1) for p in parsed.query.split("&") if "=" in p)
            estado_pago = params.get("estado_pago")
            periodo_inicio = params.get("periodo_inicio")
            periodo_fin = params.get("periodo_fin")
            return self._send_json(db.get_nominas(estado_pago=estado_pago, periodo_inicio=periodo_inicio, periodo_fin=periodo_fin))

        if path.startswith("/api/exogena/formato-"):
            params = dict(p.split("=", 1) for p in parsed.query.split("&") if "=" in p)
            formato = path.rsplit("-", 1)[-1]
            try:
                ano = int(params.get("ano", datetime.now().year))
            except ValueError:
                return self._send_error_json("Año inválido", 400)
            empresa = db.get_empresa()
            if not empresa:
                return self._send_error_json("No hay empresa configurada", 400)
            nit = str(empresa.get("nit", ""))
            try:
                if params.get("descargar") in ("1", "true"):
                    contenido = exogena_flat.generar_archivo(formato, ano, nit)
                    nombre = exogena_flat.nombre_archivo_para(formato, ano, nit)
                    return self._send_bytes(
                        contenido.encode("utf-8"), nombre, "txt",
                    )
                contenido = exogena_flat.generar_archivo(formato, ano, nit)
                nombre = exogena_flat.nombre_archivo_para(formato, ano, nit)
                lineas = contenido.strip().splitlines()
                return self._send_json({
                    "ano": ano,
                    "formato": formato,
                    "nombre_archivo": nombre,
                    "delimitador": exogena_flat.DELIMITADOR,
                    "encabezado": lineas[0] if lineas else "",
                    "registros": lineas[1:],
                    "total_registros": max(0, len(lineas) - 1),
                })
            except exogena_flat.ErrorExogena as e:
                return self._send_error_json(str(e), 400)
            except Exception as e:
                return self._send_error_json(str(e), 500)

        if path == "/api/exogena/certificado-retencion":
            params = dict(p.split("=") for p in parsed.query.split("&") if "=" in p)
            tercero_nit = params.get("tercero_nit", "")
            ano = params.get("ano", str(datetime.now().year))
            if not tercero_nit:
                return self._send_error_json("Se requiere tercero_nit", 400)
            try:
                cert = exogena.generar_certificado_retencion(tercero_nit, int(ano))
                xml = exogena.construir_xml_certificado(cert)
                return self._send_json({
                    "certificado": cert,
                    "xml": xml,
                })
            except Exception as e:
                return self._send_error_json(str(e), 500)

        if path.startswith("/api/radian/eventos"):
            fid = None
            if path.startswith("/api/radian/eventos/"):
                try:
                    fid = int(path.split("/")[4])
                except (IndexError, ValueError):
                    pass
            if not fid:
                params = parse_qs(parsed.query)
                fid = params.get("factura_id", [None])[0]
                fid = int(fid) if fid else None
            if not fid:
                return self._send_error_json("Se requiere factura_id", 400)
            eventos = radian.obtener_eventos_factura(int(fid))
            return self._send_json({"eventos": eventos})

        # === PDF / ZIP / Email endpoints ===
        if path.startswith("/api/facturas/") and path.endswith("/pdf"):
            fid = int(path.split("/")[3])
            factura = db.get_factura_by_id(fid)
            if not factura:
                return self._send_error_json("Factura no encontrada", 404)
            empresa = db.get_empresa() or {}
            cliente = None
            for c in db.get_clientes():
                if c["nit"] == factura.get("cliente_nit"):
                    cliente = c
                    break
            lineas = factura.get("lineas", [])
            pdf_bytes = pdf_generator.generar_pdf_documento(
                tipo="FACTURA",
                documento=factura,
                empresa=empresa,
                cliente=cliente,
            )
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Disposition", f"attachment; filename=factura_{factura.get('consecutivo', fid)}.pdf")
            self.end_headers()
            self.wfile.write(pdf_bytes)
            return

        if path.startswith("/api/facturas/") and path.endswith("/zip"):
            fid = int(path.split("/")[3])
            factura = db.get_factura_by_id(fid)
            if not factura:
                return self._send_error_json("Factura no encontrada", 404)
            empresa = db.get_empresa() or {}
            cliente = None
            for c in db.get_clientes():
                if c["nit"] == factura.get("cliente_nit"):
                    cliente = c
                    break
            pdf_bytes = pdf_generator.generar_pdf_documento(
                tipo="FACTURA",
                documento=factura,
                empresa=empresa,
                cliente=cliente,
            )
            zip_bytes = mail_notifier.generar_zip_factura(
                factura_id=fid,
                consecutivo=factura.get("consecutivo", str(fid)),
                cufe=factura.get("cufe", ""),
                pdf_bytes=pdf_bytes,
            )
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Disposition", f"attachment; filename=factura_{factura.get('consecutivo', fid)}_package.zip")
            self.end_headers()
            self.wfile.write(zip_bytes)
            return

        # === Exportación de reportes ===
        if path == "/api/reportes/cartera/exportar":
            params = parse_qs(parsed.query)
            formato = params.get("formato", ["csv"])[0].lower()
            try:
                rows = accounts_receivable.calcular_edades_cartera()["detalle"]
                data = excel_export.exportar(
                    formato,
                    ["cliente_nit", "saldo_pendiente", "fecha_vencimiento", "dias_vencimiento", "categoria"],
                    rows,
                    ["Cliente", "Saldo Pendiente", "Fecha Vencimiento", "Días Vencimiento", "Categoría"],
                    "Cartera",
                )
                return self._send_bytes(data, "cartera", formato)
            except excel_export.ExportError as e:
                return self._send_error_json(str(e), 400)
            except Exception as e:
                return self._send_error_json(str(e), 500)

        if path == "/api/reportes/libro-diario/exportar":
            params = parse_qs(parsed.query)
            formato = params.get("formato", ["csv"])[0].lower()
            try:
                asientos = db.get_asientos()
                rows = []
                for asiento in asientos:
                    for mov in asiento.get("movimientos", []):
                        rows.append(
                            {
                                "fecha": asiento.get("fecha"),
                                "numero_comprobante": asiento.get("numero_comprobante"),
                                "cuenta_codigo": mov.get("cuenta_codigo"),
                                "cuenta_nombre": mov.get("cuenta_nombre"),
                                "tercero_nombre": mov.get("tercero_nombre"),
                                "concepto": mov.get("concepto"),
                                "debito": mov.get("debito"),
                                "credito": mov.get("credito"),
                            }
                        )
                data = excel_export.exportar(
                    formato,
                    ["fecha", "numero_comprobante", "cuenta_codigo", "cuenta_nombre", "tercero_nombre", "concepto", "debito", "credito"],
                    rows,
                    ["Fecha", "Comprobante", "Cuenta", "Nombre Cuenta", "Tercero", "Concepto", "Débito", "Crédito"],
                    "Libro Diario",
                )
                return self._send_bytes(data, "libro-diario", formato)
            except excel_export.ExportError as e:
                return self._send_error_json(str(e), 400)
            except Exception as e:
                return self._send_error_json(str(e), 500)

        if path == "/api/reportes/kardex/exportar":
            params = parse_qs(parsed.query)
            formato = params.get("formato", ["csv"])[0].lower()
            try:
                rows = db.get_kardex()
                data = excel_export.exportar(
                    formato,
                    ["fecha", "producto_codigo", "bodega_codigo", "tipo_movimiento", "referencia_documento", "cantidad_entrada", "cantidad_salida", "saldo_cantidad", "costo_unitario", "costo_total_saldo"],
                    rows,
                    ["Fecha", "Producto", "Bodega", "Tipo Movimiento", "Documento", "Entrada", "Salida", "Saldo", "Costo Unitario", "Costo Total Saldo"],
                    "Kárdex",
                )
                return self._send_bytes(data, "kardex", formato)
            except excel_export.ExportError as e:
                return self._send_error_json(str(e), 400)
            except Exception as e:
                return self._send_error_json(str(e), 500)

        # === Importaciones Masivas ===
        if path == "/api/importaciones/plantilla":
            params = parse_qs(parsed.query)
            tipo = params.get("tipo", ["facturas"])[0].lower().replace("-", "_")
            formato = params.get("formato", ["csv"])[0].lower()
            try:
                if tipo == "facturas":
                    data = massive_import.plantilla_facturas(formato)
                    nombre = "plantilla_facturas"
                elif tipo == "saldos_iniciales":
                    data = massive_import.plantilla_saldos_iniciales(formato)
                    nombre = "plantilla_saldos_iniciales"
                elif tipo == "toma_inventario":
                    data = massive_import.plantilla_toma_inventario(formato)
                    nombre = "plantilla_toma_inventario"
                else:
                    return self._send_error_json("Tipo de plantilla inválido", 400)
                return self._send_bytes(data, nombre, formato)
            except Exception as e:
                return self._send_error_json(str(e), 400)

        # === Periodo Endpoints ===
        if path == "/api/periodos":
            periodo = period_control.get_periodo_actual()
            return self._send_json(periodo)

        # === System Admin: Empresas ===
        if path == "/api/admin/empresas":
            return self._send_json(admin.get_empresas_summary())

        if path.startswith("/api/admin/empresas/"):
            parts = path.split("/")
            if len(parts) == 4 and parts[3].isdigit():
                emp = admin.get_empresa(int(parts[3]))
                if emp is None:
                    return self._send_error_json("Empresa no encontrada", 404)
                return self._send_json(emp)

        # === System Admin: Usuarios ===
        if path == "/api/admin/usuarios":
            return self._send_json(admin.get_system_users())

        if path.startswith("/api/admin/usuarios/"):
            parts = path.split("/")
            if len(parts) == 4 and parts[3].isdigit():
                u = admin.get_system_user(int(parts[3]))
                if u is None:
                    return self._send_error_json("Usuario no encontrado", 404)
                return self._send_json(u)

        # === System Admin: Roles ===
        if path == "/api/admin/roles":
            return self._send_json(admin.get_roles())

        if path.startswith("/api/admin/roles/") and path.endswith("/permisos"):
            role_id = int(path.split("/")[-2])
            role = admin.get_role(role_id)
            if role is None:
                return self._send_error_json("Rol no encontrado", 404)
            return self._send_json({"role_id": role_id, "permisos": admin.get_role_permissions(role_id)})

        if path.startswith("/api/admin/roles/") and path.split("/")[-1].isdigit():
            role_id = int(path.split("/")[-1])
            role = admin.get_role(role_id)
            if role is None:
                return self._send_error_json("Rol no encontrado", 404)
            return self._send_json(role)

        # === System Admin: Mapeo Usuario - Empresas ===
        if path == "/api/admin/usuario-empresas":
            query = parse_qs(parsed.query)
            usuario_id = query.get("usuario_id", [None])[0]
            if usuario_id and usuario_id.isdigit():
                return self._send_json(admin.get_empresas_for_user(int(usuario_id)))
            return self._send_json(admin.get_user_empresas_mapping())

        # === RBAC / Administración ===
        if path.startswith("/api/permisos/recurso/"):
            recurso = path.split("/")[4]
            perms = rbac.permisos_por_recurso(recurso)
            return self._send_json({"recurso": recurso, "permisos": perms,
                                    "read": f"{recurso}:read" in perms})

        if path == "/api/roles":
            conn = db.get_connection()
            roles = [dict(r) for r in dbutil.query(conn, "SELECT * FROM roles ORDER BY nombre").fetchall()]
            conn.close()
            return self._send_json(roles)

        if path == "/api/permisos":
            return self._send_json({"permisos": rbac.permisos_catalogo()})

        if path == "/api/permisos/por-recurso" or path.startswith("/api/permisos/recurso/"):
            recurso = None
            if path.startswith("/api/permisos/recurso/"):
                recurso = path.split("/")[4]
            else:
                recurso = parse_qs(parsed.query).get("recurso", [None])[0]
            if not recurso:
                return self._send_error_json("Se requiere recurso", 400)
            perms = rbac.permisos_por_recurso(recurso)
            return self._send_json({"recurso": recurso, "permisos": perms,
                                    "read": f"{recurso}:read" in perms})

        if path == "/api/usuarios":
            conn = db.get_connection()
            usuarios = [
                {k: r[k] for k in ("id", "email", "nombre", "rol", "activo", "created_at")}
                for r in dbutil.query(conn, "SELECT * FROM usuarios ORDER BY email").fetchall()
            ]
            conn.close()
            return self._send_json(usuarios)

        if path == "/api/auditoria":
            return self._send_json(audit.obtener_eventos())

        # === 2FA Status ===
        if path == "/api/auth/2fa/status":
            user = self._require_auth()
            if user is None:
                return self._send_error_json("No autenticado", 401)
            return self._send_json(auth.obtener_estado_2fa(user["id"]))

        # === Compras y Proveedores ===
        if path == "/api/compras/facturas":
            return self._send_json(vendor_bills.listar_facturas_compra())

        # === Cuentas por Pagar (CxP) ===
        if path == "/api/cxp/cuentas":
            params = parse_qs(parsed.query)
            solo_pendientes = params.get("pendientes", ["false"])[0].lower() in ("true", "1")
            return self._send_json(accounts_payable.listar_cuentas_por_pagar(solo_pendientes=solo_pendientes))

        if path == "/api/cxp/edades":
            return self._send_json(accounts_payable.obtener_edades_cxp())

        if path == "/api/cxp/egresos":
            return self._send_json(accounts_payable.listar_comprobantes_egreso())

        # === Ciclo Comercial (Ventas) ===
        if path == "/api/ventas/cotizaciones":
            uid = user["id"] if (user and user.get("rol") == "VENDEDOR") else None
            return self._send_json(commercial_cycle.listar_cotizaciones(usuario_id=uid))

        if path == "/api/ventas/pedidos":
            uid = user["id"] if (user and user.get("rol") == "VENDEDOR") else None
            return self._send_json(commercial_cycle.listar_pedidos(usuario_id=uid))

        if path == "/api/ventas/remisiones":
            return self._send_json(commercial_cycle.listar_remisiones())

        # === POS Electrónico ===
        if path == "/api/pos/cajas":
            return self._send_json(pos_system.listar_cajas())

        if path == "/api/pos/sesiones":
            params = parse_qs(parsed.query)
            caja_id = params.get("caja_id", [None])[0]
            caja_id = int(caja_id) if caja_id else None
            return self._send_json(pos_system.listar_sesiones_caja(caja_id=caja_id))

        if path.startswith("/api/pos/ticket/"):
            try:
                fid = int(path.split("/")[4])
                ancho = int(parse_qs(parsed.query).get("ancho", [80])[0])
                ticket = pos_system.generar_ticket_pos(fid, ancho_mm=ancho)
                return self._send_json(ticket)
            except Exception as e:
                return self._send_error_json(str(e), 400)

        # === Listas de Precios ===
        if path == "/api/listas-precios":
            return self._send_json(price_lists.listar_listas_precios())

        if path.startswith("/api/listas-precios/") and path.endswith("/precios"):
            try:
                lid = int(path.split("/")[3])
                return self._send_json(price_lists.listar_precios_lista(lid))
            except Exception as e:
                return self._send_error_json(str(e), 400)

        # === Formularios Tributarios Oficiales DIAN ===
        if path == "/api/impuestos/formulario-300":
            params = parse_qs(parsed.query)
            bimestre = int(params.get("bimestre", [1])[0])
            anio = int(params.get("anio", [datetime.now().year])[0])
            try:
                return self._send_json(tax_forms.generar_formulario_300(bimestre, anio))
            except Exception as e:
                return self._send_error_json(str(e), 400)

        if path == "/api/impuestos/formulario-350":
            params = parse_qs(parsed.query)
            mes = int(params.get("mes", [datetime.now().month])[0])
            anio = int(params.get("anio", [datetime.now().year])[0])
            try:
                return self._send_json(tax_forms.generar_formulario_350(mes, anio))
            except Exception as e:
                return self._send_error_json(str(e), 400)

        # Servir Archivos Estáticos (contenidos estrictamente dentro de static/)
        file_path = resolver_static_path(path)
        if file_path is None:
            return self._send_error_json("Recurso no encontrado", 404)

        if os.path.isfile(file_path):
            ctype, _ = mimetypes.guess_type(file_path)
            ctype = ctype or "application/octet-stream"
            try:
                with open(file_path, "rb") as f:
                    content = f.read()
                self._set_headers(200, ctype, extra={"Content-Length": str(len(content))})
                self.wfile.write(content)
                return
            except Exception as e:
                return self._send_error_json(str(e), 500)

        self._send_error_json("Recurso no encontrado", 404)

    def do_PUT(self):
        parsed = urlparse(self.path)
        path = parsed.path
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)
        try:
            payload = json.loads(body.decode("utf-8")) if body else {}
        except Exception:
            return self._send_error_json("JSON inválido", 400)

        if path.startswith("/api/"):
            user = self._enforce(path, {"usuarios:update": "usuarios:update"}, metodo="PUT")
            if user is None:
                return

        # === Update Active Empresa / Branding ===
        if path in ("/api/empresa", "/api/empresa/branding"):
            updated = db.actualizar_empresa(payload)
            if updated is None:
                return self._send_error_json("Empresa no encontrada", 404)
            return self._send_json(updated)

        # === System Admin: Update Empresa ===
        if path.startswith("/api/admin/empresas/") and path.split("/")[-1].isdigit():
            emp_id = int(path.split("/")[-1])
            updated = admin.update_empresa(emp_id, payload)
            if updated is None:
                return self._send_error_json("Empresa no encontrada", 404)
            return self._send_json(updated)

        # === System Admin: Update Usuario ===
        if path.startswith("/api/admin/usuarios/") and path.split("/")[-1].isdigit():
            uid = int(path.split("/")[-1])
            updated = admin.update_system_user(uid, payload)
            if updated is None:
                return self._send_error_json("Usuario no encontrado", 404)
            return self._send_json(updated)

        # === System Admin: Update Rol ===
        if path.startswith("/api/admin/roles/") and path.split("/")[-1].isdigit():
            rid = int(path.split("/")[-1])
            updated = admin.update_role(rid, payload)
            if updated is None:
                return self._send_error_json("Rol no encontrado", 404)
            return self._send_json(updated)

        # === System Admin: Update Role Permissions ===
        if path.startswith("/api/admin/roles/") and path.endswith("/permisos"):
            rid = int(path.split("/")[-2])
            permisos = payload.get("permisos", [])
            if not isinstance(permisos, list):
                return self._send_error_json("permisos debe ser una lista", 400)
            if admin.set_role_permissions(rid, permisos):
                return self._send_json({"ok": True, "permisos": permisos})
            return self._send_error_json("No se pudo actualizar", 500)

        # PUT /api/usuarios/<id>/password
        if path.startswith("/api/usuarios/") and path.endswith("/password"):
            uid = path.split("/")[3]
            new_password = payload.get("new_password", "")
            if not uid.isdigit() or not new_password:
                return self._send_error_json("Se requieren usuario_id y new_password", 400)
            resultado = auth.cambiar_password(int(uid), new_password)
            return self._send_json(resultado)

        # PUT /api/empleados/<id> o /api/nomina/empleados/<id>
        if path.startswith(("/api/empleados/", "/api/nomina/empleados/")) and path.split("/")[-1].isdigit():
            emp_id = int(path.split("/")[-1])
            try:
                updated = db.actualizar_empleado(emp_id, payload)
                if updated is None:
                    return self._send_error_json("Empleado no encontrado", 404)
                return self._send_json(updated)
            except Exception as e:
                return self._send_error_json(f"Error al actualizar empleado: {e}", 400)

        return self._send_error_json("Endpoint no encontrado", 404)

    def do_DELETE(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path.startswith("/api/"):
            user = self._enforce(path, {}, metodo="DELETE")
            if user is None:
                return

        # === System Admin: Delete Empresa ===
        if path.startswith("/api/admin/empresas/") and path.split("/")[-1].isdigit():
            emp_id = int(path.split("/")[-1])
            if admin.delete_empresa(emp_id):
                return self._send_json({"ok": True})
            return self._send_error_json("No se pudo eliminar la empresa (hay usuarios vinculados)", 400)

        # === System Admin: Delete Usuario ===
        if path.startswith("/api/admin/usuarios/") and path.split("/")[-1].isdigit():
            uid = int(path.split("/")[-1])
            if admin.delete_system_user(uid):
                return self._send_json({"ok": True})
            return self._send_error_json("No se pudo eliminar el usuario", 400)

        # === System Admin: Delete Rol ===
        if path.startswith("/api/admin/roles/") and path.split("/")[-1].isdigit():
            rid = int(path.split("/")[-1])
            if admin.delete_role(rid):
                return self._send_json({"ok": True})
            return self._send_error_json("No se pudo eliminar el rol (hay usuarios asignados)", 400)

        # === System Admin: Desasignar Usuario de Empresa ===
        if path == "/api/admin/usuario-empresas":
            query = parse_qs(parsed.query)
            uid = query.get("usuario_id", [None])[0]
            eid = query.get("empresa_id", [None])[0]
            if not uid or not eid or not uid.isdigit() or not eid.isdigit():
                return self._send_error_json("Se requieren usuario_id y empresa_id válidos", 400)
            ok = admin.unassign_user_from_empresa(int(uid), int(eid))
            return self._send_json({"ok": ok})

        return self._send_error_json("Endpoint no encontrado", 404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)
        content_type = self.headers.get("Content-Type", "")

        if "multipart/form-data" in content_type and "boundary=" in content_type:
            try:
                import base64
                import email.parser
                raw_msg = (f"Content-Type: {content_type}\r\n\r\n").encode("utf-8") + body
                msg = email.parser.BytesParser().parsebytes(raw_msg)
                file_bytes = None
                filename = "archivo.csv"
                for part in msg.walk():
                    if part.get_content_maintype() == "multipart":
                        continue
                    fn = part.get_filename()
                    if fn or part.get_param("name", header="content-disposition") == "file":
                        file_bytes = part.get_payload(decode=True)
                        if fn:
                            filename = fn
                        break
                if file_bytes is None:
                    return self._send_error_json("No se encontró archivo en FormData", 400)
                ext = "xlsx" if filename.lower().endswith(".xlsx") else "csv"
                payload = {
                    "content_b64": base64.b64encode(file_bytes).decode("ascii"),
                    "formato": ext,
                }
            except Exception as e:
                return self._send_error_json(f"Error al procesar archivo multipart: {e}", 400)
        else:
            try:
                payload = json.loads(body.decode("utf-8")) if body else {}
            except Exception:
                return self._send_error_json("JSON inválido", 400)

        if path == "/api/auth/login":
            return self._do_login(payload)

        if path == "/api/auth/seleccionar-empresa":
            user = self._require_auth()
            if user is None:
                return self._send_error_json("No autenticado", 401)
            empresa_id = payload.get("empresa_id")
            if not empresa_id:
                return self._send_error_json("Se requiere empresa_id", 400)
            try:
                empresa_id = int(empresa_id)
            except (ValueError, TypeError):
                return self._send_error_json("empresa_id inválido", 400)
            allowed = admin.get_empresas_for_user(user["id"])
            if not any(e["id"] == empresa_id for e in allowed):
                return self._send_error_json("Empresa no autorizada para este usuario", 403)
            db.set_current_empresa_id(empresa_id)
            conn = db.get_connection()
            u_row = dbutil.query(conn, "SELECT id, email, rol, nombre, password_changed_at FROM usuarios WHERE id = ?", (user["id"],)).fetchone()
            conn.close()
            token = auth.generar_token(dict(u_row), empresa_id)
            return self._send_json({
                "ok": True,
                "token": token,
                "empresa_id": empresa_id,
                "mensaje": f"Cambiado a empresa {empresa_id}"
            })

        if path.startswith("/api/"):
            user = self._enforce(path, self._PERMISOS_POST)
            if user is None:
                return
            # Registrar acciones administrativas
            if path.startswith(("/api/usuarios", "/api/roles", "/api/permisos")):
                audit.log_evento(user["id"], user["sub"], "ADMIN_ACCION", f"POST {path}")

        # === System Admin: Empresas ===
        if path == "/api/admin/empresas":
            if not payload.get("nit") or not payload.get("razon_social"):
                return self._send_error_json("Se requieren nit y razon_social", 400)
            emp = admin.create_empresa(payload, creado_por=user["id"])
            if emp is None:
                return self._send_error_json("No se pudo crear la empresa", 400)
            return self._send_json(emp)

        # === System Admin: Usuarios ===
        if path == "/api/admin/usuarios":
            if not payload.get("email") or not payload.get("password"):
                return self._send_error_json("Se requieren email y password", 400)
            u = admin.create_system_user(payload)
            if u is None:
                return self._send_error_json("No se pudo crear el usuario", 400)
            return self._send_json(u)

        # === System Admin: Roles ===
        if path == "/api/admin/roles":
            if not payload.get("nombre"):
                return self._send_error_json("Se requiere nombre del rol", 400)
            r = admin.create_role(payload, creado_por=user["id"])
            if r is None:
                return self._send_error_json("No se pudo crear el rol", 400)
            return self._send_json(r)

        # === System Admin: Asignación Usuario - Empresa ===
        if path == "/api/admin/usuario-empresas":
            uid = payload.get("usuario_id")
            eid = payload.get("empresa_id")
            rol_en_empresa = payload.get("rol_en_empresa", "VENDEDOR")
            es_predeterminada = bool(payload.get("es_predeterminada", False))
            if not uid or not eid:
                return self._send_error_json("Se requieren usuario_id y empresa_id", 400)
            res = admin.assign_user_to_empresa(int(uid), int(eid), rol_en_empresa, es_predeterminada)
            if not res:
                return self._send_error_json("No se pudo asignar usuario a empresa", 400)
            return self._send_json({"ok": True, "usuario_id": uid, "empresa_id": eid, "rol_en_empresa": rol_en_empresa})

        # === Administración de usuarios y roles ===
        if path == "/api/usuarios" and payload.get("email"):
            return self._do_crear_usuario(payload)

        if path == "/api/usuarios/cambiar-password" or (path.startswith("/api/usuarios/") and path.endswith("/password")):
            return self._do_cambiar_password(payload, path, caller=user)

        if path == "/api/roles" and payload.get("nombre"):
            return self._do_crear_rol(payload)

        if path == "/api/roles/permisos":
            return self._do_roles_permisos(payload)

        if path == "/api/periodos/cerrar":
            user = self._require_role("ADMIN", "SUPERADMIN")
            if user is None:
                return
            periodo = payload.get("periodo", "")
            justificacion = payload.get("justificacion", "")
            if not periodo:
                return self._send_error_json("Se requiere periodo", 400)
            try:
                resultado = period_control.cerrar_periodo(periodo, usuario_id=user["id"], justificacion=justificacion)
                return self._send_json(resultado)
            except ValueError as e:
                return self._send_error_json(str(e), 400)

        if path == "/api/periodos/reabrir":
            user = self._require_role("ADMIN", "SUPERADMIN")
            if user is None:
                return
            periodo = payload.get("periodo", "")
            justificacion = payload.get("justificacion", "")
            if not periodo:
                return self._send_error_json("Se requiere periodo", 400)
            try:
                resultado = period_control.reabrir_periodo(periodo, usuario_id=user["id"], justificacion=justificacion)
                return self._send_json(resultado)
            except (ValueError, PermissionError) as e:
                status = 403 if isinstance(e, PermissionError) else 400
                return self._send_error_json(str(e), status=status)

        if path == "/api/liquidar":
            lineas_in = payload.get("lineas", [])
            if not lineas_in:
                return self._send_error_json("Se requiere al menos una línea", 400)
            try:
                engine = TaxEngine()
                lineas_obj = []
                for idx, l in enumerate(lineas_in, 1):
                    lineas_obj.append(LineaFactura(
                        codigo=l.get("producto_codigo", f"P{idx}"),
                        descripcion=l.get("descripcion", f"Item {idx}"),
                        cantidad=Decimal(str(l.get("cantidad", 1))),
                        valor_unitario=Decimal(str(l.get("valor_unitario", 0))),
                        tarifa_iva=l.get("tarifa_iva", "IVA_19"),
                        clasificacion=l.get("tipo_bien_servicio", "BIENES"),
                    ))
                resultado = engine.liquidar_factura(lineas_obj)
                res_dict = {
                    "base_total": resultado.base_total,
                    "iva_19": sum((r.valor_iva for r in resultado.lineas if r.linea.tarifa_iva == "IVA_19"), Decimal("0")),
                    "iva_5": sum((r.valor_iva for r in resultado.lineas if r.linea.tarifa_iva == "IVA_5"), Decimal("0")),
                    "iva_0": sum((r.valor_iva for r in resultado.lineas if r.linea.tarifa_iva == "IVA_0"), Decimal("0")),
                    "total_iva": resultado.iva_total,
                    "retefuente": resultado.retencion_fuente_total,
                    "reteica": resultado.reteica_total,
                    "reteiva": resultado.reteiva_total,
                    "total_factura": resultado.valor_transaccion,
                    "lineas": [
                        {
                            "codigo": r.linea.codigo,
                            "descripcion": r.linea.descripcion,
                            "cantidad": r.linea.cantidad,
                            "valor_unitario": r.linea.valor_unitario,
                            "base": r.base,
                            "valor_iva": r.valor_iva,
                            "tarifa_iva": r.linea.tarifa_iva,
                            "retefuente": r.retencion_fuente,
                            "reteica": r.reteica,
                            "reteiva": r.reteiva,
                            "total_linea": r.total_linea,
                        }
                        for r in resultado.lineas
                    ]
                }
                return self._send_json(res_dict)
            except Exception as e:
                return self._send_error_json(str(e), 400)

        if path == "/api/emitir":
            user = self._require_auth()
            if user is None:
                return self._send_error_json("No autenticado", 401)
            cliente_nit = payload.get("cliente_nit")
            lineas_in = payload.get("lineas", [])
            tipo_operacion = payload.get("tipo_operacion", "01")
            if not cliente_nit or not lineas_in:
                return self._send_error_json("Cliente y líneas requeridos", 400)

            try:
                empresa = db.get_empresa()
                if not empresa:
                    return self._send_error_json("Empresa no configurada", 500)

                # Validar periodo contable abierto
                try:
                    period_control.validar_periodo_abierto()
                except period_control.PeriodoCerradoError as pe:
                    return self._send_error_json(str(pe), 403)

                cliente = None
                for c in db.get_clientes():
                    if c["nit"] == cliente_nit or c["nit"].replace("-", "") == cliente_nit.replace("-", ""):
                        cliente = c
                        break
                if not cliente:
                    return self._send_error_json("Cliente no encontrado", 404)

                # 1. Liquidar
                engine = TaxEngine()
                lineas_obj = []
                for idx, l in enumerate(lineas_in, 1):
                    lineas_obj.append(LineaFactura(
                        codigo=l.get("producto_codigo", f"P{idx}"),
                        descripcion=l.get("descripcion", f"Item {idx}"),
                        cantidad=Decimal(str(l.get("cantidad", 1))),
                        valor_unitario=Decimal(str(l.get("valor_unitario", 0))),
                        tarifa_iva=l.get("tarifa_iva", "IVA_19"),
                        clasificacion=l.get("tipo_bien_servicio", "BIENES"),
                    ))
                resultado = engine.liquidar_factura(lineas_obj)

                # 2. Consecutivo dentro del rango autorizado por la DIAN.
                # Antes era len(facturas) + 1, que ignora el rango, no es
                # contiguo y reutiliza números tras un borrado.
                try:
                    cons = numeracion.siguiente_consecutivo(empresa, "facturas")
                except numeracion.ErrorNumeracion as exc:
                    return self._send_error_json(str(exc), 400)
                consecutivo = cons.completo

                ahora = parametros.ahora_utc()
                fecha_str = ahora.strftime("%Y-%m-%d")
                # La DIAN exige hora de Colombia (UTC-5) con formato HH:MM:SS.
                hora_col = ahora.astimezone(timezone(timedelta(hours=-5)))
                hora_str = hora_col.strftime("%H:%M:%S")

                # En producción no se emite sin certificado digital.
                try:
                    numeracion.exigir_certificado_para_emitir(empresa)
                except numeracion.ErrorNumeracion as exc:
                    return self._send_error_json(str(exc), 400)

                # 3. Ensamblar UBL
                emisor_obj = Emisor(
                    nit=empresa["nit"],
                    nombre=empresa["razon_social"],
                    direccion=empresa["direccion"],
                    ciudad=empresa["municipio"],
                    departamento=empresa.get("departamento") or "",
                    tipo_documento=empresa.get("tipo_documento") or "NIT",
                    clave_tecnica=empresa["clave_tecnica"],
                    resolucion_dian=empresa.get("resolucion_dian") or "",
                    fecha_resolucion=empresa.get("fecha_resolucion") or "",
                    nit_proveedor=empresa.get("nit_proveedor") or "800197268",
                )
                adquirente_obj = Adquirente(
                    nit=cliente["nit"],
                    nombre=cliente["razon_social"],
                    direccion=cliente["direccion"],
                    ciudad=cliente["municipio"],
                    tipo_documento=cliente["tipo_documento"],
                    codigo_documento=cliente["nit"],
                    regimen_fiscal=str(cliente.get("regimen_fiscal") or "2"),
                )
                builder = UblInvoiceBuilder(emisor_obj, adquirente_obj, engine=engine)
                factura_ubl = builder.build(
                    num_fac=consecutivo,
                    fecha=fecha_str,
                    hora=hora_str,
                    lineas=lineas_obj,
                    clave_tecnica=empresa["clave_tecnica"],
                    tipo_ambiente=empresa["tipo_ambiente"],
                    tipo_operacion=tipo_operacion,
                    fecha_vencimiento=(ahora + timedelta(days=int(cliente.get("plazo_dias") or 30))).strftime("%Y-%m-%d"),
                )

                # 4. Firmar y transmitir a DIAN (mock o real según configuración)
                xml_firmado = _firmar_xml(empresa, factura_ubl.xml)
                client = get_dian_client(str(empresa.get("nit", "")), empresa)
                trans_res = client.transmitir_xml(xml_firmado)

                # 5. Guardar en BD
                iva_19 = sum((r.valor_iva for r in resultado.lineas if r.linea.tarifa_iva == "IVA_19"), Decimal("0"))
                iva_5 = sum((r.valor_iva for r in resultado.lineas if r.linea.tarifa_iva == "IVA_5"), Decimal("0"))
                iva_0 = sum((r.valor_iva for r in resultado.lineas if r.linea.tarifa_iva == "IVA_0"), Decimal("0"))

                attached_doc = ""
                if trans_res.application_response_xml:
                    try:
                        from sap_colombia.attached_document import construir_attached_document
                        attached_doc = construir_attached_document(
                            xml_firmado,
                            trans_res.application_response_xml,
                            tipo_ambiente=empresa.get("tipo_ambiente", "1"),
                        )
                    except Exception as exc:
                        logger.warning("No se pudo construir AttachedDocument: %s", exc)

                datos_fac = {
                    "consecutivo": consecutivo,
                    "prefijo": empresa["prefijo_resolucion"],
                    "fecha": fecha_str,
                    "hora": hora_str,
                    "cliente_nit": cliente["nit"],
                    "subtotal": resultado.base_total,
                    "iva_19": iva_19,
                    "iva_5": iva_5,
                    "iva_0": iva_0,
                    "total_iva": resultado.iva_total,
                    "retefuente": resultado.retencion_fuente_total,
                    "reteica": resultado.reteica_total,
                    "reteiva": resultado.reteiva_total,
                    "total_factura": resultado.valor_transaccion,
                    "cufe": factura_ubl.cufe,
                    "qr": factura_ubl.qr,
                    "xml_ubl": xml_firmado or factura_ubl.xml,
                    "estado_dian": trans_res.estado,
                    "track_id": trans_res.track_id,
                    "mensaje_dian": trans_res.status_description,
                    "application_response_xml": trans_res.application_response_xml,
                    "attached_document_xml": attached_doc,
                }
                lineas_db = [
                    {
                        "producto_codigo": l.codigo,
                        "descripcion": l.descripcion,
                        "cantidad": l.cantidad,
                        "valor_unitario": l.valor_unitario,
                        "subtotal": r.base,
                        "tarifa_iva": l.tarifa_iva,
                        "valor_iva": r.valor_iva,
                        "tipo_bien_servicio": l.clasificacion,
                    }
                    for l, r in zip(lineas_obj, resultado.lineas)
                ]
                with db.transactional_scope() as tx_conn:
                    fac_id = db.guardar_factura(datos_fac, lineas_db, conn=tx_conn)
                    datos_fac["id"] = fac_id

                    try:
                        accounting_engine.contabilizar_factura_venta(datos_fac, conn=tx_conn)
                    except Exception:
                        import logging
                        logging.warning("Fallo al contabilizar factura")

                    try:
                        inventory.registrar_factura(
                            factura_id=fac_id,
                            lineas=lineas_db,
                            conn=tx_conn,
                        )
                    except inventory.InventarioError as inv_err:
                        import logging
                        logging.warning(f"Alerta de inventario: {inv_err}")

                return self._send_json({
                    "id": fac_id,
                    "consecutivo": consecutivo,
                    "cufe": factura_ubl.cufe,
                    "qr": factura_ubl.qr,
                    "track_id": trans_res.track_id,
                    "estado_dian": trans_res.estado,
                    "status_code": trans_res.status_code,
                    "status_description": trans_res.status_description,
                    "fecha_validacion": trans_res.fecha_validacion,
                    "total_factura": resultado.valor_transaccion,
                })
            except Exception as e:
                import traceback
                traceback.print_exc()
                return self._send_error_json(str(e), 500)

        if path == "/api/notas-credito/crear":
            factura_id = payload.get("factura_id")
            motivo_dian = payload.get("motivo_dian")
            if not factura_id or not motivo_dian:
                return self._send_error_json("Se requiere factura_id y motivo_dian", 400)
            try:
                empresa_emisor = db.get_empresa()
                if not empresa_emisor:
                    return self._send_error_json(
                        "Datos de la empresa emisora no configurados", 400)
                client = get_dian_client(str(empresa_emisor.get("nit", "")), empresa_emisor)

                resultado = credit_notes.emitir_nota_credito(
                    factura_id=int(factura_id),
                    motivo_dian=motivo_dian,
                    descripcion_motivo=payload.get("descripcion_motivo", "") or "",
                    tipo_anulacion=payload.get("tipo_anulacion", "TOTAL") or "TOTAL",
                    lineas_devolucion=payload.get("lineas_devolucion"),
                    dian_client=client,
                )
                nc_id = resultado["nota_credito"]["id"]
                nc_detalle = db.get_nota_credito_by_id(nc_id)
                lineas_nc = nc_detalle.get("lineas", []) if nc_detalle else []
                if lineas_nc:
                    try:
                        inventory.registrar_nota_credito(
                            nc_id=nc_id,
                            lineas=lineas_nc,
                        )
                    except inventory.InventarioError as inv_err:
                        import logging
                        logging.warning(f"Alerta de inventario: {inv_err}")
                return self._send_json(resultado)
            except Exception as e:
                return self._send_error_json(str(e), 400)

        if path == "/api/cartera/recaudar":
            factura_id = payload.get("factura_id")
            monto = payload.get("monto")
            if not factura_id or monto is None:
                return self._send_error_json("Se requiere factura_id y monto", 400)
            try:
                resultado = accounts_receivable.registrar_recibo_caja(
                    factura_id=int(factura_id),
                    monto=monto,
                    medio_pago=payload.get("medio_pago", "EFECTIVO"),
                    referencia=payload.get("referencia", ""),
                    observaciones=payload.get("observaciones", ""),
                )
                return self._send_json(resultado)
            except Exception as e:
                return self._send_error_json(str(e), 400)

        if path == "/api/documento-soporte/crear":
            datos_ds = payload.get("datos", {})
            lineas = payload.get("lineas", [])
            if not datos_ds:
                return self._send_error_json("Se requiere el bloque 'datos'", 400)
            try:
                resultado = support_document.crear_documento_soporte(datos_ds, lineas)
                return self._send_json(resultado)
            except Exception as e:
                return self._send_error_json(str(e), 400)

        if path == "/api/nomina/liquidar":
            empleado_id = payload.get("empleado_id")
            periodo_inicio = payload.get("periodo_inicio")
            periodo_fin = payload.get("periodo_fin")
            if not empleado_id or not periodo_inicio or not periodo_fin:
                return self._send_error_json("Se requiere empleado_id, periodo_inicio y periodo_fin", 400)
            try:
                resultado = payroll.liquidar_nomina(
                    empleado_id=int(empleado_id),
                    periodo_inicio=periodo_inicio,
                    periodo_fin=periodo_fin,
                )
                return self._send_json(resultado)
            except Exception as e:
                return self._send_error_json(str(e), 400)

        if path == "/api/nomina/emitir":
            empleado_id = payload.get("empleado_id")
            periodo_inicio = payload.get("periodo_inicio")
            periodo_fin = payload.get("periodo_fin")
            if not empleado_id or not periodo_inicio or not periodo_fin:
                return self._send_error_json("Se requiere empleado_id, periodo_inicio y periodo_fin", 400)
            try:
                # Obtener empresa para el NIT del emisor
                empresa = db.get_empresa()
                client = get_dian_client(str(empresa.get("nit", "")), empresa)

                resultado = payroll.emitir_nomina(
                    empleado_id=int(empleado_id),
                    periodo_inicio=periodo_inicio,
                    periodo_fin=periodo_fin,
                    dian_client=client,
                )
                return self._send_json(resultado)
            except Exception as e:
                return self._send_error_json(str(e), 400)

        if path == "/api/nomina/pagar":
            nomina_id = payload.get("nomina_id")
            medio_pago = payload.get("medio_pago", "EFECTIVO")
            if not nomina_id:
                return self._send_error_json("Se requiere nomina_id", 400)
            try:
                from sap_colombia.payroll_payment import pagar_nomina
                resultado = pagar_nomina(nomina_id=int(nomina_id), medio_pago=medio_pago)
                return self._send_json(resultado)
            except Exception as e:
                return self._send_error_json(str(e), 400)

        if path == "/api/nomina/pagar-todos":
            from sap_colombia.payroll_payment import pagar_nomina
            nomina_ids = payload.get("nomina_ids")
            medio_pago = payload.get("medio_pago", "EFECTIVO")
            if not nomina_ids or not isinstance(nomina_ids, list):
                return self._send_error_json("Se requiere nomina_ids (lista de IDs)", 400)
            pagadas = []
            errores = []
            for nid in nomina_ids:
                try:
                    resultado = pagar_nomina(nomina_id=int(nid), medio_pago=medio_pago)
                    pagadas.append({"nomina_id": int(nid), "estado": "PAGADA", "monto": resultado["recibo"]["monto"]})
                except Exception as e:
                    errores.append({"nomina_id": int(nid), "error": str(e)})
            return self._send_json({"pagadas": pagadas, "errores": errores, "total": len(nomina_ids), "exito": len(pagadas), "fallos": len(errores)})

        if path in ("/api/empleados", "/api/nomina/empleados"):
            tipo_documento = payload.get("tipo_documento")
            documento = payload.get("documento")
            nombres = payload.get("nombres")
            apellidos = payload.get("apellidos")
            salario_base = payload.get("salario_base")
            if not all([tipo_documento, documento, nombres, apellidos, salario_base]):
                return self._send_error_json("Se requieren tipo_documento, documento, nombres, apellidos y salario_base", 400)
            try:
                datos = {
                    "tipo_documento": tipo_documento,
                    "documento": documento,
                    "nombres": nombres,
                    "apellidos": apellidos,
                    "salario_base": salario_base,
                    "auxilio_transporte": payload.get("auxilio_transporte", "175405.00"),
                    "activo": payload.get("activo", 1),
                    "created_at": payload.get("created_at") or datetime.now().isoformat(),
                }
                if payload.get("id"):
                    updated = db.actualizar_empleado(int(payload["id"]), datos)
                    if updated:
                        return self._send_json(updated)
                emp_id = db.guardar_empleado(datos)
                return self._send_json(db.get_empleado_by_id(emp_id))
            except Exception as e:
                return self._send_error_json(f"Error al guardar empleado: {e}", 400)

        # === RADIAN Events ===
        if path == "/api/radian/evento":
            factura_id = payload.get("factura_id")
            codigo_evento = str(payload.get("codigo_evento", ""))
            observaciones = payload.get("observaciones", "")
            if not factura_id or not codigo_evento:
                return self._send_error_json("Se requiere factura_id y codigo_evento", 400)
            try:
                empresa_emisor = db.get_empresa()
                if not empresa_emisor:
                    return self._send_error_json(
                        "Datos de la empresa emisora no configurados", 400)
                client = get_dian_client(str(empresa_emisor.get("nit", "")), empresa_emisor)
                resultado = radian.registrar_evento_radian(
                    factura_id=int(factura_id),
                    codigo_evento=codigo_evento,
                    observaciones=observaciones,
                    dian_client=client,
                )
                return self._send_json(resultado)
            except Exception as e:
                return self._send_error_json(str(e), 400)

        # === Notas Débito ===
        if path == "/api/notas-debito/crear":
            factura_id = payload.get("factura_id")
            concepto_dian = str(payload.get("concepto_dian", "4"))
            subtotal = payload.get("subtotal", "0.00")
            iva_19 = payload.get("iva_19", "0.00")
            iva_5 = payload.get("iva_5", "0.00")
            descripcion = payload.get("descripcion", "")
            lineas = payload.get("lineas")
            if not factura_id:
                return self._send_error_json("Se requiere factura_id", 400)
            try:
                empresa_emisor = db.get_empresa()
                if not empresa_emisor:
                    return self._send_error_json(
                        "Datos de la empresa emisora no configurados", 400)
                client = get_dian_client(str(empresa_emisor.get("nit", "")), empresa_emisor)

                resultado = debit_notes.emitir_nota_debito(
                    factura_id=int(factura_id),
                    concepto_dian=concepto_dian,
                    subtotal=subtotal,
                    iva_19=iva_19,
                    iva_5=iva_5,
                    descripcion=descripcion,
                    lineas=lineas,
                    dian_client=client,
                )
                return self._send_json(resultado)
            except Exception as e:
                return self._send_error_json(str(e), 400)

        # === Enviar factura por correo ===
        if path == "/api/facturas/enviar-correo":
            factura_id = payload.get("factura_id")
            email_destino = payload.get("email_destino", "")
            if not factura_id:
                return self._send_error_json("Se requiere factura_id", 400)
            if not email_destino:
                return self._send_error_json("Se requiere email_destino", 400)
            factura = db.get_factura_by_id(int(factura_id))
            if not factura:
                return self._send_error_json("Factura no encontrada", 404)
            empresa = db.get_empresa() or {}
            cliente = None
            for c in db.get_clientes():
                if c["nit"] == factura.get("cliente_nit"):
                    cliente = c
                    break
            pdf_bytes = pdf_generator.generar_pdf_documento(
                tipo="FACTURA",
                documento=factura,
                empresa=empresa,
                cliente=cliente,
            )
            resultado = mail_notifier.enviar_factura_por_correo(
                factura_id=int(factura_id),
                consecutivo=factura.get("consecutivo", str(factura_id)),
                cufe=factura.get("cufe", ""),
                pdf_bytes=pdf_bytes,
                email_destino=email_destino,
                asunto=payload.get("asunto"),
                smtp_host=payload.get("smtp_host", "localhost"),
                smtp_port=int(payload.get("smtp_port", 587)),
                smtp_user=payload.get("smtp_user"),
                smtp_pass=payload.get("smtp_pass"),
            )
            return self._send_json(resultado)

        # === Importaciones Masivas (POST) ===
        if path in (
            "/api/importaciones/facturas",
            "/api/importaciones/saldos-iniciales",
            "/api/importaciones/saldos_iniciales",
            "/api/importaciones/toma-inventario",
            "/api/importaciones/toma_inventario",
        ):
            content_b64 = payload.get("content_b64")
            formato = payload.get("formato", "csv")
            if not content_b64:
                return self._send_error_json("Se requiere content_b64", 400)
            try:
                import base64
                content = base64.b64decode(content_b64)
                empresa_id = payload.get("empresa_id")
                if path == "/api/importaciones/facturas":
                    resultado = massive_import.importar_facturas(content, formato, empresa_id)
                elif path in ("/api/importaciones/saldos-iniciales", "/api/importaciones/saldos_iniciales"):
                    resultado = massive_import.importar_saldos_iniciales(content, formato, empresa_id)
                else:
                    resultado = massive_import.importar_toma_inventario(content, formato, empresa_id)
                return self._send_json(resultado)
            except massive_import.ImportErrorMassive as e:
                return self._send_error_json(str(e), 400)
            except Exception as e:
                return self._send_error_json(str(e), 500)

        # === 2FA / TOTP ===
        if path == "/api/auth/2fa/setup":
            user = self._require_auth()
            if user is None:
                return self._send_error_json("No autenticado", 401)
            secret = auth.generar_totp_secret()
            uri = auth.generar_totp_uri(user["sub"], secret)
            return self._send_json({"secret": secret, "uri": uri})

        if path == "/api/auth/2fa/verify":
            user = self._require_auth()
            if user is None:
                return self._send_error_json("No autenticado", 401)
            secret = payload.get("secret", "")
            codigo = payload.get("codigo", "")
            if not secret or not codigo:
                return self._send_error_json("Se requieren secret y codigo", 400)
            ok = auth.habilitar_2fa(user["id"], secret, codigo)
            if not ok:
                return self._send_error_json("Código 2FA / TOTP inválido", 400)
            audit.log_evento(user["id"], user["sub"], "2FA_HABILITADO", None, ip=self.client_address[0])
            return self._send_json({"ok": True, "mensaje": "2FA habilitado correctamente"})

        if path == "/api/auth/2fa/disable":
            user = self._require_auth()
            if user is None:
                return self._send_error_json("No autenticado", 401)
            auth.deshabilitar_2fa(user["id"])
            audit.log_evento(user["id"], user["sub"], "2FA_DESHABILITADO", None, ip=self.client_address[0])
            return self._send_json({"ok": True, "mensaje": "2FA deshabilitado"})

        # === Compras y Proveedores ===
        if path == "/api/compras/procesar-xml":
            xml_o_zip = payload.get("xml") or payload.get("content")
            if not xml_o_zip:
                return self._send_error_json("Se requiere el contenido XML o ZIP de la factura", 400)
            try:
                if isinstance(xml_o_zip, str) and (xml_o_zip.startswith("UEsDB") or payload.get("es_base64")):
                    import base64
                    xml_o_zip = base64.b64decode(xml_o_zip)
                res = vendor_bills.procesar_factura_proveedor(xml_o_zip)
                return self._send_json(res)
            except Exception as e:
                return self._send_error_json(str(e), 400)

        if path == "/api/compras/radian-evento":
            fid = payload.get("factura_compra_id")
            codigo_evento = payload.get("codigo_evento")
            obs = payload.get("observaciones", "")
            if not fid or not codigo_evento:
                return self._send_error_json("Se requiere factura_compra_id y codigo_evento", 400)
            try:
                res = vendor_bills.emitir_evento_radian_proveedor(int(fid), str(codigo_evento), observaciones=obs)
                return self._send_json(res)
            except Exception as e:
                return self._send_error_json(str(e), 400)

        # === Cuentas por Pagar (CxP) ===
        if path == "/api/cxp/egreso":
            try:
                res = accounts_payable.registrar_comprobante_egreso(payload)
                return self._send_json(res)
            except Exception as e:
                return self._send_error_json(str(e), 400)

        # === Ciclo Comercial (Ventas) ===
        if path == "/api/ventas/cotizaciones":
            try:
                if user and "usuario_id" not in payload:
                    payload["usuario_id"] = user.get("id")
                res = commercial_cycle.crear_cotizacion(payload)
                return self._send_json(res)
            except Exception as e:
                return self._send_error_json(str(e), 400)

        if path.startswith("/api/ventas/cotizaciones/") and path.endswith("/aprobar"):
            try:
                cid = int(path.split("/")[4])
                uid = user["id"] if user else 1
                res = commercial_cycle.aprobar_cotizacion(cid, usuario_aprobador_id=uid)
                return self._send_json(res)
            except Exception as e:
                return self._send_error_json(str(e), 400)

        if path.startswith("/api/ventas/cotizaciones/") and path.endswith("/convertir-pedido"):
            try:
                cid = int(path.split("/")[4])
                res = commercial_cycle.convertir_cotizacion_a_pedido(cid)
                return self._send_json(res)
            except Exception as e:
                return self._send_error_json(str(e), 400)

        if path.startswith("/api/ventas/pedidos/") and path.endswith("/convertir-remision"):
            try:
                pid = int(path.split("/")[4])
                res = commercial_cycle.convertir_pedido_a_remision(pid)
                return self._send_json(res)
            except Exception as e:
                return self._send_error_json(str(e), 400)

        if path.startswith("/api/ventas/pedidos/") and path.endswith("/convertir-factura"):
            try:
                pid = int(path.split("/")[4])
                res = commercial_cycle.convertir_pedido_a_factura(pid)
                return self._send_json(res)
            except Exception as e:
                return self._send_error_json(str(e), 400)

        # === POS Electrónico ===
        if path == "/api/pos/cajas":
            nom = payload.get("nombre", "")
            ubicacion = payload.get("ubicacion", "")
            if not nom:
                return self._send_error_json("Se requiere nombre de la caja", 400)
            try:
                res = pos_system.crear_caja(nom, ubicacion=ubicacion)
                return self._send_json(res)
            except Exception as e:
                return self._send_error_json(str(e), 400)

        if path == "/api/pos/abrir-caja":
            cid = payload.get("caja_id")
            monto_ini = payload.get("monto_inicial", "0.00")
            if not cid:
                return self._send_error_json("Se requiere caja_id", 400)
            try:
                res = pos_system.abrir_caja(int(cid), usuario_id=user["id"], monto_inicial=monto_ini)
                return self._send_json(res)
            except Exception as e:
                return self._send_error_json(str(e), 400)

        if path == "/api/pos/cerrar-caja":
            sid = payload.get("sesion_id")
            total_real = payload.get("total_real", "0.00")
            obs = payload.get("observaciones", "")
            if not sid:
                return self._send_error_json("Se requiere sesion_id", 400)
            try:
                res = pos_system.cerrar_caja(int(sid), total_real=total_real, observaciones=obs)
                return self._send_json(res)
            except Exception as e:
                return self._send_error_json(str(e), 400)

        # === Listas de Precios ===
        if path == "/api/listas-precios":
            nom = payload.get("nombre", "")
            desc = payload.get("descripcion", "")
            if not nom:
                return self._send_error_json("Se requiere nombre de la lista", 400)
            try:
                res = price_lists.crear_lista_precios(nom, descripcion=desc)
                return self._send_json(res)
            except Exception as e:
                return self._send_error_json(str(e), 400)

        if path.startswith("/api/listas-precios/") and path.endswith("/precios"):
            try:
                lid = int(path.split("/")[3])
                prod = payload.get("producto_codigo", "")
                precio = payload.get("precio", "0.00")
                res = price_lists.asignar_precio_producto(lid, prod, precio)
                return self._send_json(res)
            except Exception as e:
                return self._send_error_json(str(e), 400)

        # === Traslados de Inventario ===
        if path == "/api/inventario/traslados":
            prod = payload.get("producto_codigo", "")
            b_orig = payload.get("bodega_origen", "")
            b_dest = payload.get("bodega_destino", "")
            cant = payload.get("cantidad", 0)
            lote = payload.get("lote")
            fecha = payload.get("fecha")
            if not prod or not b_orig or not b_dest or not cant:
                return self._send_error_json("Faltan parámetros requeridos para el traslado", 400)
            try:
                res = inventory.trasladar_bodega(
                    producto_codigo=prod,
                    bodega_origen=b_orig,
                    bodega_destino=b_dest,
                    cantidad=Decimal(str(cant)),
                    lote=lote,
                    fecha=fecha,
                )
                return self._send_json(res)
            except Exception as e:
                return self._send_error_json(str(e), 400)

        self._send_error_json("Endpoint no encontrado", 404)


def run_web_server(port=8000, host="127.0.0.1"):
    db.init_db()
    auth.seed_usuarios()
    rbac.ensure_rbac()
    server_address = (host, port)
    # ThreadingHTTPServer: una petición lenta (transmisión a DIAN, export XLSX)
    # no debe bloquear al resto de la API.
    httpd = ThreadingHTTPServer(server_address, SapWebHandler)
    httpd.daemon_threads = True
    print(f"==================================================================")
    print(f" ERP SAP Colombia - Facturación Electrónica DIAN")
    print(f" Servidor Web iniciado en: http://{host}:{port}")
    print(f"==================================================================")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
        try:
            from sap_colombia import dian_factory
            if dian_factory._mock_server:
                dian_factory._mock_server.stop()
        except Exception:
            pass

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    host = sys.argv[2] if len(sys.argv) > 2 else os.environ.get("SAP_HOST", "127.0.0.1")
    run_web_server(port, host)
