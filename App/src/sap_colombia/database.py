"""Persistencia PostgreSQL para el módulo SAP Colombia."""

import os
import threading
import psycopg2
from sap_colombia import dbutil
from contextlib import contextmanager
from datetime import datetime, timezone

from sap_colombia import config as _sap_config

# DSN PostgreSQL (configurable por entorno o Data/config.json)
PG_DSN = os.environ.get("SAP_PG_DSN") or _sap_config.pg_dsn()

EMPRESAS_COLUMNS = (
    "nit",
    "dv",
    "razon_social",
    "direccion",
    "municipio",
    "departamento",
    "prefijo_resolucion",
    "resolucion_dian",
    "fecha_resolucion",
    "rango_desde",
    "rango_hasta",
    "clave_tecnica",
    "tipo_ambiente",
    "nombre_marca",
    "logo_data",
    "color_primario",
    "color_secundario",
    "color_sidebar",
    "color_fondo",
    "fuente_nombre",
    "fuente_data",
)

CLIENTES_COLUMNS = (
    "nit",
    "dv",
    "tipo_documento",
    "razon_social",
    "direccion",
    "municipio",
    "email",
    "telefono",
    "regimen_fiscal",
)

PRODUCTOS_COLUMNS = (
    "codigo",
    "descripcion",
    "precio_unitario",
    "tarifa_iva",
    "tipo_bien_servicio",
    "unidad_medida",
)

FACTURAS_COLUMNS = (
    "empresa_id",
    "consecutivo",
    "prefijo",
    "fecha",
    "hora",
    "cliente_nit",
    "subtotal",
    "iva_19",
    "iva_5",
    "iva_0",
    "total_iva",
    "retefuente",
    "reteica",
    "reteiva",
    "total_factura",
    "cufe",
    "qr",
    "xml_ubl",
    "estado_dian",
    "track_id",
    "mensaje_dian",
    "plazo_dias",
    "fecha_vencimiento",
    "saldo_pendiente",
    "estado_cartera",
    "application_response_xml",
    "attached_document_xml",
)

LINEAS_FACTURA_COLUMNS = (
    "producto_codigo",
    "descripcion",
    "cantidad",
    "valor_unitario",
    "subtotal",
    "tarifa_iva",
    "valor_iva",
    "tipo_bien_servicio",
)

NOTAS_CREDITO_COLUMNS = (
    "empresa_id",
    "consecutivo",
    "prefijo",
    "fecha",
    "hora",
    "factura_id",
    "factura_consecutivo",
    "cufe_factura",
    "cliente_nit",
    "motivo_dian",
    "descripcion_motivo",
    "subtotal",
    "total_iva",
    "retefuente",
    "reteica",
    "reteiva",
    "total_nota",
    "cude",
    "qr",
    "xml_ubl",
    "estado_dian",
    "track_id",
    "mensaje_dian",
)

LINEAS_NOTA_CREDITO_COLUMNS = (
    "producto_codigo",
    "descripcion",
    "cantidad",
    "valor_unitario",
    "subtotal",
    "tarifa_iva",
    "valor_iva",
)

RECIBOS_CAJA_COLUMNS = (
    "numero",
    "fecha",
    "cliente_nit",
    "factura_id",
    "monto",
    "medio_pago",
    "referencia",
    "observaciones",
)

DOCUMENTOS_SOPORTE_COLUMNS = (
    "empresa_id",
    "consecutivo",
    "prefijo",
    "fecha",
    "hora",
    "proveedor_nit",
    "proveedor_nombre",
    "subtotal",
    "retefuente",
    "reteica",
    "total_documento",
    "cuds",
    "qr",
    "xml_ubl",
    "estado_dian",
    "track_id",
    "mensaje_dian",
)

LINEAS_DOCUMENTO_SOPORTE_COLUMNS = (
    "descripcion",
    "cantidad",
    "valor_unitario",
    "subtotal",
)


