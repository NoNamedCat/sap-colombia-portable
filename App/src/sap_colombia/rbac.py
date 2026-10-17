"""Catálogo de permisos RBAC (resource:action) y helpers de BD."""

from datetime import datetime
from sap_colombia import dbutil
from sap_colombia import database as db

PERMISOS = [
    "usuarios:read", "usuarios:create", "usuarios:update", "usuarios:delete",
    "roles:read", "roles:create", "roles:update", "roles:delete",
    "permisos:read",
    "auditoria:read",
    "empresa:read", "empresa:update",
    "clientes:read", "clientes:create", "clientes:update", "clientes:delete",
    "productos:read", "productos:create", "productos:update", "productos:delete",
    "facturacion:read", "facturacion:create", "facturacion:update",
    "notas_credito:read", "notas_credito:create",
    "notas_debito:read", "notas_debito:create",
    "cartera:read", "cartera:create",
    "documento_soporte:read", "documento_soporte:create",
    "contabilidad:read", "contabilidad:create", "contabilidad:asiento",
    "inventario:read", "inventario:update",
    "nominas:read", "nominas:create",
    "periodos:read", "periodos:cerrar", "periodos:reabrir",
    "dashboard:read",
    "exogena:read",
    "radian:read",
    "empresas:read", "empresas:create", "empresas:update", "empresas:delete",
    "usuarios_sistema:read", "usuarios_sistema:create", "usuarios_sistema:update", "usuarios_sistema:delete",
    "roles_empresa:read", "roles_empresa:create", "roles_empresa:update", "roles_empresa:delete",
    "importaciones:read", "importaciones:create",
    "compras:read", "compras:create",
    "cxp:read", "cxp:create",
    "ventas:read", "ventas:create", "ventas:update",
    "pos:read", "pos:create",
    "impuestos:read",
    "precios:read", "precios:create",
]

ROLES_SEED = [
    ("ADMIN", "Administrador Global de Sistema", ["*"]),
    ("SUPERADMIN", "Superadministrador de Sistema", ["*"]),
    ("ADMIN_SISTEMA", "Administrador de Sistema", [
        "empresas:read", "empresas:create", "empresas:update", "empresas:delete",
        "usuarios_sistema:read", "usuarios_sistema:create", "usuarios_sistema:update", "usuarios_sistema:delete",
        "roles_empresa:read", "roles_empresa:create", "roles_empresa:update", "roles_empresa:delete",
        "auditoria:read",
    ]),
    ("ADMIN_EMPRESA", "Administrador de Empresa", [
        "dashboard:read",
        "empresa:read", "empresa:update",
        "usuarios:read", "usuarios:create", "usuarios:update", "usuarios:delete",
        "clientes:read", "clientes:create", "clientes:update", "clientes:delete",
        "productos:read", "productos:create", "productos:update", "productos:delete",
        "facturacion:read", "facturacion:create", "facturacion:update",
        "notas_credito:read", "notas_credito:create",
        "notas_debito:read", "notas_debito:create",
        "cartera:read", "cartera:create",
        "ventas:read", "ventas:create", "ventas:update",
        "pos:read", "pos:create",
        "compras:read", "compras:create",
        "cxp:read", "cxp:create",
        "documento_soporte:read", "documento_soporte:create",
        "inventario:read", "inventario:update",
        "contabilidad:read", "contabilidad:create", "contabilidad:asiento",
        "impuestos:read",
        "precios:read", "precios:create",
        "nominas:read", "nominas:create",
        "periodos:read", "periodos:cerrar",
        "exogena:read",
        "radian:read",
        "importaciones:read", "importaciones:create",
    ]),
    ("VENDEDOR", "Vendedor Comercial", [
        "facturacion:read", "facturacion:create",
        "notas_credito:read", "notas_credito:create",
        "notas_debito:read", "notas_debito:create",
        "cartera:read", "documento_soporte:read",
        "ventas:read", "ventas:create", "pos:read", "pos:create", "precios:read",
        "clientes:read", "clientes:create", "productos:read",
    ]),
    ("CAJERO_POS", "Cajero Punto de Venta POS", [
        "pos:read", "pos:create", "facturacion:read", "facturacion:create",
        "clientes:read", "productos:read", "precios:read",
    ]),
    ("ALMACENISTA", "Almacenista / Logística", [
        "inventario:read", "inventario:update", "facturacion:read",
        "compras:read", "productos:read",
    ]),
    ("CONTADOR", "Contador / Revisor Fiscal", [
        "contabilidad:read", "contabilidad:create", "contabilidad:asiento",
        "periodos:read", "periodos:cerrar", "nominas:read", "nominas:create",
        "facturacion:read", "notas_debito:read", "cartera:read",
        "compras:read", "compras:create", "cxp:read", "cxp:create", "impuestos:read",
        "exogena:read", "radian:read",
    ]),
    ("TESORERO", "Tesorero / Cuentas por Pagar", [
        "compras:read", "compras:create", "cxp:read", "cxp:create",
        "cartera:read", "contabilidad:read",
    ]),
    ("RECURSOS_HUMANOS", "Gestor de Talento Humano", [
        "nominas:read", "nominas:create",
    ]),
]


