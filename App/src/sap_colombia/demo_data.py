"""
================================================================================
 MÓDULO DE GESTIÓN DE DATOS DE DEMOSTRACIÓN (DEMO) — ERP COLOMBIA
================================================================================
Permite poblar o limpiar controladamente los datos ficticios de demostración:
  - Empresas Demo (Empresa Corporativa S.A.S. y Inversiones Andinas S.A.S.)
  - Clientes de prueba (Distribuidora del Café, Comercializadora Caribe, etc.)
  - Productos de prueba (P001 con IVA 19%, P002 con IVA 5%, etc.)
  - Bodegas y stock de prueba (BODEGA-01)
  - Empleados y nómina de prueba
  - Cajas POS de prueba
  - Usuarios de prueba con roles asignados (Gerente, Contador, Vendedor, etc.)

PRESERVANDO SIEMPRE en la limpieza:
  - Catálogo PUC (Plan Único de Cuentas NIIF)
  - Parámetros tributarios legales DIAN (UVT, Retenciones)
  - Esquema y tablas de base de datos
  - Roles y permisos RBAC del sistema
  - Superadministrador de la plataforma (admin@sistema.com / admin@saluki.com)
"""
import base64
from datetime import datetime, timezone
import psycopg2.extensions
from sap_colombia import dbutil
from sap_colombia import database as db
from sap_colombia import auth

DEMO_NIT_CORP = "90012345678"
DEMO_NIT_ANDINA = "901987654"

DEMO_EMAILS = [
    "gerente@empresa.com",
    "contador@empresa.com",
    "vendedor@empresa.com",
    "tesorero@empresa.com",
    "cajero@empresa.com",
    "rrhh@empresa.com",
    "almacen@empresa.com",
]

# Logos SVG vectoriales en Base64 para demostración de identidad visual
_SVG_CORP = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="140" height="44" viewBox="0 0 140 44">'
    '<rect width="40" height="40" x="2" y="2" rx="8" fill="#0070f2"/>'
    '<path d="M12 22 L20 30 L32 14" stroke="#ffffff" stroke-width="4" fill="none" stroke-linecap="round" stroke-linejoin="round"/>'
    '<text x="50" y="27" font-family="Inter, Arial, sans-serif" font-weight="800" font-size="18" fill="#0f172a">CORP</text>'
    '<text x="103" y="27" font-family="Inter, Arial, sans-serif" font-weight="700" font-size="14" fill="#0070f2">ERP</text>'
    '</svg>'
)
_LOGO_CORP_B64 = "data:image/svg+xml;base64," + base64.b64encode(_SVG_CORP.encode("utf-8")).decode("ascii")

_SVG_ANDINA = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="150" height="44" viewBox="0 0 150 44">'
    '<rect width="40" height="40" x="2" y="2" rx="8" fill="#059669"/>'
    '<polygon points="22,8 34,32 10,32" fill="#ffffff"/>'
    '<text x="48" y="27" font-family="Montserrat, Arial, sans-serif" font-weight="800" font-size="16" fill="#064e3b">ANDINA</text>'
    '</svg>'
)
_LOGO_ANDINA_B64 = "data:image/svg+xml;base64," + base64.b64encode(_SVG_ANDINA.encode("utf-8")).decode("ascii")