def _schema_sql() -> str:
    return """
        CREATE TABLE IF NOT EXISTS bodegas (
            id SERIAL PRIMARY KEY,
            codigo TEXT NOT NULL UNIQUE,
            nombre TEXT NOT NULL,
            direccion TEXT,
            activa INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS kardex (
            id SERIAL PRIMARY KEY,
            fecha TEXT NOT NULL,
            producto_codigo TEXT NOT NULL,
            bodega_codigo TEXT NOT NULL,
            tipo_movimiento TEXT NOT NULL,
            referencia_documento TEXT,
            cantidad_entrada TEXT,
            cantidad_salida TEXT,
            saldo_cantidad TEXT NOT NULL,
            costo_unitario TEXT,
            costo_total_saldo TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS stock_actual (
            producto_codigo TEXT NOT NULL,
            bodega_codigo TEXT NOT NULL,
            cantidad TEXT NOT NULL,
            costo_promedio TEXT NOT NULL,
            PRIMARY KEY (producto_codigo, bodega_codigo)
        );
        CREATE TABLE IF NOT EXISTS empresas (
            id SERIAL PRIMARY KEY,
            nit TEXT NOT NULL UNIQUE,
            dv TEXT,
            razon_social TEXT NOT NULL,
            direccion TEXT,
            municipio TEXT,
            departamento TEXT,
            prefijo_resolucion TEXT,
            resolucion_dian TEXT,
            fecha_resolucion TEXT,
            rango_desde INTEGER,
            rango_hasta INTEGER,
            clave_tecnica TEXT,
            tipo_ambiente TEXT,
            ruta_certificado TEXT,
            password_certificado TEXT,
            url_dian TEXT,
            en_contingencia INTEGER DEFAULT 0,
            motivo_contingencia TEXT,
            fecha_contingencia TEXT,
            nombre_marca TEXT,
            logo_data TEXT,
            color_primario TEXT DEFAULT '#2563eb',
            color_secundario TEXT DEFAULT '#1d4ed8',
            color_sidebar TEXT DEFAULT '#0f172a',
            color_fondo TEXT DEFAULT '#f1f5f9',
            fuente_nombre TEXT DEFAULT 'Inter',
            fuente_data TEXT
        );

        CREATE TABLE IF NOT EXISTS tenant_context (
            empresa_id SERIAL PRIMARY KEY
        );

        CREATE TABLE IF NOT EXISTS clientes (
            id SERIAL PRIMARY KEY,
            empresa_id INTEGER NOT NULL,
            nit TEXT NOT NULL,
            dv TEXT,
            tipo_documento TEXT NOT NULL,
            razon_social TEXT NOT NULL,
            direccion TEXT,
            municipio TEXT,
            email TEXT,
            telefono TEXT,
            regimen_fiscal TEXT,
            UNIQUE(empresa_id, nit)
        );

        CREATE TABLE IF NOT EXISTS productos (
            id SERIAL PRIMARY KEY,
            empresa_id INTEGER NOT NULL,
            codigo TEXT NOT NULL,
            descripcion TEXT NOT NULL,
            precio_unitario TEXT NOT NULL,
            tarifa_iva TEXT NOT NULL,
            tipo_bien_servicio TEXT NOT NULL,
            unidad_medida TEXT,
            UNIQUE(empresa_id, codigo)
        );

        CREATE TABLE IF NOT EXISTS facturas (
            id SERIAL PRIMARY KEY,
            empresa_id INTEGER NOT NULL,
            consecutivo TEXT NOT NULL,
            prefijo TEXT,
            fecha TEXT NOT NULL,
            hora TEXT,
            cliente_nit TEXT NOT NULL,
            subtotal TEXT,
            iva_19 TEXT,
            iva_5 TEXT,
            iva_0 TEXT,
            total_iva TEXT,
            retefuente TEXT,
            reteica TEXT,
            reteiva TEXT,
            total_factura TEXT,
            cufe TEXT,
            qr TEXT,
            xml_ubl TEXT,
            estado_dian TEXT,
            track_id TEXT,
            mensaje_dian TEXT,
            plazo_dias INTEGER DEFAULT 30,
            fecha_vencimiento TEXT,
            saldo_pendiente TEXT,
            estado_cartera TEXT DEFAULT 'PENDIENTE',
            application_response_xml TEXT,
            attached_document_xml TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS factura_lineas (
            id SERIAL PRIMARY KEY,
            factura_id INTEGER NOT NULL,
            producto_codigo TEXT NOT NULL,
            descripcion TEXT NOT NULL,
            cantidad TEXT,
            valor_unitario TEXT,
            subtotal TEXT,
            tarifa_iva TEXT,
            valor_iva TEXT,
            tipo_bien_servicio TEXT,
            FOREIGN KEY (factura_id)
                REFERENCES facturas (id)
                ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS plan_cuentas (
            codigo TEXT PRIMARY KEY,
            nombre TEXT NOT NULL,
            naturaleza TEXT NOT NULL,
            nivel INTEGER NOT NULL,
            categoria TEXT NOT NULL,
            activa INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS asientos_contables (
            id SERIAL PRIMARY KEY,
            numero_comprobante TEXT NOT NULL UNIQUE,
            fecha TEXT NOT NULL,
            tipo_documento TEXT NOT NULL,
            documento_id INTEGER,
            glosa TEXT NOT NULL,
            total_debito TEXT NOT NULL,
            total_credito TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS movimientos_contables (
            id SERIAL PRIMARY KEY,
            asiento_id INTEGER NOT NULL,
            cuenta_codigo TEXT NOT NULL,
            tercero_nit TEXT,
            tercero_nombre TEXT,
            concepto TEXT,
            debito TEXT NOT NULL,
            credito TEXT NOT NULL,
            FOREIGN KEY (asiento_id)
                REFERENCES asientos_contables (id)
                ON DELETE CASCADE,
            FOREIGN KEY (cuenta_codigo)
                REFERENCES plan_cuentas (codigo)
        );

        CREATE TABLE IF NOT EXISTS notas_credito (
            id SERIAL PRIMARY KEY,
            empresa_id INTEGER NOT NULL,
            consecutivo TEXT NOT NULL,
            prefijo TEXT,
            fecha TEXT NOT NULL,
            hora TEXT,
            factura_id INTEGER NOT NULL,
            factura_consecutivo TEXT NOT NULL,
            cufe_factura TEXT NOT NULL,
            cliente_nit TEXT NOT NULL,
            motivo_dian TEXT NOT NULL,
            descripcion_motivo TEXT,
            subtotal TEXT,
            total_iva TEXT,
            retefuente TEXT,
            reteica TEXT,
            reteiva TEXT,
            total_nota TEXT,
            cude TEXT,
            qr TEXT,
            xml_ubl TEXT,
            estado_dian TEXT,
            track_id TEXT,
            mensaje_dian TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (factura_id)
                REFERENCES facturas (id)
        );

        CREATE TABLE IF NOT EXISTS lineas_nota_credito (
            id SERIAL PRIMARY KEY,
            nota_credito_id INTEGER NOT NULL,
            producto_codigo TEXT,
            descripcion TEXT NOT NULL,
            cantidad TEXT,
            valor_unitario TEXT,
            subtotal TEXT,
            tarifa_iva TEXT,
            valor_iva TEXT,
            FOREIGN KEY (nota_credito_id)
                REFERENCES notas_credito (id)
                ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS recibos_caja (
            id SERIAL PRIMARY KEY,
            numero TEXT NOT NULL UNIQUE,
            fecha TEXT NOT NULL,
            cliente_nit TEXT NOT NULL,
            factura_id INTEGER NOT NULL,
            monto TEXT NOT NULL,
            medio_pago TEXT NOT NULL,
            referencia TEXT,
            observaciones TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (factura_id)
                REFERENCES facturas (id)
        );

        CREATE TABLE IF NOT EXISTS documentos_soporte (
            id SERIAL PRIMARY KEY,
            empresa_id INTEGER NOT NULL,
            consecutivo TEXT NOT NULL,
            prefijo TEXT,
            fecha TEXT NOT NULL,
            hora TEXT,
            proveedor_nit TEXT NOT NULL,
            proveedor_nombre TEXT NOT NULL,
            subtotal TEXT,
            retefuente TEXT,
            reteica TEXT,
            total_documento TEXT,
            cuds TEXT,
            qr TEXT,
            xml_ubl TEXT,
            estado_dian TEXT,
            track_id TEXT,
            mensaje_dian TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS lineas_documento_soporte (
            id SERIAL PRIMARY KEY,
            documento_soporte_id INTEGER NOT NULL,
            descripcion TEXT NOT NULL,
            cantidad TEXT,
            valor_unitario TEXT,
            subtotal TEXT,
            FOREIGN KEY (documento_soporte_id)
                REFERENCES documentos_soporte (id)
                ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS empleados (
            id SERIAL PRIMARY KEY,
            tipo_documento TEXT NOT NULL,
            documento TEXT NOT NULL UNIQUE,
            nombres TEXT NOT NULL,
            apellidos TEXT NOT NULL,
            salario_base TEXT NOT NULL,
            auxilio_transporte TEXT DEFAULT '0.00',
            activo INTEGER DEFAULT 1,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS nominas (
            id SERIAL PRIMARY KEY,
            consecutivo TEXT NOT NULL UNIQUE,
            prefijo TEXT DEFAULT 'NOM',
            periodo_inicio TEXT NOT NULL,
            periodo_fin TEXT NOT NULL,
            empleado_id INTEGER NOT NULL,
            total_devengado TEXT NOT NULL,
            total_deducciones TEXT NOT NULL,
            neto_pagar TEXT NOT NULL,
            cune TEXT,
            xml_ubl TEXT,
            estado_dian TEXT DEFAULT 'SIN_EMITIR',
            estado_pago TEXT DEFAULT 'PENDIENTE',
            track_id TEXT,
            mensaje_dian TEXT,
            fecha_emision TEXT,
            hora_emision TEXT,
            -- Componentes del comprobante. Antes el motor calculaba 14 valores
            -- y guardar_nomina solo persistía 3: el resto se descartaba en
            -- silencio y el CUNE no era auditable contra sus componentes.
            salario_base TEXT DEFAULT '0.00',
            auxilio_transporte TEXT DEFAULT '0.00',
            total_horas_extras TEXT DEFAULT '0.00',
            bonificaciones TEXT DEFAULT '0.00',
            recargo_nocturno TEXT DEFAULT '0.00',
            recargo_dominical TEXT DEFAULT '0.00',
            recargo_festivo TEXT DEFAULT '0.00',
            cesantias TEXT DEFAULT '0.00',
            intereses_cesantias TEXT DEFAULT '0.00',
            prima_servicios TEXT DEFAULT '0.00',
            vacaciones TEXT DEFAULT '0.00',
            ded_salud TEXT DEFAULT '0.00',
            ded_pension TEXT DEFAULT '0.00',
            ded_retencion TEXT DEFAULT '0.00',
            empleador_salud TEXT DEFAULT '0.00',
            empleador_pension TEXT DEFAULT '0.00',
            empleador_arl TEXT DEFAULT '0.00',
            empleador_sena TEXT DEFAULT '0.00',
            empleador_icbf TEXT DEFAULT '0.00',
            empleador_caja TEXT DEFAULT '0.00',
            ibc TEXT DEFAULT '0.00',
            total_cargas TEXT DEFAULT '0.00',
            total_comprobante TEXT DEFAULT '0.00',
            created_at TEXT NOT NULL,
            FOREIGN KEY (empleado_id)
                REFERENCES empleados (id)
        );

        CREATE TABLE IF NOT EXISTS eventos_radian (
            id SERIAL PRIMARY KEY,
            factura_id INTEGER NOT NULL,
            tipo_evento TEXT NOT NULL,
            codigo_evento TEXT NOT NULL,
            cude_evento TEXT,
            xml_ubl TEXT,
            estado_dian TEXT DEFAULT 'EXITOSA',
            fecha_evento TEXT,
            hora_evento TEXT,
            track_id TEXT,
            mensaje_dian TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (factura_id)
                REFERENCES facturas (id)
        );

        CREATE TABLE IF NOT EXISTS notas_debito (
            id SERIAL PRIMARY KEY,
            empresa_id INTEGER NOT NULL,
            consecutivo TEXT NOT NULL,
            prefijo TEXT,
            fecha TEXT NOT NULL,
            hora TEXT,
            factura_id INTEGER NOT NULL,
            factura_consecutivo TEXT,
            cufe_factura TEXT,
            cliente_nit TEXT NOT NULL,
            concepto_dian TEXT NOT NULL,
            descripcion_motivo TEXT,
            subtotal TEXT,
            total_iva TEXT,
            total_nota TEXT,
            cude TEXT,
            qr TEXT,
            estado_dian TEXT DEFAULT 'EXITOSA',
            track_id TEXT,
            mensaje_dian TEXT,
            xml_ubl TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (factura_id)
                REFERENCES facturas (id)
        );

        CREATE TABLE IF NOT EXISTS lineas_nota_debito (
            id SERIAL PRIMARY KEY,
            nota_debito_id INTEGER NOT NULL,
            producto_codigo TEXT,
            descripcion TEXT NOT NULL,
            cantidad TEXT,
            valor_unitario TEXT,
            subtotal TEXT,
            tarifa_iva TEXT,
            valor_iva TEXT,
            FOREIGN KEY (nota_debito_id)
                REFERENCES notas_debito (id)
                ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS usuarios (
            id SERIAL PRIMARY KEY,
            email TEXT NOT NULL UNIQUE,
            nombre TEXT NOT NULL,
            rol TEXT NOT NULL,
            hash_password TEXT NOT NULL,
            salt TEXT NOT NULL,
            activo INTEGER DEFAULT 1,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS periodos_contables (
            periodo TEXT PRIMARY KEY,
            estado TEXT NOT NULL DEFAULT 'ABIERTO',
            cerrado_por INTEGER,
            fecha_cierre TEXT,
            justificacion TEXT,
            FOREIGN KEY (cerrado_por)
                REFERENCES usuarios (id)
        );

        CREATE TABLE IF NOT EXISTS roles (
            id SERIAL PRIMARY KEY,
            nombre TEXT NOT NULL UNIQUE,
            descripcion TEXT,
            activo INTEGER DEFAULT 1,
            creado_por INTEGER,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS permisos (
            id SERIAL PRIMARY KEY,
            recurso TEXT NOT NULL,
            accion TEXT NOT NULL,
            UNIQUE (recurso, accion)
        );

        CREATE TABLE IF NOT EXISTS role_permissions (
            role_id INTEGER NOT NULL,
            permission_id INTEGER NOT NULL,
            PRIMARY KEY (role_id, permission_id),
            FOREIGN KEY (role_id) REFERENCES roles (id) ON DELETE CASCADE,
            FOREIGN KEY (permission_id) REFERENCES permisos (id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS config (
            clave TEXT PRIMARY KEY,
            valor TEXT
        );

        CREATE TABLE IF NOT EXISTS parametros_tributarios (
            clave TEXT NOT NULL,
            anio INTEGER NOT NULL,
            valor TEXT NOT NULL,
            descripcion TEXT,
            PRIMARY KEY (clave, anio)
        );

        CREATE TABLE IF NOT EXISTS auditoria (
            id SERIAL PRIMARY KEY,
            usuario_id INTEGER,
            email TEXT,
            evento TEXT NOT NULL,
            detalle TEXT,
            ip TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (usuario_id) REFERENCES usuarios (id)
        );

        CREATE TABLE IF NOT EXISTS facturas_compra (
            id SERIAL PRIMARY KEY,
            empresa_id INTEGER NOT NULL,
            proveedor_nit TEXT NOT NULL,
            proveedor_nombre TEXT,
            prefijo TEXT,
            consecutivo TEXT NOT NULL,
            fecha TEXT NOT NULL,
            fecha_vencimiento TEXT,
            cufe TEXT,
            subtotal TEXT DEFAULT '0.00',
            iva_19 TEXT DEFAULT '0.00',
            iva_5 TEXT DEFAULT '0.00',
            iva_0 TEXT DEFAULT '0.00',
            total_iva TEXT DEFAULT '0.00',
            retefuente TEXT DEFAULT '0.00',
            reteica TEXT DEFAULT '0.00',
            reteiva TEXT DEFAULT '0.00',
            total TEXT DEFAULT '0.00',
            estado_radian TEXT DEFAULT 'PENDIENTE',
            xml_contenido TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS cuentas_por_pagar (
            id SERIAL PRIMARY KEY,
            empresa_id INTEGER NOT NULL,
            factura_compra_id INTEGER,
            proveedor_nit TEXT NOT NULL,
            monto_total TEXT NOT NULL,
            saldo_pendiente TEXT NOT NULL,
            fecha_emision TEXT,
            fecha_vencimiento TEXT,
            estado TEXT DEFAULT 'PENDIENTE',
            created_at TEXT NOT NULL,
            FOREIGN KEY (factura_compra_id) REFERENCES facturas_compra (id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS comprobantes_egreso (
            id SERIAL PRIMARY KEY,
            empresa_id INTEGER NOT NULL,
            consecutivo TEXT NOT NULL,
            fecha TEXT NOT NULL,
            proveedor_nit TEXT NOT NULL,
            proveedor_nombre TEXT,
            monto TEXT NOT NULL,
            medio_pago TEXT NOT NULL,
            cuenta_origen TEXT DEFAULT '111005',
            factura_compra_id INTEGER,
            observaciones TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (factura_compra_id) REFERENCES facturas_compra (id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS cotizaciones (
            id SERIAL PRIMARY KEY,
            empresa_id INTEGER NOT NULL,
            usuario_id INTEGER,
            consecutivo TEXT NOT NULL,
            cliente_nit TEXT NOT NULL,
            fecha TEXT NOT NULL,
            fecha_vencimiento TEXT,
            subtotal TEXT DEFAULT '0.00',
            iva TEXT DEFAULT '0.00',
            total TEXT DEFAULT '0.00',
            descuento_porcentaje TEXT DEFAULT '0.00',
            estado TEXT DEFAULT 'COTIZADO',
            aprobado_por INTEGER,
            lineas TEXT,
            observaciones TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS pedidos_venta (
            id SERIAL PRIMARY KEY,
            empresa_id INTEGER NOT NULL,
            usuario_id INTEGER,
            consecutivo TEXT NOT NULL,
            cotizacion_id INTEGER,
            cliente_nit TEXT NOT NULL,
            fecha TEXT NOT NULL,
            subtotal TEXT DEFAULT '0.00',
            iva TEXT DEFAULT '0.00',
            total TEXT DEFAULT '0.00',
            estado TEXT DEFAULT 'PENDIENTE',
            aprobado_por INTEGER,
            lineas TEXT,
            observaciones TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (cotizacion_id) REFERENCES cotizaciones (id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS remisiones_venta (
            id SERIAL PRIMARY KEY,
            empresa_id INTEGER NOT NULL,
            consecutivo TEXT NOT NULL,
            pedido_id INTEGER,
            cliente_nit TEXT NOT NULL,
            fecha TEXT NOT NULL,
            lineas TEXT,
            observaciones TEXT,
            estado TEXT DEFAULT 'ENTREGADO',
            created_at TEXT NOT NULL,
            FOREIGN KEY (pedido_id) REFERENCES pedidos_venta (id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS pos_cajas (
            id SERIAL PRIMARY KEY,
            empresa_id INTEGER NOT NULL,
            nombre TEXT NOT NULL,
            ubicacion TEXT,
            activa INTEGER DEFAULT 1,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS pos_sesiones (
            id SERIAL PRIMARY KEY,
            caja_id INTEGER NOT NULL,
            usuario_id INTEGER,
            fecha_apertura TEXT NOT NULL,
            fecha_cierre TEXT,
            monto_inicial TEXT DEFAULT '0.00',
            total_ventas_efectivo TEXT DEFAULT '0.00',
            total_ventas_tarjeta TEXT DEFAULT '0.00',
            total_ventas_transferencia TEXT DEFAULT '0.00',
            total_esperado TEXT DEFAULT '0.00',
            total_real TEXT DEFAULT '0.00',
            diferencia TEXT DEFAULT '0.00',
            estado TEXT DEFAULT 'ABIERTA',
            observaciones TEXT,
            FOREIGN KEY (caja_id) REFERENCES pos_cajas (id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS listas_precios (
            id SERIAL PRIMARY KEY,
            empresa_id INTEGER NOT NULL,
            nombre TEXT NOT NULL,
            descripcion TEXT,
            activa INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS precios_productos (
            id SERIAL PRIMARY KEY,
            lista_id INTEGER NOT NULL,
            producto_codigo TEXT NOT NULL,
            precio TEXT NOT NULL,
            FOREIGN KEY (lista_id) REFERENCES listas_precios (id) ON DELETE CASCADE,
            UNIQUE (lista_id, producto_codigo)
        );

        CREATE TABLE IF NOT EXISTS usuario_empresas (
            usuario_id INTEGER NOT NULL REFERENCES usuarios (id) ON DELETE CASCADE,
            empresa_id INTEGER NOT NULL REFERENCES empresas (id) ON DELETE CASCADE,
            rol_en_empresa TEXT NOT NULL DEFAULT 'ADMIN_EMPRESA',
            es_predeterminada INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            PRIMARY KEY (usuario_id, empresa_id)
        );
    """


def get_active_dsn() -> str:
    return os.environ.get("SAP_PG_DSN") or _sap_config.pg_dsn()


def get_active_dbname() -> str:
    dsn = get_active_dsn()
    try:
        from urllib.parse import urlparse
        p = urlparse(dsn)
        return p.path.lstrip("/") or "sap_colombia"
    except Exception:
        return "sap_colombia"


def get_connection() -> psycopg2.extensions.connection:
    # Conectar a PostgreSQL usando el DSN activo dinámico
    dsn = get_active_dsn()
    connection = dbutil.get_conn(dsn)
    return connection


_tls = threading.local()

def get_active_connection() -> psycopg2.extensions.connection:
    return getattr(_tls, "conn", None)

def _set_active_connection(conn: psycopg2.extensions.connection | None) -> None:
    if conn is None:
        if hasattr(_tls, "conn"):
            del _tls.conn
    else:
        _tls.conn = conn

def get_current_empresa_id() -> int | None:
    """Retorna el empresa_id del tenant actual o None si no está establecido."""
    return getattr(_tls, "empresa_id", None)

def set_current_empresa_id(empresa_id: int | None) -> None:
    """Establece el empresa_id del tenant actual."""
    if empresa_id is None:
        if hasattr(_tls, "empresa_id"):
            del _tls.empresa_id
    else:
        _tls.empresa_id = empresa_id