def permisos_catalogo() -> list[str]:
    return list(PERMISOS)


def roles_existentes() -> list[str]:
    """Nombres de rol realmente definidos en la base de datos."""
    conn = db.get_connection()
    rows = dbutil.query(conn, "SELECT nombre FROM roles ORDER BY nombre").fetchall()
    conn.close()
    return [r["nombre"] for r in rows]


def permisos_por_recurso(recurso: str) -> list[str]:
    return [p for p in PERMISOS if p.startswith(f"{recurso}:")]


def _seed_roles() -> None:
    conn = db.get_connection()
    now = datetime.now().isoformat()
    for nombre, desc, _ in ROLES_SEED:
        tipo = "SISTEMA" if nombre in ("SUPERADMIN", "ADMIN_SISTEMA", "ADMIN") else "EMPRESA"
        dbutil.query(conn, 
            "INSERT INTO roles (nombre, descripcion, activo, tipo, created_at) VALUES (?, ?, 1, ?, ?) "
            "ON CONFLICT (nombre) DO UPDATE SET tipo = EXCLUDED.tipo, descripcion = EXCLUDED.descripcion",
            (nombre, desc, tipo, now),
        )
    conn.commit()
    conn.close()


def _ensure_role_permissions() -> None:
    conn = db.get_connection()
    for p in PERMISOS:
        recurso, accion = p.split(":", 1)
        dbutil.query(conn, 
            "INSERT INTO permisos (recurso, accion) VALUES (?, ?) ON CONFLICT DO NOTHING",
            (recurso, accion),
        )
    permisos = {row["recurso"] + ":" + row["accion"]: row["id"]
                for row in dbutil.query(conn, "SELECT * FROM permisos").fetchall()}
    roles = {row["nombre"]: row["id"] for row in dbutil.query(conn, "SELECT * FROM roles").fetchall()}
    for nombre, _desc, perms in ROLES_SEED:
        if nombre not in roles:
            continue
        for p in perms:
            if p == "*":
                for pid in permisos.values():
                    dbutil.query(conn, 
                        "INSERT INTO role_permissions (role_id, permission_id) VALUES (?, ?) ON CONFLICT DO NOTHING",
                        (roles[nombre], pid),
                    )
            elif p in permisos:
                dbutil.query(conn, 
                    "INSERT INTO role_permissions (role_id, permission_id) VALUES (?, ?) ON CONFLICT DO NOTHING",
                    (roles[nombre], permisos[p]),
                )
    conn.commit()
    conn.close()


def ensure_rbac() -> None:
    """Asegura roles seed y permisos asignados (idempotente)."""
    _seed_roles()
    _ensure_role_permissions()


def usuario_tiene_permiso(conn, usuario_id: int, permiso: str) -> bool:
    row = dbutil.query(conn, 
        "SELECT r.nombre FROM usuarios u JOIN roles r ON u.rol = r.nombre WHERE u.id = ?",
        (usuario_id,),
    ).fetchone()
    if row is None:
        return False
    if row["nombre"] in ("ADMIN", "SUPERADMIN"):
        return True
    return _role_tiene_permiso(conn, row["nombre"], permiso)


def permisos_de_recursos(recursos: set[str]) -> set[str]:
    """Conjunción de todos los permisos de los recursos dados (catalogo)."""
    return {p for p in PERMISOS if p.split(":")[0] in recursos}


def _role_tiene_permiso(conn, rol: str, permiso: str) -> bool:
    row = dbutil.query(conn, 
        "SELECT 1 FROM role_permissions rp "
        "JOIN roles r ON r.id = rp.role_id "
        "JOIN permisos p ON p.id = rp.permission_id "
        "WHERE r.nombre = ? AND (p.recurso || ':' || p.accion = ? OR p.recurso = '*' OR p.accion = '*')",
        (rol, permiso),
    ).fetchone()
    return row is not None