def sembrar_datos_demo(conn: psycopg2.extensions.connection | None = None) -> dict:
    """Inserta el conjunto completo de datos de demostración en la base de datos activa."""
    close_at_end = False
    if conn is None:
        conn = db.get_connection()
        close_at_end = True

    stats = {
        "empresas": 0,
        "bodegas": 0,
        "clientes": 0,
        "productos": 0,
        "empleados": 0,
        "cajas_pos": 0,
        "usuarios": 0,
    }

    try:
        now_iso = datetime.now(timezone.utc).isoformat(sep=" ")

        # 1. Empresa Demo Principal (Empresa Corporativa S.A.S. - Tema Horizon Blue)
        emp1 = dbutil.query(conn, "SELECT id FROM empresas WHERE nit = ?", (DEMO_NIT_CORP,)).fetchone()
        if not emp1:
            cur = dbutil.query(
                conn,
                """INSERT INTO empresas (
                    nit, dv, razon_social, nombre_marca, direccion, municipio, departamento,
                    prefijo_resolucion, resolucion_dian, fecha_resolucion, rango_desde, rango_hasta,
                    clave_tecnica, tipo_ambiente, logo_data, color_primario, color_secundario,
                    color_sidebar, color_fondo, fuente_nombre
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING id""",
                (
                    DEMO_NIT_CORP, "1", "Empresa Corporativa S.A.S.", "CORP",
                    "Cra 15 # 45-30, PBX 12", "Bogotá D.C.", "Cundinamarca",
                    "SETP", "18760000001", "2026-01-15", 990000000, 999999999,
                    "3fa9c0b1d2e34f5a6b7c8d9e0f1a2b3c", "1",
                    _LOGO_CORP_B64, "#0070f2", "#1b90ff", "#0f172a", "#f4f6f9", "Inter",
                ),
            )
            emp1_id = cur.fetchone()["id"]
            stats["empresas"] += 1
        else:
            emp1_id = emp1["id"]

        # 2. Segunda Empresa Demo (Inversiones Andinas S.A.S. - Tema Esmeralda)
        emp2 = dbutil.query(conn, "SELECT id FROM empresas WHERE nit = ?", (DEMO_NIT_ANDINA,)).fetchone()
        if not emp2:
            cur = dbutil.query(
                conn,
                """INSERT INTO empresas (
                    nit, dv, razon_social, nombre_marca, direccion, municipio, departamento,
                    prefijo_resolucion, resolucion_dian, fecha_resolucion, rango_desde, rango_hasta,
                    clave_tecnica, tipo_ambiente, logo_data, color_primario, color_secundario,
                    color_sidebar, color_fondo, fuente_nombre
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING id""",
                (
                    DEMO_NIT_ANDINA, "3", "Inversiones Andinas S.A.S.", "ANDINA",
                    "Av. El Dorado # 68B-85", "Bogotá D.C.", "Bogotá D.C.",
                    "AND", "18764099887766", "2026-01-15", 1, 500000,
                    "fc8eac422eba16e22ffd8c6f94b3f40a6e38162c", "2",
                    _LOGO_ANDINA_B64, "#059669", "#10b981", "#064e3b", "#f0fdf4", "Montserrat",
                ),
            )
            emp2_id = cur.fetchone()["id"]
            stats["empresas"] += 1
        else:
            emp2_id = emp2["id"]

        # 3. Bodega Demo
        bod = dbutil.query(conn, "SELECT id FROM bodegas WHERE codigo = ?", ("BODEGA-01",)).fetchone()
        if not bod:
            dbutil.query(
                conn,
                "INSERT INTO bodegas (codigo, nombre, direccion, activa) VALUES (?, ?, ?, 1)",
                ("BODEGA-01", "Bodega Principal", "Cra 15 # 45-30, PBX 12"),
            )
            stats["bodegas"] += 1

        # 4. Clientes Demo
        clientes_demo = [
            (emp1_id, "800197268", "4", "NIT", "Distribuidora del Café S.A.S.", "Calle 26 # 68C-61", "Bogotá D.C.", "facturacion@districafe.com.co", "6013142589", "Responsable IVA"),
            (emp1_id, "900876543", "8", "NIT", "Comercializadora Caribe S.A.", "Cra 52 # 74-56", "Barranquilla", "contabilidad@caribesa.com.co", "6053851234", "Responsable IVA"),
            (emp1_id, "1234567890", "9", "CC", "Carlos Eduardo Rodríguez", "Carrera 7 # 12-45", "Cali", "carlos.rodriguez@email.com", "3154879512", "No Responsable IVA"),
            (emp1_id, "1111111111", "2", "NIT", "Tecnología y Redes del Norte S.A.S.", "Calle 100 # 19A-40", "Bogotá D.C.", "facturas@tecronorte.com.co", "6017456321", "Responsable IVA"),
            (emp1_id, "2222222222", "3", "NIT", "Servicios Andinos Ltda", "Av. El Poblado # 34-12", "Medellín", "administracion@andinos.com.co", "3201234567", "Responsable IVA"),
        ]
        for c in clientes_demo:
            if not dbutil.query(conn, "SELECT id FROM clientes WHERE nit = ? AND (empresa_id = ? OR empresa_id IS NULL)", (c[1], c[0])).fetchone():
                dbutil.query(
                    conn,
                    """INSERT INTO clientes (empresa_id, nit, dv, tipo_documento, razon_social, direccion, municipio, email, telefono, regimen_fiscal)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    c,
                )
                stats["clientes"] += 1

        # 5. Productos Demo
        productos_demo = [
            (emp1_id, "P001", "Producto general con IVA 19%", "100000.00", "IVA_19", "BIENES", "U", 10),
            (emp1_id, "P002", "Producto con IVA 5%", "50000.00", "IVA_5", "BIENES", "U", 5),
            (emp1_id, "P003", "Servicio técnico mensual", "200000.00", "IVA_19", "SERVICIOS", "H", 0),
            (emp1_id, "P004", "Arrendamiento de equipo", "150000.00", "IVA_19", "ARRENDAMIENTO", "D", 0),
            (emp1_id, "P005", "Producto exento", "50000.00", "IVA_0", "EXENTO", "U", 5),
        ]
        for p in productos_demo:
            if not dbutil.query(conn, "SELECT id FROM productos WHERE codigo = ? AND (empresa_id = ? OR empresa_id IS NULL)", (p[1], p[0])).fetchone():
                dbutil.query(
                    conn,
                    """INSERT INTO productos (empresa_id, codigo, descripcion, precio_unitario, tarifa_iva, tipo_bien_servicio, unidad_medida, stock_minimo)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    p,
                )
                stats["productos"] += 1

        # 6. Empleados Demo
        empleados_demo = [
            ("CC", "1018456123", "Carlos", "Contador Pérez", "2800000.00", "0.00", 1),
            ("CC", "1020789456", "Pedro", "Vendedor Gómez", "1800000.00", "162000.00", 1),
            ("CC", "1032145879", "Elena", "Recursos Humanos", "2500000.00", "0.00", 1),
        ]
        for e in empleados_demo:
            if not dbutil.query(conn, "SELECT id FROM empleados WHERE documento = ?", (e[1],)).fetchone():
                dbutil.query(
                    conn,
                    """INSERT INTO empleados (tipo_documento, documento, nombres, apellidos, salario_base, auxilio_transporte, activo, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (*e, now_iso),
                )
                stats["empleados"] += 1

        # 7. Cajas POS Demo
        if not dbutil.query(conn, "SELECT id FROM pos_cajas WHERE nombre = ? AND empresa_id = ?", ("Caja Principal Mostrador", emp1_id)).fetchone():
            dbutil.query(
                conn,
                "INSERT INTO pos_cajas (empresa_id, nombre, ubicacion, activa, created_at) VALUES (?, ?, ?, 1, ?)",
                (emp1_id, "Caja Principal Mostrador", "Local Principal Piso 1", now_iso),
            )
            stats["cajas_pos"] += 1

        # 8. Usuarios de Demostración con Roles
        demo_users = [
            ("gerente@empresa.com", "Gerente123!", "Gerente General", "ADMIN_EMPRESA", emp1_id),
            ("contador@empresa.com", "Contador123!", "Ana Contadora", "CONTADOR", emp1_id),
            ("vendedor@empresa.com", "Vendedor123!", "Pedro Vendedor", "VENDEDOR", emp1_id),
            ("tesorero@empresa.com", "Tesorero123!", "Lucía Tesorera", "TESORERO", emp1_id),
            ("cajero@empresa.com", "Cajero123!", "Juan Cajero POS", "CAJERO_POS", emp1_id),
            ("rrhh@empresa.com", "Nomina123!", "Elena Recursos Humanos", "RECURSOS_HUMANOS", emp1_id),
            ("almacen@empresa.com", "Almacen123!", "Marcos Almacenista", "ALMACENISTA", emp1_id),
        ]
        for email, pwd, nombre, rol, eid in demo_users:
            u_row = dbutil.query(conn, "SELECT id FROM usuarios WHERE email = ?", (email,)).fetchone()
            if not u_row:
                h, salt = auth.hash_password(pwd)
                cur = dbutil.query(
                    conn,
                    """INSERT INTO usuarios (email, nombre, rol, hash_password, salt, activo, created_at, empresa_id, password_changed_at)
                       VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?) RETURNING id""",
                    (email, nombre, rol, h, salt, now_iso, eid, now_iso),
                )
                uid = cur.fetchone()["id"]
                stats["usuarios"] += 1
            else:
                uid = u_row["id"]
                h, salt = auth.hash_password(pwd)
                dbutil.query(
                    conn,
                    "UPDATE usuarios SET hash_password = ?, salt = ?, nombre = ?, rol = ?, activo = 1, password_changed_at = ? WHERE id = ?",
                    (h, salt, nombre, rol, now_iso, uid),
                )

            # Vincular a la empresa predeterminada
            if eid:
                dbutil.query(
                    conn,
                    """INSERT INTO usuario_empresas (usuario_id, empresa_id, rol_en_empresa, es_predeterminada, created_at)
                       VALUES (?, ?, ?, 1, ?) ON CONFLICT DO NOTHING""",
                    (uid, eid, rol, now_iso),
                )

        # 9. Vincular al Superadmin a las empresas demo para que pueda alternar libremente
        for s_email in ("admin@sistema.com", "admin@saluki.com"):
            s_row = dbutil.query(conn, "SELECT id FROM usuarios WHERE email = ?", (s_email,)).fetchone()
            if s_row:
                suid = s_row["id"]
                for eid in (emp1_id, emp2_id):
                    dbutil.query(
                        conn,
                        """INSERT INTO usuario_empresas (usuario_id, empresa_id, rol_en_empresa, es_predeterminada, created_at)
                           VALUES (?, ?, 'SUPERADMIN', 0, ?) ON CONFLICT DO NOTHING""",
                        (suid, eid, now_iso),
                    )

        conn.commit()
    finally:
        if close_at_end:
            conn.close()

    return stats


def limpiar_datos_demo(conn: psycopg2.extensions.connection | None = None, solo_ficticios: bool = True) -> dict:
    """
    Limpia de manera segura y controlada los datos de demostración o datos operacionales.
    
    PRESERVA SIEMPRE:
      - Plan de Cuentas PUC (plan_cuentas)
      - Parámetros tributarios DIAN (parametros_tributarios)
      - Catálogo de roles y permisos (roles, permisos, role_permissions)
      - Cuentas de Superadministrador (admin@sistema.com, admin@saluki.com)
    """
    close_at_end = False
    if conn is None:
        conn = db.get_connection()
        close_at_end = True

    purged = {}

    try:
        # Tablas transaccionales y de negocio a limpiar
        tablas_a_limpiar = [
            "pos_sesiones",
            "pos_turnos",
            "pos_ventas",
            "pos_cajas",
            "remisiones_venta",
            "pedidos_venta",
            "cotizaciones",
            "comprobantes_egreso",
            "cuentas_por_pagar",
            "facturas_compra",
            "compras_recibidas",
            "precios_productos",
            "listas_precios",
            "lineas_nota_credito",
            "notas_credito",
            "lineas_nota_debito",
            "notas_debito",
            "factura_lineas",
            "facturas",
            "lineas_documento_soporte",
            "documentos_soporte",
            "kardex",
            "stock_actual",
            "lotes",
            "movimientos_contables",
            "asientos_contables",
            "cierre_fiscal",
            "exogena_formatos",
            "recibos_caja",
            "eventos_radian",
            "nomina_novedades",
            "nominas",
            "empleados",
            "clientes",
            "proveedores",
            "productos",
            "bodegas",
            "auditoria",
        ]

        if not solo_ficticios:
            # Limpieza total para producción: vaciar tablas operacionales completas
            tablas_existentes = {
                r["table_name"]
                for r in dbutil.query(
                    conn,
                    "SELECT table_name FROM information_schema.tables WHERE table_schema='public'"
                ).fetchall()
            }
            for t in tablas_a_limpiar:
                if t in tablas_existentes:
                    res = dbutil.query(conn, f'TRUNCATE TABLE "{t}" RESTART IDENTITY CASCADE')
                    purged[t] = "TRUNCATED"

            # Limpiar usuario_empresas y usuarios demo
            dbutil.query(conn, 'TRUNCATE TABLE "usuario_empresas" RESTART IDENTITY CASCADE')
            dbutil.query(
                conn,
                "DELETE FROM usuarios WHERE email NOT IN ('admin@sistema.com', 'admin@saluki.com')"
            )
            # Limpiar empresas
            dbutil.query(conn, 'TRUNCATE TABLE "empresas" RESTART IDENTITY CASCADE')
            purged["empresas"] = "TRUNCATED"
            purged["usuarios_demo"] = "PURGED"
        else:
            # Limpieza dirigida: solo elimina las empresas demo y sus registros vinculados
            demo_nits = (DEMO_NIT_CORP, DEMO_NIT_ANDINA)
            emp_rows = dbutil.query(
                conn,
                "SELECT id FROM empresas WHERE nit IN (?, ?)",
                demo_nits,
            ).fetchall()
            demo_emp_ids = [r["id"] for r in emp_rows]

            tablas_existentes = {
                r["table_name"]
                for r in dbutil.query(
                    conn,
                    "SELECT table_name FROM information_schema.tables WHERE table_schema='public'"
                ).fetchall()
            }

            if demo_emp_ids:
                ph = ", ".join(["?"] * len(demo_emp_ids))
                tablas_con_empresa = [
                    "pos_sesiones", "pos_turnos", "pos_ventas", "pos_cajas",
                    "remisiones_venta", "pedidos_venta", "cotizaciones",
                    "lineas_nota_credito", "notas_credito",
                    "lineas_nota_debito", "notas_debito",
                    "factura_lineas", "facturas",
                    "lineas_documento_soporte", "documentos_soporte",
                    "comprobantes_egreso", "cuentas_por_pagar", "facturas_compra", "compras_recibidas",
                    "kardex", "stock_actual", "lotes", "precios_productos", "listas_precios",
                    "movimientos_contables", "asientos_contables", "cierre_fiscal", "exogena_formatos",
                    "recibos_caja", "eventos_radian", "nomina_novedades", "nominas",
                    "empleados", "clientes", "productos"
                ]

                for t in tablas_con_empresa:
                    if t in tablas_existentes:
                        cols = set(dbutil.table_columns(conn, t))
                        if "empresa_id" in cols:
                            dbutil.query(conn, f'DELETE FROM "{t}" WHERE empresa_id IN ({ph})', tuple(demo_emp_ids))
                            purged[t] = "demo_purged"
                        elif t == "empleados":
                            dbutil.query(conn, "DELETE FROM empleados WHERE documento IN ('1018456123', '1020789456', '1032145879')")
                            purged["empleados"] = "demo_purged"

                # Eliminar bodegas demo
                if "bodegas" in tablas_existentes:
                    dbutil.query(conn, "DELETE FROM bodegas WHERE codigo IN ('BODEGA-01', 'BODEGA-02')")
                    purged["bodegas"] = "demo_purged"

                # Eliminar vínculos usuario_empresas
                if "usuario_empresas" in tablas_existentes:
                    dbutil.query(conn, f'DELETE FROM usuario_empresas WHERE empresa_id IN ({ph})', tuple(demo_emp_ids))

                # Eliminar las empresas demo
                dbutil.query(conn, f'DELETE FROM empresas WHERE id IN ({ph})', tuple(demo_emp_ids))
                purged["empresas"] = len(demo_emp_ids)

            # Eliminar usuarios demo y sus referencias (auditoria, usuario_empresas, etc.)
            if DEMO_EMAILS and "usuarios" in tablas_existentes:
                e_ph = ", ".join(["?"] * len(DEMO_EMAILS))
                if "auditoria" in tablas_existentes:
                    dbutil.query(conn, f"DELETE FROM auditoria WHERE usuario_id IN (SELECT id FROM usuarios WHERE email IN ({e_ph}))", tuple(DEMO_EMAILS))
                if "pos_sesiones" in tablas_existentes:
                    dbutil.query(conn, f"DELETE FROM pos_sesiones WHERE usuario_id IN (SELECT id FROM usuarios WHERE email IN ({e_ph}))", tuple(DEMO_EMAILS))
                if "usuario_empresas" in tablas_existentes:
                    dbutil.query(conn, f"DELETE FROM usuario_empresas WHERE usuario_id IN (SELECT id FROM usuarios WHERE email IN ({e_ph}))", tuple(DEMO_EMAILS))
                dbutil.query(conn, f"DELETE FROM usuarios WHERE email IN ({e_ph})", tuple(DEMO_EMAILS))
                purged["usuarios_demo"] = len(DEMO_EMAILS)

        # Asegurar que admin@sistema.com y admin@saluki.com existan con sus roles intactos
        auth.seed_usuarios()

        conn.commit()
    finally:
        if close_at_end:
            conn.close()

    return purged


def estado_datos_demo(conn: psycopg2.extensions.connection | None = None) -> dict:
    """Retorna el estado de la base de datos indicando si contiene datos demo o está limpia."""
    close_at_end = False
    if conn is None:
        conn = db.get_connection()
        close_at_end = True

    try:
        emp_total = dbutil.query(conn, "SELECT COUNT(*) AS n FROM empresas").fetchone()["n"]
        emp_demo = dbutil.query(
            conn,
            "SELECT COUNT(*) AS n FROM empresas WHERE nit IN (?, ?)",
            (DEMO_NIT_CORP, DEMO_NIT_ANDINA),
        ).fetchone()["n"]

        cli_total = dbutil.query(conn, "SELECT COUNT(*) AS n FROM clientes").fetchone()["n"]
        prod_total = dbutil.query(conn, "SELECT COUNT(*) AS n FROM productos").fetchone()["n"]
        usr_total = dbutil.query(conn, "SELECT COUNT(*) AS n FROM usuarios").fetchone()["n"]

        e_ph = ", ".join(["?"] * len(DEMO_EMAILS))
        usr_demo = dbutil.query(
            conn,
            f"SELECT COUNT(*) AS n FROM usuarios WHERE email IN ({e_ph})",
            tuple(DEMO_EMAILS),
        ).fetchone()["n"]

        tiene_demo = (emp_demo > 0 or usr_demo > 0)
        es_limpio = (emp_total == 0 and usr_total <= 2)

        return {
            "tiene_demo": tiene_demo,
            "es_limpio": es_limpio,
            "total_empresas": emp_total,
            "empresas_demo": emp_demo,
            "total_clientes": cli_total,
            "total_productos": prod_total,
            "total_usuarios": usr_total,
            "usuarios_demo": usr_demo,
        }
    finally:
        if close_at_end:
            conn.close()