@contextmanager
def tenant_scope(empresa_id: int):
    """Context manager que establece el tenant actual para el scope."""
    old = get_current_empresa_id()
    set_current_empresa_id(empresa_id)
    try:
        yield empresa_id
    finally:
        set_current_empresa_id(old)

@contextmanager
def transactional_scope():
    _set_active_connection(None)
    conn = get_connection()
    try:
        _set_active_connection(conn)
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        _set_active_connection(None)
        conn.close()


def _valor_sql(valor):
    return None if valor is None else str(valor)


def _insert_rows(conn: psycopg2.extensions.connection, table: str, registros: list[dict]) -> None:
    if not registros:
        return
    for registro in registros:
        columnas = list(registro.keys())
        nombres = ", ".join(columnas)
        marcadores = ", ".join("?" for _ in columnas)
        valores = [_valor_sql(registro[col]) for col in columnas]
        dbutil.query(conn, 
            f"INSERT INTO {table} ({nombres}) VALUES ({marcadores})",
            valores,
        )


def _seed_puc(conn: psycopg2.extensions.connection) -> None:
    cuentas = [
        # ==================== ACTIVO (1xxx) ====================
        {"codigo": "110505", "nombre": "Caja General", "naturaleza": "DEBITO", "nivel": 3, "categoria": "ACTIVO"},
        {"codigo": "110510", "nombre": "Caja Chica", "naturaleza": "DEBITO", "nivel": 3, "categoria": "ACTIVO"},
        {"codigo": "111005", "nombre": "Bancos Nacionales Moneda Local", "naturaleza": "DEBITO", "nivel": 3, "categoria": "ACTIVO"},
        {"codigo": "111010", "nombre": "Bancos Nacionales Moneda Extranjera", "naturaleza": "DEBITO", "nivel": 3, "categoria": "ACTIVO"},
        {"codigo": "112501", "nombre": "Cuentas por Cobrar a Corto Plazo", "naturaleza": "DEBITO", "nivel": 3, "categoria": "ACTIVO"},
        {"codigo": "120505", "nombre": "Deuda de Corto Plazo por Cobrar", "naturaleza": "DEBITO", "nivel": 3, "categoria": "ACTIVO"},
        {"codigo": "130501", "nombre": "Clientes Extranjeros", "naturaleza": "DEBITO", "nivel": 3, "categoria": "ACTIVO"},
        {"codigo": "130505", "nombre": "Clientes Nacionales", "naturaleza": "DEBITO", "nivel": 3, "categoria": "ACTIVO"},
        {"codigo": "130510", "nombre": "Clientes - Deuda por Cobrar", "naturaleza": "DEBITO", "nivel": 3, "categoria": "ACTIVO"},
        {"codigo": "131005", "nombre": "Deuda por Cobrar a Corto Plazo", "naturaleza": "DEBITO", "nivel": 3, "categoria": "ACTIVO"},
        {"codigo": "131501", "nombre": "Crédito por Descontar", "naturaleza": "DEBITO", "nivel": 3, "categoria": "ACTIVO"},
        {"codigo": "135515", "nombre": "Anticipo de Impuestos: Retención en la Fuente", "naturaleza": "DEBITO", "nivel": 3, "categoria": "ACTIVO"},
        {"codigo": "135517", "nombre": "Anticipo de Impuestos: Retención de IVA (ReteIVA)", "naturaleza": "DEBITO", "nivel": 3, "categoria": "ACTIVO"},
        {"codigo": "135518", "nombre": "Anticipo de Impuestos: Retención de ICA (ReteICA)", "naturaleza": "DEBITO", "nivel": 3, "categoria": "ACTIVO"},
        {"codigo": "135520", "nombre": "Anticipo de Impuestos: Impuesto de Renta", "naturaleza": "DEBITO", "nivel": 3, "categoria": "ACTIVO"},
        {"codigo": "136001", "nombre": "Cuentas por Cobrar por Servicios Prestados", "naturaleza": "DEBITO", "nivel": 3, "categoria": "ACTIVO"},
        {"codigo": "143501", "nombre": "Mercancías no Fabricadas por la Empresa (Inventario)", "naturaleza": "DEBITO", "nivel": 3, "categoria": "ACTIVO"},
        {"codigo": "143510", "nombre": "Insumos y Materiales (Inventario)", "naturaleza": "DEBITO", "nivel": 3, "categoria": "ACTIVO"},
        {"codigo": "144001", "nombre": "Productos en Proceso", "naturaleza": "DEBITO", "nivel": 3, "categoria": "ACTIVO"},
        {"codigo": "144501", "nombre": "Productos Terminados", "naturaleza": "DEBITO", "nivel": 3, "categoria": "ACTIVO"},
        {"codigo": "150501", "nombre": "Inversiones a Corto Plazo", "naturaleza": "DEBITO", "nivel": 3, "categoria": "ACTIVO"},
        {"codigo": "160505", "nombre": "Herramientas y Equipo Menor", "naturaleza": "DEBITO", "nivel": 3, "categoria": "ACTIVO"},
        {"codigo": "161005", "nombre": "Muebles y Enseres de Oficina", "naturaleza": "DEBITO", "nivel": 3, "categoria": "ACTIVO"},
        {"codigo": "161501", "nombre": "Equipo de Cómputo", "naturaleza": "DEBITO", "nivel": 3, "categoria": "ACTIVO"},
        {"codigo": "162001", "nombre": "Vehículos y Maquinaria", "naturaleza": "DEBITO", "nivel": 3, "categoria": "ACTIVO"},
        {"codigo": "169901", "nombre": "Otros Activos Fijos", "naturaleza": "DEBITO", "nivel": 3, "categoria": "ACTIVO"},
        {"codigo": "170501", "nombre": "Depreciación Acumulada - Inmuebles", "naturaleza": "CREDITO", "nivel": 3, "categoria": "ACTIVO"},
        {"codigo": "171001", "nombre": "Depreciación Acumulada - Maquinaria", "naturaleza": "CREDITO", "nivel": 3, "categoria": "ACTIVO"},
        {"codigo": "171501", "nombre": "Depreciación Acumulada - Muebles y Enseres", "naturaleza": "CREDITO", "nivel": 3, "categoria": "ACTIVO"},
        {"codigo": "172001", "nombre": "Depreciación Acumulada - Equipo de Cómputo", "naturaleza": "CREDITO", "nivel": 3, "categoria": "ACTIVO"},

        # ==================== PASIVO (2xxx) ====================
        {"codigo": "210501", "nombre": "Deuda Bancaria a Corto Plazo", "naturaleza": "CREDITO", "nivel": 3, "categoria": "PASIVO"},
        {"codigo": "210505", "nombre": "Deuda Bancaria a Largo Plazo (Corriente)", "naturaleza": "CREDITO", "nivel": 3, "categoria": "PASIVO"},
        {"codigo": "220505", "nombre": "Proveedores Nacionales", "naturaleza": "CREDITO", "nivel": 3, "categoria": "PASIVO"},
        {"codigo": "221001", "nombre": "Proveedores Extranjeros", "naturaleza": "CREDITO", "nivel": 3, "categoria": "PASIVO"},
        {"codigo": "230501", "nombre": "Deuda por Prestaciones Sociales", "naturaleza": "CREDITO", "nivel": 3, "categoria": "PASIVO"},
        {"codigo": "236540", "nombre": "Retención en la Fuente por Pagar (Compras/Servicios)", "naturaleza": "CREDITO", "nivel": 3, "categoria": "PASIVO"},
        {"codigo": "236801", "nombre": "Retención de ICA por Pagar", "naturaleza": "CREDITO", "nivel": 3, "categoria": "PASIVO"},
        {"codigo": "236802", "nombre": "ReteIVA por Pagar", "naturaleza": "CREDITO", "nivel": 3, "categoria": "PASIVO"},
        {"codigo": "237005", "nombre": "Aportes a Salud EPS por Pagar", "naturaleza": "CREDITO", "nivel": 3, "categoria": "PASIVO"},
        {"codigo": "238030", "nombre": "Aportes a Pension por Pagar", "naturaleza": "CREDITO", "nivel": 3, "categoria": "PASIVO"},
        {"codigo": "239001", "nombre": "Aportes Patronales por Pagar", "naturaleza": "CREDITO", "nivel": 3, "categoria": "PASIVO"},
        {"codigo": "240801", "nombre": "Impuesto sobre las Ventas por Pagar (IVA 19% Generado)", "naturaleza": "CREDITO", "nivel": 3, "categoria": "PASIVO"},
        {"codigo": "240802", "nombre": "Impuesto sobre las Ventas por Pagar (IVA 5% Generado)", "naturaleza": "CREDITO", "nivel": 3, "categoria": "PASIVO"},
        {"codigo": "240810", "nombre": "IVA por Pagar - Netos", "naturaleza": "CREDITO", "nivel": 3, "categoria": "PASIVO"},
        {"codigo": "250505", "nombre": "Salarios por Pagar - Neto", "naturaleza": "CREDITO", "nivel": 3, "categoria": "PASIVO"},
        {"codigo": "251001", "nombre": "Comisiones por Pagar", "naturaleza": "CREDITO", "nivel": 3, "categoria": "PASIVO"},
        {"codigo": "260501", "nombre": "Intereses por Pagar", "naturaleza": "CREDITO", "nivel": 3, "categoria": "PASIVO"},
        {"codigo": "270501", "nombre": "Deuda por Pagar a Socio", "naturaleza": "CREDITO", "nivel": 3, "categoria": "PASIVO"},
        {"codigo": "280501", "nombre": "Deuda Fiscal por Pagar", "naturaleza": "CREDITO", "nivel": 3, "categoria": "PASIVO"},
        {"codigo": "290501", "nombre": "Otros Pasivos a Corto Plazo", "naturaleza": "CREDITO", "nivel": 3, "categoria": "PASIVO"},

        # ==================== PATRIMONIO (3xxx) ====================
        {"codigo": "310501", "nombre": "Capital Social", "naturaleza": "CREDITO", "nivel": 3, "categoria": "PATRIMONIO"},
        {"codigo": "310505", "nombre": "Capital Social - Capital de Giro", "naturaleza": "CREDITO", "nivel": 3, "categoria": "PATRIMONIO"},
        {"codigo": "311001", "nombre": "Reserva Legal", "naturaleza": "CREDITO", "nivel": 3, "categoria": "PATRIMONIO"},
        {"codigo": "311501", "nombre": "Reservas por Aportaciones", "naturaleza": "CREDITO", "nivel": 3, "categoria": "PATRIMONIO"},
        {"codigo": "312001", "nombre": "Utilidades o Pérdidas a Distribuir", "naturaleza": "CREDITO", "nivel": 3, "categoria": "PATRIMONIO"},
        {"codigo": "312501", "nombre": "Utilidades o Pérdidas del Ejercicio", "naturaleza": "CREDITO", "nivel": 3, "categoria": "PATRIMONIO"},

        # ==================== INGRESOS (4xxx) ====================
        {"codigo": "413501", "nombre": "Ingresos Operacionales - Comercio al por Mayor y Menor", "naturaleza": "CREDITO", "nivel": 3, "categoria": "INGRESOS"},
        {"codigo": "413505", "nombre": "Ingresos por Servicios Prestados", "naturaleza": "CREDITO", "nivel": 3, "categoria": "INGRESOS"},
        {"codigo": "413510", "nombre": "Ingresos por Arrendamiento", "naturaleza": "CREDITO", "nivel": 3, "categoria": "INGRESOS"},
        {"codigo": "413520", "nombre": "Ingresos Financieros", "naturaleza": "CREDITO", "nivel": 3, "categoria": "INGRESOS"},
        {"codigo": "414501", "nombre": "Ingresos por Intereses Corridos", "naturaleza": "CREDITO", "nivel": 3, "categoria": "INGRESOS"},
        {"codigo": "417505", "nombre": "Devoluciones en Ventas", "naturaleza": "DEBITO", "nivel": 3, "categoria": "INGRESOS"},
        {"codigo": "417510", "nombre": "Descuentos en Ventas", "naturaleza": "DEBITO", "nivel": 3, "categoria": "INGRESOS"},
        {"codigo": "417520", "nombre": "Devoluciones y Devengos en Ventas", "naturaleza": "DEBITO", "nivel": 3, "categoria": "INGRESOS"},
        {"codigo": "420501", "nombre": "Otros Ingresos", "naturaleza": "CREDITO", "nivel": 3, "categoria": "INGRESOS"},

        # ==================== GASTOS (5xxx) ====================
        {"codigo": "510501", "nombre": "Sueldos y Salarios - Gerencia", "naturaleza": "DEBITO", "nivel": 3, "categoria": "GASTOS"},
        {"codigo": "510506", "nombre": "Sueldos y Salarios", "naturaleza": "DEBITO", "nivel": 3, "categoria": "GASTOS"},
        {"codigo": "510527", "nombre": "Auxilio de Transporte", "naturaleza": "DEBITO", "nivel": 3, "categoria": "GASTOS"},
        {"codigo": "511001", "nombre": "Servicios de Salud", "naturaleza": "DEBITO", "nivel": 3, "categoria": "GASTOS"},
        {"codigo": "513501", "nombre": "Gastos Operacionales - Servicios y Compras Generales", "naturaleza": "DEBITO", "nivel": 3, "categoria": "GASTOS"},
        {"codigo": "513505", "nombre": "Gastos Operacionales - Servicios Básicos", "naturaleza": "DEBITO", "nivel": 3, "categoria": "GASTOS"},
        {"codigo": "513510", "nombre": "Gastos Operacionales - Arrendamiento", "naturaleza": "DEBITO", "nivel": 3, "categoria": "GASTOS"},
        {"codigo": "514001", "nombre": "Gastos por Depreciación", "naturaleza": "DEBITO", "nivel": 3, "categoria": "GASTOS"},
        {"codigo": "514501", "nombre": "Gastos por Amortización", "naturaleza": "DEBITO", "nivel": 3, "categoria": "GASTOS"},
        {"codigo": "515001", "nombre": "Intereses Gastos Financieros", "naturaleza": "DEBITO", "nivel": 3, "categoria": "GASTOS"},
        {"codigo": "515501", "nombre": "Pérdida por Diferencias de Cambio", "naturaleza": "DEBITO", "nivel": 3, "categoria": "GASTOS"},
        {"codigo": "516001", "nombre": "Pérdidas por Inventario", "naturaleza": "DEBITO", "nivel": 3, "categoria": "GASTOS"},
        {"codigo": "517501", "nombre": "Gastos por Donaciones y Contribuciones", "naturaleza": "DEBITO", "nivel": 3, "categoria": "GASTOS"},
        {"codigo": "520501", "nombre": "Gastos por Impuestos y Contribuciones", "naturaleza": "DEBITO", "nivel": 3, "categoria": "GASTOS"},
        {"codigo": "521001", "nombre": "Gastos por Servicios Profesionales", "naturaleza": "DEBITO", "nivel": 3, "categoria": "GASTOS"},
        {"codigo": "521501", "nombre": "Gastos por Auditoría y Contaduría", "naturaleza": "DEBITO", "nivel": 3, "categoria": "GASTOS"},
        {"codigo": "530501", "nombre": "Costo de Ventas", "naturaleza": "DEBITO", "nivel": 3, "categoria": "GASTOS"},
        {"codigo": "531001", "nombre": "Costo de Merchancías Vendidas", "naturaleza": "DEBITO", "nivel": 3, "categoria": "GASTOS"},
        # --- Cuentas que exige el catálogo y faltaban ---
        {"codigo": "240801", "nombre": "Impuesto sobre las ventas por pagar - IVA 19%", "naturaleza": "CREDITO", "nivel": 3, "categoria": "PASIVO"},
        {"codigo": "240803", "nombre": "Impuesto sobre las ventas por pagar - IVA 0%", "naturaleza": "CREDITO", "nivel": 3, "categoria": "PASIVO"},
        {"codigo": "240805", "nombre": "Impuesto sobre las ventas por pagar - IVA 5%", "naturaleza": "CREDITO", "nivel": 3, "categoria": "PASIVO"},
        {"codigo": "240807", "nombre": "Retención de IVA practicada (ReteIVA por pagar)", "naturaleza": "CREDITO", "nivel": 3, "categoria": "PASIVO"},
        {"codigo": "240808", "nombre": "IVA descontable", "naturaleza": "DEBITO", "nivel": 3, "categoria": "ACTIVO"},
        {"codigo": "240809", "nombre": "IVA descontable en compras de bienes para consumo", "naturaleza": "DEBITO", "nivel": 3, "categoria": "ACTIVO"},
        {"codigo": "236505", "nombre": "Retención en la fuente por pagar", "naturaleza": "CREDITO", "nivel": 3, "categoria": "PASIVO"},
        {"codigo": "236802", "nombre": "Impuesto sobre las ventas retenido (ReteIVA)", "naturaleza": "CREDITO", "nivel": 3, "categoria": "PASIVO"},
        {"codigo": "237005", "nombre": "Salud - aportes de los empleadores", "naturaleza": "CREDITO", "nivel": 3, "categoria": "PASIVO"},
        {"codigo": "238030", "nombre": "AFP - aportes de los empleadores", "naturaleza": "CREDITO", "nivel": 3, "categoria": "PASIVO"},
        {"codigo": "239001", "nombre": "Aportes parafiscales (SENA, ICBF, caja)", "naturaleza": "CREDITO", "nivel": 3, "categoria": "PASIVO"},
        {"codigo": "243505", "nombre": "Retención de ICA por pagar", "naturaleza": "CREDITO", "nivel": 3, "categoria": "PASIVO"},
        {"codigo": "250525", "nombre": "Intereses sobre cesantías por pagar", "naturaleza": "CREDITO", "nivel": 3, "categoria": "PASIVO"},
        {"codigo": "251005", "nombre": "Cesantías consolidadas", "naturaleza": "CREDITO", "nivel": 3, "categoria": "PASIVO"},
        {"codigo": "251525", "nombre": "Vacaciones consolidadas", "naturaleza": "CREDITO", "nivel": 3, "categoria": "PASIVO"},
        {"codigo": "413595", "nombre": "Ajuste de inventario - sobrantes (ingreso no operacional)", "naturaleza": "CREDITO", "nivel": 3, "categoria": "INGRESOS"},
        {"codigo": "511595", "nombre": "Ajuste de inventario - faltantes (gasto no operacional)", "naturaleza": "DEBITO", "nivel": 3, "categoria": "GASTOS"},
        {"codigo": "511110", "nombre": "Cesantías", "naturaleza": "DEBITO", "nivel": 3, "categoria": "GASTOS"},
        {"codigo": "511120", "nombre": "Intereses sobre cesantías", "naturaleza": "DEBITO", "nivel": 3, "categoria": "GASTOS"},
        {"codigo": "511130", "nombre": "Prima de servicios", "naturaleza": "DEBITO", "nivel": 3, "categoria": "GASTOS"},
        {"codigo": "541120", "nombre": "ARL - Aportes al Sistema General de Riesgos Laborales", "naturaleza": "DEBITO", "nivel": 3, "categoria": "GASTOS"},
        {"codigo": "542510", "nombre": "Aportes al SENA", "naturaleza": "DEBITO", "nivel": 3, "categoria": "GASTOS"},
        {"codigo": "542520", "nombre": "Aportes al ICBF", "naturaleza": "DEBITO", "nivel": 3, "categoria": "GASTOS"},
        {"codigo": "542530", "nombre": "Aportes a cajas de compensación familiar", "naturaleza": "DEBITO", "nivel": 3, "categoria": "GASTOS"},
        # --- Cuentas de nómina (prestaciones y aportes patronales) ---
        {"codigo": "510506", "nombre": "Sueldos y salarios", "naturaleza": "DEBITO", "nivel": 3, "categoria": "GASTOS"},
        {"codigo": "510527", "nombre": "Auxilio de transporte", "naturaleza": "DEBITO", "nivel": 3, "categoria": "GASTOS"},
        {"codigo": "512510", "nombre": "Vacaciones", "naturaleza": "DEBITO", "nivel": 3, "categoria": "GASTOS"},
        {"codigo": "512520", "nombre": "Indemnizaciones", "naturaleza": "DEBITO", "nivel": 3, "categoria": "GASTOS"},
        {"codigo": "512525", "nombre": "Ajuste de nómina por redondeo", "naturaleza": "CREDITO", "nivel": 3, "categoria": "GASTOS"},
        {"codigo": "513520", "nombre": "Aportes patronales de pensión", "naturaleza": "DEBITO", "nivel": 3, "categoria": "GASTOS"},
        {"codigo": "513530", "nombre": "Aportes patronales de salud", "naturaleza": "DEBITO", "nivel": 3, "categoria": "GASTOS"},
    ]
    for c in cuentas:
        dbutil.query(conn, 
            """INSERT INTO plan_cuentas (codigo, nombre, naturaleza, nivel, categoria, activa)
               VALUES (?, ?, ?, ?, ?, 1) ON CONFLICT (codigo) DO UPDATE
               SET nombre = EXCLUDED.nombre""",
            (c["codigo"], c["nombre"], c["naturaleza"], c["nivel"], c["categoria"]),
        )