def permisos_usuario(conn, usuario_id: int) -> set[str]:
    row = dbutil.query(conn, "SELECT rol FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()
    if row is None:
        return set()
    return permisos_rol(conn, row["rol"])


def permisos_rol(conn, rol: str) -> set[str]:
    rows = dbutil.query(conn,
        "SELECT p.recurso || ':' || p.accion AS perm FROM role_permissions rp "
        "JOIN roles r ON r.id = rp.role_id "
        "JOIN permisos p ON p.id = rp.permission_id "
        "WHERE r.nombre = ?",
        (rol,),
    ).fetchall()
    return {r["perm"] for r in rows}


# ============================================================================
# Matriz de Separación de Obligaciones (SoD - Segregation of Duties)
# ============================================================================

CONFLICTOS_SOD = [
    {
        "id": "SOD-001",
        "permiso_a": "compras:create",
        "permiso_b": "cxp:create",
        "nivel": "ALTO",
        "titulo": "Compras vs. Desembolsos (Cuentas por Pagar)",
        "descripcion": "El mismo usuario puede registrar facturas de proveedores y autorizar/emitir pagos o egresos bancarios. Riesgo de pagos no autorizados o proveedores simulados.",
        "control_compensatorio": "Exigir visto bueno de Tesorería independiente de quien registra la recepción de factura.",
    },
    {
        "id": "SOD-002",
        "permiso_a": "facturacion:create",
        "permiso_b": "notas_credito:create",
        "nivel": "MEDIO",
        "titulo": "Facturación vs. Anulación por Nota Crédito",
        "descripcion": "Permite emitir facturas y anularlas directamente mediante Notas Crédito sin autorización de supervisión.",
        "control_compensatorio": "Toda Nota Crédito por anulación total debe requerir visto bueno del Contador o Administrador de Empresa.",
    },
    {
        "id": "SOD-003",
        "permiso_a": "nominas:create",
        "permiso_b": "cxp:create",
        "nivel": "ALTO",
        "titulo": "Liquidación de Nómina vs. Pagos de Tesorería",
        "descripcion": "Un mismo operador puede liquidar novedades de nómina y ordenar pagos sin segregación.",
        "control_compensatorio": "Separación de cargos entre Gestión Humana (liquidación) y Tesorería (desembolso bancario).",
    },
    {
        "id": "SOD-004",
        "permiso_a": "inventario:update",
        "permiso_b": "compras:create",
        "nivel": "MEDIO",
        "titulo": "Ajuste de Kardex / Inventario vs. Compras",
        "descripcion": "Capacidad de alterar existencias físicas de almacén y registrar facturas de compras simultáneamente.",
        "control_compensatorio": "Conteos cíclicos de inventario ciegos y traslados con doble confirmación de bodega.",
    },
    {
        "id": "SOD-005",
        "permiso_a": "periodos:cerrar",
        "permiso_b": "periodos:reabrir",
        "nivel": "ALTO",
        "titulo": "Cierre y Reapertura de Periodos Contables",
        "descripcion": "Un usuario puede reabrir periodos contables cerrados y alterarlos sin justificación independiente.",
        "control_compensatorio": "Exigir justificación obligatoria documentada y registro inmutable en auditoría.",
    },
]


def catalogo_conflictos_sod() -> list[dict]:
    """Retorna la matriz completa de reglas de riesgo SoD."""
    return list(CONFLICTOS_SOD)


def analizar_conflictos_sod(permisos: list[str] | set[str]) -> list[dict]:
    """Evalúa un conjunto de permisos y retorna los conflictos SoD detectados."""
    perm_set = set(permisos)
    if "*" in perm_set:
        return []
    conflictos = []
    for c in CONFLICTOS_SOD:
        if c["permiso_a"] in perm_set and c["permiso_b"] in perm_set:
            conflictos.append(c)
    return conflictos


def resolver_permiso_tri_estado(permisos: set[str], recurso: str) -> str:
    """Calcula el nivel de acceso tri-estado: 'FULL', 'READ_ONLY' o 'NONE'."""
    if "*" in permisos:
        return "FULL"
    perms_recurso = {p for p in permisos if p.startswith(f"{recurso}:")}
    if not perms_recurso:
        return "NONE"

    acciones_modificacion = (":create", ":update", ":delete", ":asiento", ":cerrar", ":reabrir")
    if any(p.endswith(acciones_modificacion) for p in perms_recurso):
        return "FULL"

    if any(p.endswith(":read") for p in perms_recurso):
        return "READ_ONLY"

    return "NONE"