def _seed_datos(conn: psycopg2.extensions.connection) -> None:
    if dbutil.query(conn, "SELECT COUNT(*) AS total FROM empresas").fetchone()["total"] == 0:
        _insert_rows(
            conn,
            "empresas",
            [
                {
                    "nit": "90012345678",
                    "dv": "1",
                    "razon_social": "Empresa Corporativa S.A.S.",
                    "nombre_marca": "ERP",
                    "direccion": "Cra 15 # 45-30, PBX 12",
                    "municipio": "Bogotá D.C.",
                    "departamento": "Cundinamarca",
                    "prefijo_resolucion": "SETP",
                    "resolucion_dian": "18760000001",
                    "fecha_resolucion": "2026-01-15",
                    "rango_desde": 990000000,
                    "rango_hasta": 999999999,
                    "clave_tecnica": "3fa9c0b1d2e34f5a6b7c8d9e0f1a2b3c",
                    "tipo_ambiente": "1",
                    "color_primario": "#2563eb",
                    "color_secundario": "#1d4ed8",
                    "color_sidebar": "#0f172a",
                    "color_fondo": "#f1f5f9",
                    "fuente_nombre": "Inter",
                }
            ],
        )

    emp_row = dbutil.query(conn, "SELECT id FROM empresas ORDER BY id LIMIT 1").fetchone()
    emp_id = emp_row["id"] if emp_row else 1

    if dbutil.query(conn, "SELECT COUNT(*) AS total FROM clientes").fetchone()["total"] == 0:
        _insert_rows(
            conn,
            "clientes",
            [
                {
                    "empresa_id": emp_id,
                    "nit": "800197268",
                    "dv": "4",
                    "tipo_documento": "NIT",
                    "razon_social": "Distribuidora del Café S.A.S.",
                    "direccion": "Calle 26 # 68C-61",
                    "municipio": "Bogotá D.C.",
                    "email": "facturacion@districafe.com.co",
                    "telefono": "6013142589",
                    "regimen_fiscal": "Responsable IVA",
                },
                {
                    "empresa_id": emp_id,
                    "nit": "900876543",
                    "dv": "8",
                    "tipo_documento": "NIT",
                    "razon_social": "Comercializadora Caribe S.A.",
                    "direccion": "Cra 52 # 74-56",
                    "municipio": "Barranquilla",
                    "email": "contabilidad@caribesa.com.co",
                    "telefono": "6053851234",
                    "regimen_fiscal": "Responsable IVA",
                },
                {
                    "empresa_id": emp_id,
                    "nit": "1234567890",
                    "dv": "9",
                    "tipo_documento": "CC",
                    "razon_social": "Carlos Eduardo Rodríguez",
                    "direccion": "Carrera 7 # 12-45",
                    "municipio": "Cali",
                    "email": "carlos.rodriguez@email.com",
                    "telefono": "3154879512",
                    "regimen_fiscal": "No Responsable IVA",
                },
                {
                    "empresa_id": emp_id,
                    "nit": "1111111111",
                    "dv": "2",
                    "tipo_documento": "NIT",
                    "razon_social": "Tecnología y Redes del Norte S.A.S.",
                    "direccion": "Calle 100 # 19A-40",
                    "municipio": "Bogotá D.C.",
                    "email": "facturas@tecronorte.com.co",
                    "telefono": "6017456321",
                    "regimen_fiscal": "Responsable IVA",
                },
                {
                    "empresa_id": emp_id,
                    "nit": "2222222222",
                    "dv": "3",
                    "tipo_documento": "NIT",
                    "razon_social": "Servicios Andinos Ltda",
                    "direccion": "Av. El Poblado # 34-12",
                    "municipio": "Medellín",
                    "email": "administracion@andinos.com.co",
                    "telefono": "3201234567",
                    "regimen_fiscal": "Responsable IVA",
                },
            ],
        )

    if dbutil.query(conn, "SELECT COUNT(*) AS total FROM productos").fetchone()["total"] == 0:
        _insert_rows(
            conn,
            "productos",
            [
                {
                    "empresa_id": emp_id,
                    "codigo": "P001",
                    "descripcion": "Producto general con IVA 19%",
                    "precio_unitario": "100000.00",
                    "tarifa_iva": "IVA_19",
                    "tipo_bien_servicio": "BIENES",
                    "unidad_medida": "U",
                },
                {
                    "empresa_id": emp_id,
                    "codigo": "P002",
                    "descripcion": "Producto con IVA 5%",
                    "precio_unitario": "50000.00",
                    "tarifa_iva": "IVA_5",
                    "tipo_bien_servicio": "BIENES",
                    "unidad_medida": "U",
                },
                {
                    "empresa_id": emp_id,
                    "codigo": "P003",
                    "descripcion": "Servicio técnico mensual",
                    "precio_unitario": "200000.00",
                    "tarifa_iva": "IVA_19",
                    "tipo_bien_servicio": "SERVICIOS",
                    "unidad_medida": "H",
                },
                {
                    "empresa_id": emp_id,
                    "codigo": "P004",
                    "descripcion": "Arrendamiento de equipo",
                    "precio_unitario": "150000.00",
                    "tarifa_iva": "IVA_19",
                    "tipo_bien_servicio": "ARRENDAMIENTO",
                    "unidad_medida": "D",
                },
                {
                    "empresa_id": emp_id,
                    "codigo": "P005",
                    "descripcion": "Producto exento",
                    "precio_unitario": "50000.00",
                    "tarifa_iva": "IVA_0",
                    "tipo_bien_servicio": "EXENTO",
                    "unidad_medida": "U",
                },
            ],
        )

    # Seed system admin role
    dbutil.query(conn, 
        "INSERT INTO roles (nombre, descripcion, activo, tipo, created_at) VALUES (?, ?, 1, 'SISTEMA', ?) ON CONFLICT DO NOTHING",
        ("SUPERADMIN", "Administrador de Sistema Root", datetime.now().isoformat()),
    )
    dbutil.query(conn, 
        "INSERT INTO roles (nombre, descripcion, activo, tipo, created_at) VALUES (?, ?, 1, 'SISTEMA', ?) ON CONFLICT DO NOTHING",
        ("ADMIN_SISTEMA", "Administrador de Sistema", datetime.now().isoformat()),
    )


def _migrate_schema(conn: psycopg2.extensions.connection) -> None:
    # Certificados, contingencia DIAN y branding por empresa en empresas
    cols_emp = set(dbutil.table_columns(conn, 'empresas'))
    if "ruta_certificado" not in cols_emp:
        dbutil.query(conn, "ALTER TABLE empresas ADD COLUMN ruta_certificado TEXT")
    if "password_certificado" not in cols_emp:
        dbutil.query(conn, "ALTER TABLE empresas ADD COLUMN password_certificado TEXT")
    if "url_dian" not in cols_emp:
        dbutil.query(conn, "ALTER TABLE empresas ADD COLUMN url_dian TEXT")
    if "en_contingencia" not in cols_emp:
        dbutil.query(conn, "ALTER TABLE empresas ADD COLUMN en_contingencia INTEGER DEFAULT 0")
    if "motivo_contingencia" not in cols_emp:
        dbutil.query(conn, "ALTER TABLE empresas ADD COLUMN motivo_contingencia TEXT")
    if "fecha_contingencia" not in cols_emp:
        dbutil.query(conn, "ALTER TABLE empresas ADD COLUMN fecha_contingencia TEXT")
    if "nombre_marca" not in cols_emp:
        dbutil.query(conn, "ALTER TABLE empresas ADD COLUMN nombre_marca TEXT")
    if "logo_data" not in cols_emp:
        dbutil.query(conn, "ALTER TABLE empresas ADD COLUMN logo_data TEXT")
    if "color_primario" not in cols_emp:
        dbutil.query(conn, "ALTER TABLE empresas ADD COLUMN color_primario TEXT DEFAULT '#2563eb'")
    if "color_secundario" not in cols_emp:
        dbutil.query(conn, "ALTER TABLE empresas ADD COLUMN color_secundario TEXT DEFAULT '#1d4ed8'")
    if "color_sidebar" not in cols_emp:
        dbutil.query(conn, "ALTER TABLE empresas ADD COLUMN color_sidebar TEXT DEFAULT '#0f172a'")
    if "color_fondo" not in cols_emp:
        dbutil.query(conn, "ALTER TABLE empresas ADD COLUMN color_fondo TEXT DEFAULT '#f1f5f9'")
    if "fuente_nombre" not in cols_emp:
        dbutil.query(conn, "ALTER TABLE empresas ADD COLUMN fuente_nombre TEXT DEFAULT 'Inter'")
    if "fuente_data" not in cols_emp:
        dbutil.query(conn, "ALTER TABLE empresas ADD COLUMN fuente_data TEXT")

    # Asegurar que las columnas nuevas de cartera existan en facturas
    columnas_existentes = set(dbutil.table_columns(conn, 'facturas'))

    if "plazo_dias" not in columnas_existentes:
        dbutil.query(conn, "ALTER TABLE facturas ADD COLUMN plazo_dias INTEGER DEFAULT 30")
    if "fecha_vencimiento" not in columnas_existentes:
        dbutil.query(conn, "ALTER TABLE facturas ADD COLUMN fecha_vencimiento TEXT")
    if "saldo_pendiente" not in columnas_existentes:
        dbutil.query(conn, "ALTER TABLE facturas ADD COLUMN saldo_pendiente TEXT")
    if "estado_cartera" not in columnas_existentes:
        dbutil.query(conn, "ALTER TABLE facturas ADD COLUMN estado_cartera TEXT DEFAULT 'PENDIENTE'")
    if "application_response_xml" not in columnas_existentes:
        dbutil.query(conn, "ALTER TABLE facturas ADD COLUMN application_response_xml TEXT")
    if "attached_document_xml" not in columnas_existentes:
        dbutil.query(conn, "ALTER TABLE facturas ADD COLUMN attached_document_xml TEXT")

    # Umbral de stock mínimo para alertas del dashboard
    cols_prod = set(dbutil.table_columns(conn, 'productos'))
    if "stock_minimo" not in cols_prod:
        dbutil.query(conn, "ALTER TABLE productos ADD COLUMN stock_minimo INTEGER DEFAULT 0")

    # Rellenar saldos iniciales en facturas preexistentes
    dbutil.query(conn, 
        """UPDATE facturas 
            SET saldo_pendiente = total_factura, 
                estado_cartera = 'PENDIENTE',
                plazo_dias = 30
            WHERE saldo_pendiente IS NULL"""
    )

    # Columna de invalidación de tokens
    cols_usuarios = set(dbutil.table_columns(conn, 'usuarios'))
    if "password_changed_at" not in cols_usuarios:
        dbutil.query(conn, "ALTER TABLE usuarios ADD COLUMN password_changed_at TEXT")

    # Multi-tenancy: agregar empresa_id a tablas de negocio
    emp_row = dbutil.query(conn, "SELECT id FROM empresas ORDER BY id LIMIT 1").fetchone()
    default_emp_id = emp_row["id"] if emp_row else 1
    tablas_multitenant = (
        "clientes", "productos", "facturas", "notas_credito", "notas_debito",
        "documentos_soporte", "asientos_contables", "recibos_caja", "empleados",
        "nominas", "bodegas", "kardex", "stock_actual", "periodos_contables",
    )
    for tabla in tablas_multitenant:
        cols = set(dbutil.table_columns(conn, tabla))
        if "empresa_id" not in cols:
            dbutil.query(conn, f"ALTER TABLE {tabla} ADD COLUMN empresa_id INTEGER DEFAULT 1")
            # Asignar la primera empresa a registros existentes
            dbutil.query(conn, f"UPDATE {tabla} SET empresa_id = ? WHERE empresa_id IS NULL", (default_emp_id,))
        elif default_emp_id != 1:
            # Corregir registros heredados con empresa_id=1 cuando el id real difiere
            dbutil.query(conn, 
                f"UPDATE {tabla} SET empresa_id = ? WHERE (empresa_id IS NULL OR (empresa_id = 1 AND 1 NOT IN (SELECT id FROM empresas)))",
                (default_emp_id,),
            )
        else:
            dbutil.query(conn, f"UPDATE {tabla} SET empresa_id = ? WHERE empresa_id IS NULL", (default_emp_id,))

    # Crear tabla de contexto de tenant
    dbutil.query(conn, """
        CREATE TABLE IF NOT EXISTS tenant_context (
            empresa_id SERIAL PRIMARY KEY
        )
    """)

    # System admin: empresa_id in usuarios
    cols_usuarios = set(dbutil.table_columns(conn, 'usuarios'))
    if "empresa_id" not in cols_usuarios:
        dbutil.query(conn, "ALTER TABLE usuarios ADD COLUMN empresa_id INTEGER")

    # Pago de nómina: estado_pago y track_id
    cols_nominas = set(dbutil.table_columns(conn, 'nominas'))
    if "estado_pago" not in cols_nominas:
        dbutil.query(conn, "ALTER TABLE nominas ADD COLUMN estado_pago TEXT DEFAULT 'PENDIENTE'")
    # Componentes del comprobante de nómina (ver payroll.calcular_nomina).
    nuevas_nomina = {
        "mensaje_dian": "TEXT",
        "salario_base": "TEXT DEFAULT '0.00'",
        "auxilio_transporte": "TEXT DEFAULT '0.00'",
        "total_horas_extras": "TEXT DEFAULT '0.00'",
        "bonificaciones": "TEXT DEFAULT '0.00'",
        "recargo_nocturno": "TEXT DEFAULT '0.00'",
        "recargo_dominical": "TEXT DEFAULT '0.00'",
        "recargo_festivo": "TEXT DEFAULT '0.00'",
        "cesantias": "TEXT DEFAULT '0.00'",
        "intereses_cesantias": "TEXT DEFAULT '0.00'",
        "prima_servicios": "TEXT DEFAULT '0.00'",
        "vacaciones": "TEXT DEFAULT '0.00'",
        "ded_salud": "TEXT DEFAULT '0.00'",
        "ded_pension": "TEXT DEFAULT '0.00'",
        "ded_retencion": "TEXT DEFAULT '0.00'",
        "empleador_salud": "TEXT DEFAULT '0.00'",
        "empleador_pension": "TEXT DEFAULT '0.00'",
        "empleador_arl": "TEXT DEFAULT '0.00'",
        "empleador_sena": "TEXT DEFAULT '0.00'",
        "empleador_icbf": "TEXT DEFAULT '0.00'",
        "empleador_caja": "TEXT DEFAULT '0.00'",
        "ibc": "TEXT DEFAULT '0.00'",
        "total_cargas": "TEXT DEFAULT '0.00'",
        "total_comprobante": "TEXT DEFAULT '0.00'",
    }
    for col, tipo in nuevas_nomina.items():
        if col not in cols_nominas:
            dbutil.query(conn, f"ALTER TABLE nominas ADD COLUMN {col} {tipo}")
    if "track_id" not in cols_nominas:
        dbutil.query(conn, "ALTER TABLE nominas ADD COLUMN track_id TEXT")

    # System admin: tipo in roles (system vs company role)
    cols_roles = set(dbutil.table_columns(conn, 'roles'))
    if "tipo" not in cols_roles:
        dbutil.query(conn, "ALTER TABLE roles ADD COLUMN tipo TEXT DEFAULT 'EMPRESA'")

    # Role-company assignment table
    dbutil.query(conn, """
        CREATE TABLE IF NOT EXISTS role_empresa (
            role_id INTEGER NOT NULL,
            empresa_id INTEGER NOT NULL,
            PRIMARY KEY (role_id, empresa_id),
            FOREIGN KEY (role_id) REFERENCES roles (id) ON DELETE CASCADE,
            FOREIGN KEY (empresa_id) REFERENCES empresas (id) ON DELETE CASCADE
        )
    """)

    # User-company assignment table (multi-tenant administration)
    dbutil.query(conn, """
        CREATE TABLE IF NOT EXISTS usuario_empresas (
            usuario_id INTEGER NOT NULL REFERENCES usuarios (id) ON DELETE CASCADE,
            empresa_id INTEGER NOT NULL REFERENCES empresas (id) ON DELETE CASCADE,
            rol_en_empresa TEXT NOT NULL DEFAULT 'ADMIN_EMPRESA',
            es_predeterminada INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            PRIMARY KEY (usuario_id, empresa_id)
        )
    """)

    # Trazabilidad de inventario: lote y fecha_vencimiento
    cols_kardex = set(dbutil.table_columns(conn, 'kardex'))
    if "lote" not in cols_kardex:
        dbutil.query(conn, "ALTER TABLE kardex ADD COLUMN lote TEXT")
    if "fecha_vencimiento" not in cols_kardex:
        dbutil.query(conn, "ALTER TABLE kardex ADD COLUMN fecha_vencimiento TEXT")

    cols_stock = set(dbutil.table_columns(conn, 'stock_actual'))
    if "lote" not in cols_stock:
        dbutil.query(conn, "ALTER TABLE stock_actual ADD COLUMN lote TEXT")
    if "fecha_vencimiento" not in cols_stock:
        dbutil.query(conn, "ALTER TABLE stock_actual ADD COLUMN fecha_vencimiento TEXT")

    # Autenticación multifactor 2FA / TOTP
    cols_usuarios = set(dbutil.table_columns(conn, 'usuarios'))
    if "totp_secret" not in cols_usuarios:
        dbutil.query(conn, "ALTER TABLE usuarios ADD COLUMN totp_secret TEXT")
    if "totp_enabled" not in cols_usuarios:
        dbutil.query(conn, "ALTER TABLE usuarios ADD COLUMN totp_enabled INTEGER DEFAULT 0")

    # Data Ownership y Flujos de Aprobación en Ventas
    cols_cot = set(dbutil.table_columns(conn, 'cotizaciones'))
    if "usuario_id" not in cols_cot:
        dbutil.query(conn, "ALTER TABLE cotizaciones ADD COLUMN usuario_id INTEGER")
    if "descuento_porcentaje" not in cols_cot:
        dbutil.query(conn, "ALTER TABLE cotizaciones ADD COLUMN descuento_porcentaje TEXT DEFAULT '0.00'")
    if "aprobado_por" not in cols_cot:
        dbutil.query(conn, "ALTER TABLE cotizaciones ADD COLUMN aprobado_por INTEGER")

    cols_ped = set(dbutil.table_columns(conn, 'pedidos_venta'))
    if "usuario_id" not in cols_ped:
        dbutil.query(conn, "ALTER TABLE pedidos_venta ADD COLUMN usuario_id INTEGER")
    if "aprobado_por" not in cols_ped:
        dbutil.query(conn, "ALTER TABLE pedidos_venta ADD COLUMN aprobado_por INTEGER")


def init_db(seed: bool = False) -> None:
    conn = get_connection()
    try:
        dbutil.exec_script(conn, _schema_sql())
        _migrate_schema(conn)
        _seed_puc(conn)
        conn.commit()
    finally:
        conn.close()
    # Los parámetros tributarios se siembran fuera de la transacción principal
    # porque parametros.py abre su propia conexión.
    from sap_colombia import parametros
    parametros.sembrar_parametros()
    from sap_colombia import rbac
    rbac.ensure_rbac()
    if seed:
        from sap_colombia import demo_data
        demo_data.sembrar_datos_demo()


def seed_demo_data() -> dict:
    from sap_colombia import demo_data
    return demo_data.sembrar_datos_demo()


def clean_demo_data(solo_ficticios: bool = True) -> dict:
    from sap_colombia import demo_data
    return demo_data.limpiar_datos_demo(solo_ficticios=solo_ficticios)


def get_demo_status() -> dict:
    from sap_colombia import demo_data
    return demo_data.estado_datos_demo()


def _fetch_all(conn: psycopg2.extensions.connection, sql: str, params: tuple | None = None) -> list[dict]:
    cursor = dbutil.query(conn, sql, params or ())
    return [dict(row) for row in cursor.fetchall()]


def _fetch_one(conn: psycopg2.extensions.connection, sql: str, params: tuple | None = None) -> dict | None:
    row = dbutil.query(conn, sql, params or ()).fetchone()
    return dict(row) if row is not None else None


def get_empresa(empresa_id: int | None = None) -> dict | None:
    conn = get_connection()
    try:
        emp_id = empresa_id or get_current_empresa_id()
        if emp_id:
            row = _fetch_one(conn, "SELECT * FROM empresas WHERE id = ?", (emp_id,))
            if row:
                return row
        return _fetch_one(conn, "SELECT * FROM empresas ORDER BY id LIMIT 1")
    finally:
        conn.close()


def get_cliente_by_nit(nit: str) -> dict | None:
    conn = get_connection()
    try:
        empresa_id = get_current_empresa_id()
        if empresa_id:
            row = _fetch_one(conn, "SELECT * FROM clientes WHERE nit = ? AND empresa_id = ?", (nit, empresa_id))
            if row:
                return row
        return _fetch_one(conn, "SELECT * FROM clientes WHERE nit = ?", (nit,))
    finally:
        conn.close()


def get_lineas_factura(factura_id: int) -> list[dict]:
    conn = get_connection()
    try:
        return _fetch_all(conn, "SELECT * FROM factura_lineas WHERE factura_id = ? ORDER BY id", (factura_id,))
    finally:
        conn.close()


def get_siguiente_consecutivo(tipo: str = "facturas", empresa_id: int | None = None) -> str:
    emp = get_empresa(empresa_id)
    if not emp:
        return "1"
    try:
        from sap_colombia import numeracion
        cons = numeracion.siguiente_consecutivo(emp, tipo)
        return str(cons.numero)
    except Exception:
        conn = get_connection()
        try:
            row = dbutil.query(conn, "SELECT COUNT(*) AS c FROM facturas WHERE empresa_id = ?", (empresa_id or 1,)).fetchone()
            return str((row["c"] if row else 0) + 1)
        finally:
            conn.close()


def _resolve_empresa_id(conn: psycopg2.extensions.connection, explicit_id: int | None = None) -> int:
    emp_id = explicit_id or get_current_empresa_id()
    if emp_id is not None:
        return int(emp_id)
    row = dbutil.query(conn, "SELECT id FROM empresas ORDER BY id LIMIT 1").fetchone()
    return int(row["id"]) if row else 1


def actualizar_empresa(cambios: dict) -> dict | None:
    """Actualiza campos de la empresa activa o principal."""
    campos_validos = {
        "nit", "dv", "razon_social", "direccion", "municipio", "departamento",
        "prefijo_resolucion", "resolucion_dian", "fecha_resolucion",
        "rango_desde", "rango_hasta", "clave_tecnica", "tipo_ambiente",
        "ruta_certificado", "password_certificado", "url_dian",
        "en_contingencia", "motivo_contingencia", "fecha_contingencia",
        "nombre_marca", "logo_data", "color_primario", "color_secundario",
        "color_sidebar", "color_fondo", "fuente_nombre", "fuente_data",
    }
    cols = {k: v for k, v in cambios.items() if k in campos_validos}
    target_id = cambios.get("id") or get_current_empresa_id()
    if not cols:
        return get_empresa(target_id)
    asignaciones = ", ".join(f"{k} = ?" for k in cols)
    conn = get_connection()
    try:
        with conn:
            if target_id:
                cur = dbutil.query(
                    conn,
                    f"UPDATE empresas SET {asignaciones} WHERE id = ?",
                    (*cols.values(), target_id),
                )
                if cur.rowcount == 0:
                    dbutil.query(
                        conn,
                        f"UPDATE empresas SET {asignaciones} WHERE id = (SELECT id FROM empresas ORDER BY id LIMIT 1)",
                        tuple(cols.values()),
                    )
            else:
                dbutil.query(
                    conn,
                    f"UPDATE empresas SET {asignaciones} WHERE id = (SELECT id FROM empresas ORDER BY id LIMIT 1)",
                    tuple(cols.values()),
                )
        return get_empresa(target_id)
    finally:
        conn.close()


def get_clientes() -> list[dict]:
    conn = get_connection()
    try:
        empresa_id = get_current_empresa_id()
        if empresa_id:
            return _fetch_all(conn, "SELECT * FROM clientes WHERE empresa_id = ? ORDER BY id", (empresa_id,))
        return _fetch_all(conn, "SELECT * FROM clientes ORDER BY id")
    finally:
        conn.close()


def get_productos() -> list[dict]:
    conn = get_connection()
    try:
        empresa_id = get_current_empresa_id()
        if empresa_id:
            return _fetch_all(conn, "SELECT * FROM productos WHERE empresa_id = ? ORDER BY id", (empresa_id,))
        return _fetch_all(conn, "SELECT * FROM productos ORDER BY id")
    finally:
        conn.close()


def guardar_factura(datos_factura: dict, lineas: list[dict], conn=None) -> int:
    own_conn = conn is None
    conn = conn or get_connection()
    try:
        # Calcular saldo inicial si no viene especificado
        total = datos_factura.get("total_factura")
        saldo = datos_factura.get("saldo_pendiente", total)
        plazo = datos_factura.get("plazo_dias", 30)
        fecha_emision = datos_factura.get("fecha", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
        
        # Fecha de vencimiento aproximada si no viene
        fecha_venc = datos_factura.get("fecha_vencimiento")
        if not fecha_venc:
            try:
                dt = datetime.strptime(fecha_emision, "%Y-%m-%d")
                from datetime import timedelta
                fecha_venc = (dt + timedelta(days=int(plazo))).strftime("%Y-%m-%d")
            except Exception:
                fecha_venc = fecha_emision

        datos_completos = dict(datos_factura)
        datos_completos.setdefault("saldo_pendiente", saldo)
        datos_completos.setdefault("estado_cartera", "PENDIENTE")
        datos_completos.setdefault("plazo_dias", plazo)
        datos_completos.setdefault("fecha_vencimiento", fecha_venc)
        emp_id = get_current_empresa_id()
        if emp_id is None:
            row = dbutil.query(conn, "SELECT id FROM empresas ORDER BY id LIMIT 1").fetchone()
            emp_id = row["id"] if row else 1
        datos_completos.setdefault("empresa_id", emp_id)

        valores_factura = [
            datos_completos.get(columna) if datos_completos.get(columna) is not None else None
            for columna in FACTURAS_COLUMNS
        ]
        valores_factura.append(
            datos_completos.get("created_at")
            or datetime.now(timezone.utc).isoformat()
        )

        nombres_factura = ", ".join([*FACTURAS_COLUMNS, "created_at"])
        marcadores_factura = ", ".join("?" for _ in [*FACTURAS_COLUMNS, "created_at"])
        cursor = dbutil.query(conn, 
            f"INSERT INTO facturas ({nombres_factura}) VALUES ({marcadores_factura}) RETURNING id",
            [_valor_sql(valor) for valor in valores_factura],
        )
        factura_id = cursor.fetchone()["id"]

        if lineas:
            nombres_lineas = ", ".join(["factura_id", *LINEAS_FACTURA_COLUMNS])
            marcadores_lineas = ", ".join(
                "?" for _ in ["factura_id", *LINEAS_FACTURA_COLUMNS]
            )
            registros = []
            for linea in lineas:
                registros.append(
                    (
                        factura_id,
                        *(
                            _valor_sql(linea.get(columna))
                            for columna in LINEAS_FACTURA_COLUMNS
                        ),
                    )
                )
            dbutil.query_many(conn, 
                f"INSERT INTO factura_lineas ({nombres_lineas}) VALUES ({marcadores_lineas})",
                registros,
            )
        if own_conn:
            conn.commit()
        return factura_id
    finally:
        if conn is not get_active_connection():
            conn.close()


def get_facturas() -> list[dict]:
    conn = get_connection()
    try:
        empresa_id = get_current_empresa_id()
        if empresa_id:
            return _fetch_all(
                conn,
                "SELECT * FROM facturas WHERE empresa_id = ? ORDER BY created_at DESC, id DESC",
                (empresa_id,),
            )
        return _fetch_all(
            conn,
            "SELECT * FROM facturas ORDER BY created_at DESC, id DESC",
        )
    finally:
        conn.close()


def get_facturas_paginado(
    page: int = 1,
    limit: int = 50,
    fecha_desde: str | None = None,
    fecha_hasta: str | None = None,
    cliente_nit: str | None = None,
    estado_cartera: str | None = None,
) -> dict:
    conn = get_connection()
    try:
        where = []
        params: list = []
        empresa_id = get_current_empresa_id()
        if empresa_id:
            where.append("empresa_id = ?")
            params.append(empresa_id)
        if fecha_desde:
            where.append("fecha >= ?")
            params.append(fecha_desde)
        if fecha_hasta:
            where.append("fecha <= ?")
            params.append(fecha_hasta)
        if cliente_nit:
            where.append("cliente_nit = ?")
            params.append(cliente_nit)
        if estado_cartera:
            where.append("estado_cartera = ?")
            params.append(estado_cartera)
        where_sql = f"WHERE {' AND '.join(where)}" if where else ""

        total = dbutil.query(conn, 
            f"SELECT COUNT(*) AS cnt FROM facturas {where_sql}",
            params,
        ).fetchone()["cnt"]

        pages = (total + limit - 1) // limit if total else 0
        offset = (page - 1) * limit
        rows = _fetch_all(
            conn,
            f"SELECT * FROM facturas {where_sql} ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
            tuple(params + [limit, offset]),
        )
        return {
            "data": rows,
            "total": total,
            "page": page,
            "limit": limit,
            "pages": pages,
        }
    finally:
        conn.close()


def get_factura_by_id(factura_id: int) -> dict | None:
    conn = get_connection()
    try:
        factura = _fetch_one(
            conn,
            "SELECT * FROM facturas WHERE id = ?",
            (factura_id,),
        )
        if factura is None:
            return None
        factura["lineas"] = _fetch_all(
            conn,
            "SELECT * FROM factura_lineas WHERE factura_id = ? ORDER BY id",
            (factura_id,),
        )
        return factura
    finally:
        conn.close()


# ==========================================
# GESTIÓN DEL PLAN ÚNICO DE CUENTAS (PUC)
# ==========================================

def get_cuentas_puc() -> list[dict]:
    conn = get_connection()
    try:
        return _fetch_all(conn, "SELECT * FROM plan_cuentas WHERE activa = 1 ORDER BY codigo")
    finally:
        conn.close()


def get_cuenta_puc(codigo: str) -> dict | None:
    conn = get_connection()
    try:
        return _fetch_one(conn, "SELECT * FROM plan_cuentas WHERE codigo = ?", (codigo,))
    finally:
        conn.close()


def guardar_cuenta_puc(cuenta: dict) -> None:
    conn = get_connection()
    try:
        with conn:
            dbutil.query(conn, 
                """INSERT INTO plan_cuentas (codigo, nombre, naturaleza, nivel, categoria, activa)
                   VALUES (?, ?, ?, ?, ?, 1) ON CONFLICT (codigo) DO UPDATE SET nombre = EXCLUDED.nombre""",
                (
                    cuenta["codigo"],
                    cuenta["nombre"],
                    cuenta["naturaleza"],
                    cuenta.get("nivel", 3),
                    cuenta.get("categoria", "ACTIVO"),
                ),
            )
    finally:
        conn.close()


# ==========================================
# GESTIÓN DE ASIENTOS Y CONTABILIDAD
# ==========================================

class AsientoDuplicadoError(Exception):
    """Se intentó persistir un asiento con un numero_comprobante ya existente."""

    pass


def guardar_asiento(datos_asiento: dict, movimientos: list[dict], conn=None) -> int:
    """Persiste un asiento y sus movimientos.

    Ante una colisión de ``numero_comprobante`` la versión anterior hacía
    ``UPDATE`` del asiento existente y ``DELETE`` de sus movimientos antes de
    reinsertar los nuevos: **destruía el asiento previo** y su trazabilidad.
    Ahora la colisión se reporta como error para que el llamador genere un
    consecutivo válido (o reemita explícitamente).
    """
    own_conn = conn is None
    conn = conn or get_connection()
    try:
        existente = dbutil.query(conn, 
            "SELECT id FROM asientos_contables WHERE numero_comprobante = ?",
            (datos_asiento["numero_comprobante"],),
        ).fetchone()
        if existente:
            raise AsientoDuplicadoError(
                f"Ya existe un asiento con el número de comprobante "
                f"{datos_asiento['numero_comprobante']!r} (id={existente['id']}). "
                "No se sobrescribe para no destruir el asiento previo."
            )
        emp_id = _resolve_empresa_id(conn, datos_asiento.get("empresa_id"))
        cursor = dbutil.query(conn, 
            """INSERT INTO asientos_contables 
               (empresa_id, numero_comprobante, fecha, tipo_documento, documento_id, glosa, total_debito, total_credito, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING id""",
            (
                emp_id,
                datos_asiento["numero_comprobante"],
                datos_asiento["fecha"],
                datos_asiento["tipo_documento"],
                datos_asiento.get("documento_id"),
                datos_asiento["glosa"],
                _valor_sql(datos_asiento["total_debito"]),
                _valor_sql(datos_asiento["total_credito"]),
                datos_asiento.get("created_at") or datetime.now(timezone.utc).isoformat(),
            ),
        )
        asiento_id = cursor.fetchone()["id"]

        registros = [
            (
                asiento_id,
                m["cuenta_codigo"],
                m.get("tercero_nit"),
                m.get("tercero_nombre"),
                m.get("concepto"),
                _valor_sql(m.get("debito", "0.00")),
                _valor_sql(m.get("credito", "0.00")),
            )
            for m in movimientos
        ]
        dbutil.query_many(conn, 
            """INSERT INTO movimientos_contables 
               (asiento_id, cuenta_codigo, tercero_nit, tercero_nombre, concepto, debito, credito)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            registros,
        )
        if own_conn:
            conn.commit()
        return asiento_id
    finally:
        # Solo se cierra si esta función abrió la conexión: cerrarla cuando la
        # recibió del llamador dejaba conexiones rotas en las transacciones
        # composed (inventario -> asiento, por ejemplo).
        if own_conn:
            conn.close()


def get_asientos() -> list[dict]:
    conn = get_connection()
    try:
        empresa_id = get_current_empresa_id()
        if empresa_id:
            asientos = _fetch_all(
                conn,
                "SELECT * FROM asientos_contables WHERE (empresa_id = ? OR empresa_id IS NULL) ORDER BY fecha DESC, id DESC",
                (empresa_id,),
            )
        else:
            asientos = _fetch_all(conn, "SELECT * FROM asientos_contables ORDER BY fecha DESC, id DESC")
        for a in asientos:
            a["movimientos"] = _fetch_all(
                conn,
                """SELECT m.*, p.nombre AS cuenta_nombre 
                   FROM movimientos_contables m 
                   LEFT JOIN plan_cuentas p ON m.cuenta_codigo = p.codigo 
                   WHERE m.asiento_id = ? ORDER BY m.id""",
                (a["id"],),
            )
        return asientos
    finally:
        conn.close()


def get_asiento_by_id(asiento_id: int) -> dict | None:
    conn = get_connection()
    try:
        asiento = _fetch_one(conn, "SELECT * FROM asientos_contables WHERE id = ?", (asiento_id,))
        if not asiento:
            return None
        asiento["movimientos"] = _fetch_all(
            conn,
            """SELECT m.*, p.nombre AS cuenta_nombre 
               FROM movimientos_contables m 
               LEFT JOIN plan_cuentas p ON m.cuenta_codigo = p.codigo 
               WHERE m.asiento_id = ? ORDER BY m.id""",
            (asiento_id,),
        )
        return asiento
    finally:
        conn.close()


def get_asientos_por_documento(tipo_doc: str, documento_id: int) -> list[dict]:
    conn = get_connection()
    try:
        asientos = _fetch_all(
            conn,
            "SELECT * FROM asientos_contables WHERE tipo_documento = ? AND documento_id = ?",
            (tipo_doc, documento_id),
        )
        for a in asientos:
            a["movimientos"] = _fetch_all(
                conn,
                """SELECT m.*, p.nombre AS cuenta_nombre 
                   FROM movimientos_contables m 
                   LEFT JOIN plan_cuentas p ON m.cuenta_codigo = p.codigo 
                   WHERE m.asiento_id = ? ORDER BY m.id""",
                (a["id"],),
            )
        return asientos
    finally:
        conn.close()


# ==========================================
# GESTIÓN DE NOTAS CRÉDITO
# ==========================================

def guardar_nota_credito(datos_nc: dict, lineas: list[dict], conn=None) -> int:
    own_conn = conn is None
    conn = conn or get_connection()
    try:
        datos_completos = dict(datos_nc)
        datos_completos.setdefault("empresa_id", _resolve_empresa_id(conn, datos_nc.get("empresa_id")))
        valores_nc = [
            datos_completos.get(c) if datos_completos.get(c) is not None else None
            for c in NOTAS_CREDITO_COLUMNS
        ]
        valores_nc.append(datos_completos.get("created_at") or datetime.now(timezone.utc).isoformat())
        nombres_nc = ", ".join([*NOTAS_CREDITO_COLUMNS, "created_at"])
        marcadores_nc = ", ".join("?" for _ in [*NOTAS_CREDITO_COLUMNS, "created_at"])
        cursor = dbutil.query(conn, 
            f"INSERT INTO notas_credito ({nombres_nc}) VALUES ({marcadores_nc}) RETURNING id",
            [_valor_sql(v) for v in valores_nc],
        )
        nc_id = cursor.fetchone()["id"]

        if lineas:
            registros = [
                (
                    nc_id,
                    l.get("producto_codigo"),
                    l.get("descripcion", ""),
                    _valor_sql(l.get("cantidad")),
                    _valor_sql(l.get("valor_unitario")),
                    _valor_sql(l.get("subtotal")),
                    _valor_sql(l.get("tarifa_iva")),
                    _valor_sql(l.get("valor_iva")),
                )
                for l in lineas
            ]
            dbutil.query_many(conn, 
                """INSERT INTO lineas_nota_credito 
                   (nota_credito_id, producto_codigo, descripcion, cantidad, valor_unitario, subtotal, tarifa_iva, valor_iva)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                registros,
            )
        if own_conn:
            conn.commit()
        return nc_id
    finally:
        if conn is not get_active_connection():
            conn.close()


def get_notas_credito() -> list[dict]:
    conn = get_connection()
    try:
        empresa_id = get_current_empresa_id()
        if empresa_id:
            return _fetch_all(
                conn,
                "SELECT * FROM notas_credito WHERE (empresa_id = ? OR empresa_id IS NULL) ORDER BY id DESC",
                (empresa_id,),
            )
        return _fetch_all(conn, "SELECT * FROM notas_credito ORDER BY id DESC")
    finally:
        conn.close()


def get_nota_credito_by_id(nc_id: int) -> dict | None:
    conn = get_connection()
    try:
        nc = _fetch_one(conn, "SELECT * FROM notas_credito WHERE id = ?", (nc_id,))
        if not nc:
            return None
        nc["lineas"] = _fetch_all(
            conn,
            "SELECT * FROM lineas_nota_credito WHERE nota_credito_id = ? ORDER BY id",
            (nc_id,),
        )
        return nc
    finally:
        conn.close()


# ==========================================
# GESTIÓN DE CARTERA Y RECIBOS DE CAJA
# ==========================================

def actualizar_saldo_factura(factura_id: int, nuevo_saldo: str, nuevo_estado: str, conn=None) -> None:
    own_conn = conn is None
    conn = conn or get_connection()
    try:
        dbutil.query(conn, 
            "UPDATE facturas SET saldo_pendiente = ?, estado_cartera = ? WHERE id = ?",
            (nuevo_saldo, nuevo_estado, factura_id),
        )
        if own_conn:
            conn.commit()
    finally:
        if conn is not get_active_connection():
            conn.close()


def guardar_recibo_caja(datos_rc: dict, conn=None) -> int:
    own_conn = conn is None
    conn = conn or get_connection()
    try:
        emp_id = _resolve_empresa_id(conn, datos_rc.get("empresa_id"))
        valores_rc = [
            datos_rc.get(c) if datos_rc.get(c) is not None else None
            for c in RECIBOS_CAJA_COLUMNS
        ]
        valores_rc.append(emp_id)
        valores_rc.append(datos_rc.get("created_at") or datetime.now(timezone.utc).isoformat())
        nombres_rc = ", ".join([*RECIBOS_CAJA_COLUMNS, "empresa_id", "created_at"])
        marcadores_rc = ", ".join("?" for _ in [*RECIBOS_CAJA_COLUMNS, "empresa_id", "created_at"])
        cursor = dbutil.query(conn, 
            f"INSERT INTO recibos_caja ({nombres_rc}) VALUES ({marcadores_rc}) RETURNING id",
            [_valor_sql(v) for v in valores_rc],
        )
        rc_id = cursor.fetchone()["id"]
        if own_conn:
            conn.commit()
        return rc_id
    finally:
        if conn is not get_active_connection():
            conn.close()


def get_recibos_caja() -> list[dict]:
    conn = get_connection()
    try:
        empresa_id = get_current_empresa_id()
        if empresa_id:
            return _fetch_all(
                conn,
                """SELECT r.*, f.consecutivo AS factura_consecutivo, c.razon_social AS cliente_nombre 
                   FROM recibos_caja r 
                   LEFT JOIN facturas f ON r.factura_id = f.id 
                   LEFT JOIN clientes c ON r.cliente_nit = c.nit AND (c.empresa_id = r.empresa_id OR c.empresa_id IS NULL)
                   WHERE (r.empresa_id = ? OR r.empresa_id IS NULL)
                   ORDER BY r.id DESC""",
                (empresa_id,),
            )
        return _fetch_all(
            conn,
            """SELECT r.*, f.consecutivo AS factura_consecutivo, c.razon_social AS cliente_nombre 
               FROM recibos_caja r 
               LEFT JOIN facturas f ON r.factura_id = f.id 
               LEFT JOIN clientes c ON r.cliente_nit = c.nit 
               ORDER BY r.id DESC""",
        )
    finally:
        conn.close()


# ==========================================
# GESTIÓN DE DOCUMENTOS SOPORTE
# ==========================================

def guardar_documento_soporte(datos_ds: dict, lineas: list[dict]) -> int:
    conn = get_connection()
    try:
        with conn:
            datos_completos = dict(datos_ds)
            datos_completos.setdefault("empresa_id", _resolve_empresa_id(conn, datos_ds.get("empresa_id")))
            valores_ds = [
                datos_completos.get(c) if datos_completos.get(c) is not None else None
                for c in DOCUMENTOS_SOPORTE_COLUMNS
            ]
            valores_ds.append(datos_completos.get("created_at") or datetime.now(timezone.utc).isoformat())
            nombres_ds = ", ".join([*DOCUMENTOS_SOPORTE_COLUMNS, "created_at"])
            marcadores_ds = ", ".join("?" for _ in [*DOCUMENTOS_SOPORTE_COLUMNS, "created_at"])
            cursor = dbutil.query(conn, 
                f"INSERT INTO documentos_soporte ({nombres_ds}) VALUES ({marcadores_ds}) RETURNING id",
                [_valor_sql(v) for v in valores_ds],
            )
            ds_id = cursor.fetchone()["id"]

            if lineas:
                registros = [
                    (
                        ds_id,
                        l.get("descripcion", ""),
                        _valor_sql(l.get("cantidad")),
                        _valor_sql(l.get("valor_unitario")),
                        _valor_sql(l.get("subtotal")),
                    )
                    for l in lineas
                ]
                dbutil.query_many(conn, 
                    """INSERT INTO lineas_documento_soporte 
                       (documento_soporte_id, descripcion, cantidad, valor_unitario, subtotal)
                       VALUES (?, ?, ?, ?, ?)""",
                    registros,
                )
            return ds_id
    finally:
        conn.close()


def get_documentos_soporte() -> list[dict]:
    conn = get_connection()
    try:
        empresa_id = get_current_empresa_id()
        if empresa_id:
            return _fetch_all(
                conn,
                "SELECT * FROM documentos_soporte WHERE (empresa_id = ? OR empresa_id IS NULL) ORDER BY id DESC",
                (empresa_id,),
            )
        return _fetch_all(conn, "SELECT * FROM documentos_soporte ORDER BY id DESC")
    finally:
        conn.close()


def get_documento_soporte_by_id(ds_id: int) -> dict | None:
    conn = get_connection()
    try:
        ds = _fetch_one(conn, "SELECT * FROM documentos_soporte WHERE id = ?", (ds_id,))
        if not ds:
            return None
        ds["lineas"] = _fetch_all(
            conn,
            "SELECT * FROM lineas_documento_soporte WHERE documento_soporte_id = ? ORDER BY id",
            (ds_id,),
        )
        return ds
    finally:
        conn.close()


# ==========================================
# GESTIÓN DE INVENTARIO Y KÁRDEX
# ==========================================

def get_bodegas() -> list[dict]:
    conn = get_connection()
    try:
        return _fetch_all(conn, "SELECT * FROM bodegas ORDER BY id")
    finally:
        conn.close()


def get_bodega(codigo: str) -> dict | None:
    conn = get_connection()
    try:
        return _fetch_one(conn, "SELECT * FROM bodegas WHERE codigo = ?", (codigo,))
    finally:
        conn.close()


def guardar_bodega(datos: dict) -> int:
    conn = get_connection()
    try:
        with conn:
            emp_id = _resolve_empresa_id(conn, datos.get("empresa_id"))
            cursor = dbutil.query(conn, 
                "INSERT INTO bodegas (codigo, nombre, direccion, activa, empresa_id) VALUES (?, ?, ?, ?, ?) RETURNING id",
                (datos["codigo"], datos["nombre"], datos.get("direccion", ""), 1, emp_id),
            )
            return cursor.fetchone()["id"]
    finally:
        conn.close()


def get_kardex(producto_codigo: str | None = None, bodega_codigo: str | None = None) -> list[dict]:
    conn = get_connection()
    try:
        sql = "SELECT * FROM kardex WHERE 1=1"
        params: list = []
        empresa_id = get_current_empresa_id()
        if empresa_id:
            sql += " AND (empresa_id = ? OR empresa_id IS NULL)"
            params.append(empresa_id)
        if producto_codigo:
            sql += " AND producto_codigo = ?"
            params.append(producto_codigo)
        if bodega_codigo:
            sql += " AND bodega_codigo = ?"
            params.append(bodega_codigo)
        sql += " ORDER BY fecha DESC, id DESC"
        return _fetch_all(conn, sql, params)
    finally:
        conn.close()


def get_stock_actual(producto_codigo: str | None = None, bodega_codigo: str | None = None) -> list[dict]:
    conn = get_connection()
    try:
        sql = "SELECT * FROM stock_actual WHERE 1=1"
        params: list = []
        empresa_id = get_current_empresa_id()
        if empresa_id:
            sql += " AND (empresa_id = ? OR empresa_id IS NULL)"
            params.append(empresa_id)
        if producto_codigo:
            sql += " AND producto_codigo = ?"
            params.append(producto_codigo)
        if bodega_codigo:
            sql += " AND bodega_codigo = ?"
            params.append(bodega_codigo)
        sql += " ORDER BY producto_codigo, bodega_codigo"
        return _fetch_all(conn, sql, params)
    finally:
        conn.close()


def _seed_bodegas(conn: psycopg2.extensions.connection) -> None:
    if dbutil.query(conn, "SELECT COUNT(*) AS total FROM bodegas").fetchone()["total"] == 0:
        dbutil.query(conn, 
            "INSERT INTO bodegas (codigo, nombre, direccion, activa) VALUES (?, ?, ?, 1)",
            ("BODEGA-01", "Bodega Principal", "Cra 15 # 45-30, PBX 12"),
        )


def get_empleados(activo: int | None = None) -> list[dict]:
    conn = get_connection()
    try:
        sql = "SELECT * FROM empleados WHERE 1=1"
        params: list = []
        empresa_id = get_current_empresa_id()
        if empresa_id:
            sql += " AND (empresa_id = ? OR empresa_id IS NULL)"
            params.append(empresa_id)
        if activo is not None:
            sql += " AND activo = ?"
            params.append(activo)
        sql += " ORDER BY id"
        return _fetch_all(conn, sql, params)
    finally:
        conn.close()


def get_empleado_by_id(empleado_id: int) -> dict | None:
    conn = get_connection()
    try:
        return _fetch_one(conn, "SELECT * FROM empleados WHERE id = ?", (empleado_id,))
    finally:
        conn.close()


def nomina_completa(nomina_id: int) -> dict | None:
    """Nómina con todos sus componentes (para el asiento contable)."""
    conn = get_connection()
    try:
        return _fetch_one(conn, "SELECT * FROM nominas WHERE id = ?", (nomina_id,))
    finally:
        conn.close()


def get_empleado_by_documento(documento: str) -> dict | None:
    conn = get_connection()
    try:
        empresa_id = get_current_empresa_id()
        if empresa_id:
            row = _fetch_one(
                conn,
                "SELECT * FROM empleados WHERE documento = ? AND (empresa_id = ? OR empresa_id IS NULL)",
                (documento, empresa_id),
            )
            if row:
                return row
        return _fetch_one(conn, "SELECT * FROM empleados WHERE documento = ?", (documento,))
    finally:
        conn.close()


def guardar_empleado(datos: dict) -> int:
    conn = get_connection()
    try:
        emp_id_tenant = _resolve_empresa_id(conn, datos.get("empresa_id"))
        colunas = ["empresa_id", "tipo_documento", "documento", "nombres", "apellidos", "salario_base", "auxilio_transporte", "activo", "created_at"]
        nombres = ", ".join(colunas)
        marcadores = ", ".join("?" for _ in colunas)
        datos_completos = dict(datos)
        datos_completos.setdefault("empresa_id", emp_id_tenant)
        datos_completos.setdefault("tipo_documento", "CC")
        if not datos_completos.get("documento") and datos_completos.get("numero_documento"):
            datos_completos["documento"] = datos_completos["numero_documento"]
        datos_completos.setdefault("auxilio_transporte", 1)
        datos_completos.setdefault("activo", 1)
        datos_completos.setdefault("created_at", datetime.now(timezone.utc).isoformat())
        valores = [datos_completos.get(c) for c in colunas]
        cur = dbutil.query(conn, 
            f"INSERT INTO empleados ({nombres}) VALUES ({marcadores}) RETURNING id",
            valores,
        )
        emp_id = cur.fetchone()["id"]
        conn.commit()
        return emp_id
    finally:
        conn.close()


def actualizar_empleado(empleado_id: int, datos: dict) -> dict | None:
    """Actualiza los datos de un empleado existente."""
    campos_validos = {"tipo_documento", "documento", "nombres", "apellidos", "salario_base", "auxilio_transporte", "activo"}
    cols = {k: v for k, v in datos.items() if k in campos_validos and v is not None}
    if not cols:
        return get_empleado_by_id(empleado_id)
    asignaciones = ", ".join(f"{k} = ?" for k in cols)
    conn = get_connection()
    try:
        with conn:
            dbutil.query(
                conn,
                f"UPDATE empleados SET {asignaciones} WHERE id = ?",
                (*cols.values(), empleado_id),
            )
        return get_empleado_by_id(empleado_id)
    finally:
        conn.close()


def get_nominas(empleado_id: int | None = None, estado_pago: str | None = None, periodo_inicio: str | None = None, periodo_fin: str | None = None) -> list[dict]:
    conn = get_connection()
    try:
        sql = "SELECT n.*, e.nombres, e.apellidos, e.documento FROM nominas n LEFT JOIN empleados e ON n.empleado_id = e.id WHERE 1=1"
        params: list = []
        empresa_id = get_current_empresa_id()
        if empresa_id:
            sql += " AND (n.empresa_id = ? OR n.empresa_id IS NULL)"
            params.append(empresa_id)
        if empleado_id is not None:
            sql += " AND n.empleado_id = ?"
            params.append(empleado_id)
        if estado_pago is not None:
            sql += " AND n.estado_pago = ?"
            params.append(estado_pago)
        if periodo_inicio is not None:
            sql += " AND n.periodo_inicio >= ?"
            params.append(periodo_inicio)
        if periodo_fin is not None:
            sql += " AND n.periodo_fin <= ?"
            params.append(periodo_fin)
        sql += " ORDER BY n.id DESC"
        return _fetch_all(conn, sql, params)
    finally:
        conn.close()


def get_nomina_by_id(nomina_id: int) -> dict | None:
    conn = get_connection()
    try:
        return _fetch_one(conn, "SELECT * FROM nominas WHERE id = ?", (nomina_id,))
    finally:
        conn.close()


def actualizar_estado_pago_nomina(nomina_id: int, estado_pago: str) -> None:
    conn = get_connection()
    try:
        dbutil.query(conn, "UPDATE nominas SET estado_pago = ? WHERE id = ?", (estado_pago, nomina_id))
        conn.commit()
    finally:
        conn.close()


def guardar_nomina(datos: dict) -> int:
    conn = get_connection()
    try:
        # Se persiste **toda** la liquidación, no solo los 3 totales: antes el
        # motor calculaba 14 conceptos y guardar_nomina insertaba 3, dejando
        # el resto en el aire (el CUNE no era auditable contra sus componentes).
        datos_completos = dict(datos)
        datos_completos.setdefault("empresa_id", _resolve_empresa_id(conn, datos.get("empresa_id")))
        colunas = [
            "empresa_id",
            "consecutivo", "prefijo", "periodo_inicio", "periodo_fin", "empleado_id",
            "total_devengado", "total_deducciones", "neto_pagar", "cune",
            "xml_ubl", "estado_dian", "estado_pago", "track_id", "mensaje_dian",
            "fecha_emision", "hora_emision",
            "salario_base", "auxilio_transporte", "total_horas_extras",
            "bonificaciones", "recargo_nocturno", "recargo_dominical",
            "recargo_festivo", "cesantias", "intereses_cesantias",
            "prima_servicios", "vacaciones",
            "ded_salud", "ded_pension", "ded_retencion",
            "empleador_salud", "empleador_pension", "empleador_arl",
            "empleador_sena", "empleador_icbf", "empleador_caja",
            "ibc", "total_cargas", "total_comprobante",
            "created_at",
        ]
        existentes = set(dbutil.table_columns(conn, "nominas"))
        colunas = [c for c in colunas if c in existentes]
        nombres = ", ".join(colunas)
        marcadores = ", ".join("?" for _ in colunas)
        valores = [
            datos_completos.get(c, datetime.now(timezone.utc).isoformat() if c == "created_at" else None)
            for c in colunas
        ]
        cur = dbutil.query(conn, 
            f"INSERT INTO nominas ({nombres}) VALUES ({marcadores}) RETURNING id",
            valores,
        )
        nom_id = cur.fetchone()["id"]
        conn.commit()
        return nom_id
    finally:
        conn.close()


def guardar_evento_radian(datos_evento: dict) -> int:
    conn = get_connection()
    try:
        colunas = ["factura_id", "tipo_evento", "codigo_evento", "cude_evento",
                   "xml_ubl", "estado_dian", "fecha_evento", "hora_evento",
                   "track_id", "mensaje_dian", "created_at"]
        nombres = ", ".join(colunas)
        marcadores = ", ".join("?" for _ in colunas)
        valores = [datos_evento.get(c) for c in colunas]
        cur = dbutil.query(conn, 
            f"INSERT INTO eventos_radian ({nombres}) VALUES ({marcadores}) RETURNING id",
            valores,
        )
        ev_id = cur.fetchone()["id"]
        conn.commit()
        return ev_id
    finally:
        conn.close()


def get_eventos_radian_by_factura(factura_id: int) -> list[dict]:
    conn = get_connection()
    try:
        return _fetch_all(
            conn,
            "SELECT * FROM eventos_radian WHERE factura_id = ? ORDER BY fecha_evento",
            (factura_id,),
        )
    finally:
        conn.close()


def guardar_nota_debito(datos_nd: dict, lineas: list[dict]) -> int:
    conn = get_connection()
    try:
        datos_completos = dict(datos_nd)
        datos_completos.setdefault("empresa_id", _resolve_empresa_id(conn, datos_nd.get("empresa_id")))
        colunas = ["empresa_id", "consecutivo", "prefijo", "fecha", "hora", "factura_id",
                    "factura_consecutivo", "cufe_factura", "cliente_nit",
                    "concepto_dian", "descripcion_motivo", "subtotal",
                    "total_iva", "total_nota", "cude", "qr", "estado_dian",
                    "track_id", "mensaje_dian", "xml_ubl", "created_at"]
        nombres = ", ".join(colunas)
        marcadores = ", ".join("?" for _ in colunas)
        valores = [datos_completos.get(c) for c in colunas]
        cur = dbutil.query(conn, 
            f"INSERT INTO notas_debito ({nombres}) VALUES ({marcadores}) RETURNING id",
            valores,
        )
        nd_id = cur.fetchone()["id"]
        for linea in lineas:
            dbutil.query(conn, 
                "INSERT INTO lineas_nota_debito (nota_debito_id, producto_codigo, descripcion, cantidad, valor_unitario, subtotal, tarifa_iva, valor_iva) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (nd_id, linea.get("producto_codigo"), linea.get("descripcion"),
                 linea.get("cantidad"), str(linea.get("valor_unitario")),
                 str(linea.get("subtotal")), linea.get("tarifa_iva"),
                 str(linea.get("valor_iva"))),
            )
        conn.commit()
        return nd_id
    finally:
        conn.close()


def get_notas_debito() -> list[dict]:
    conn = get_connection()
    try:
        empresa_id = get_current_empresa_id()
        if empresa_id:
            return _fetch_all(
                conn,
                "SELECT * FROM notas_debito WHERE (empresa_id = ? OR empresa_id IS NULL) ORDER BY created_at DESC",
                (empresa_id,),
            )
        return _fetch_all(conn, "SELECT * FROM notas_debito ORDER BY created_at DESC")
    finally:
        conn.close()


def get_nota_debito_by_id(nd_id: int) -> dict | None:
    conn = get_connection()
    try:
        return _fetch_one(conn, "SELECT * FROM notas_debito WHERE id = ?", (nd_id,))
    finally:
        conn.close()


# ==========================================
# GESTIÓN DE USUARIOS Y PERIODOS
# ==========================================

def get_usuarios() -> list[dict]:
    conn = get_connection()
    try:
        return _fetch_all(conn, "SELECT id, email, nombre, rol, activo, created_at FROM usuarios ORDER BY id")
    finally:
        conn.close()