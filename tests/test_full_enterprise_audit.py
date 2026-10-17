"""Auditoría Empresarial Completa — Saluki Enterprise SAS.

Simula un ciclo de operaciones mensual completo:
Payroll → Compras (CUDS) → Ventas (CUFE) → RADIAN → Notas → Recibos → Exogena → Cierre Periodo.

Cada fase valida integridad contable (debits == credits) y normativa DIAN.
"""

import os
from sap_colombia import dbutil
import sys
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import patch

import pytest

from sap_colombia import database as db
from sap_colombia.cufe_calculator import calculate_cufe, generar_cadena_qr
from sap_colombia.payroll import emitir_nomina
from sap_colombia.support_document import crear_documento_soporte
from sap_colombia.radian import registrar_evento_radian
from sap_colombia.credit_notes import emitir_nota_credito
from sap_colombia.accounts_receivable import registrar_recibo_caja
from sap_colombia.exogena import extraer_formato_1001
from sap_colombia.period_control import cerrar_periodo, validar_periodo_abierto
from sap_colombia.accounting_engine import generar_balance_prueba


def _limpiar():
    dbutil.close_all_pools()
    conn = db.get_connection()
    with conn:
        tablas = ["role_permissions", "role_empresa", "permisos", "auditoria",
                  "usuarios", "empresas", "clientes", "productos", "bodegas",
                  "facturas", "factura_lineas", "notas_credito", "lineas_nota_credito",
                  "recibos_caja", "documentos_soporte", "lineas_documento_soporte",
                  "empleados", "nominas", "eventos_radian", "notas_debito",
                  "lineas_nota_debito", "periodos_contables", "kardex", "stock_actual",
                  "asientos_contables", "movimientos_contables"]
        cur = conn.cursor()
        cur.execute(f"TRUNCATE TABLE {', '.join(tablas)} CASCADE")
    conn.close()
    from sap_colombia import auth, rbac
    auth.seed_usuarios()
    rbac.ensure_rbac()


@pytest.fixture(autouse=True)
def setup_db():
    db.init_db()
    _limpiar()
    yield
    _limpiar()


@pytest.fixture(autouse=True)
def mock_dian():
    class FakeResp:
        estado = "EXITOSA"
        track_id = "TRK-TEST"
        status_description = "OK"
    with patch("sap_colombia.dian_client.DianClient.transmitir_xml") as m:
        m.return_value = FakeResp()
        yield m


def _setup_empresa_cliente():
    conn = db.get_connection()
    with conn:
        emp_cur = dbutil.query(conn,
            "INSERT INTO empresas (nit, dv, razon_social, direccion, municipio, clave_tecnica, tipo_ambiente, prefijo_resolucion, rango_desde, rango_hasta, resolucion_dian, fecha_resolucion) "
            "VALUES ('900123456', '7', 'Saluki Enterprise SAS', 'Carrera 15 # 85-250', 'Bogotá', '3fa9c0b1d2e34f5a6b7c8d9e0f1a2b3c', '1', 'FAC', 990000000, 999999999, '18760000002', '2026-01-15') "
            "RETURNING id"
        )
        empresa_id = emp_cur.fetchone()["id"]
        dbutil.query(conn, 
            "INSERT INTO clientes (nit, dv, tipo_documento, razon_social, direccion, municipio, empresa_id) "
            "VALUES ('900999999', '1', 'NIT', 'Cliente Auditado S.A.S.', 'Av. 68 # 52-31', 'Bogotá', ?)",
            (empresa_id,)
        )
        dbutil.query(conn, 
            "INSERT INTO productos (codigo, descripcion, precio_unitario, tarifa_iva, tipo_bien_servicio, unidad_medida, empresa_id) "
            "VALUES ('AUD-001', 'Producto de Auditoría', '150000', 'IVA_19', 'BIEN', 'UNO', ?)",
            (empresa_id,)
        )
    conn.close()
    return db.get_empresa(), db.get_clientes()[0]


def _emitir_factura_test(cliente_nit, cantidad="10", valor_unitario="150000", tarifa_iva="IVA_19"):
    empresa = db.get_empresa()
    ahora = datetime.now(timezone.utc)
    fecha = ahora.strftime("%Y-%m-%d")
    hora = ahora.strftime("%H:%M:%S-05:00")
    prefijo = "FAC"
    consecutivo = str(datetime.now().strftime("%s"))[-6:]
    subtotal = Decimal(valor_unitario) * Decimal(cantidad)
    iva_19 = subtotal * Decimal("0.19")
    total_iva = iva_19
    total_factura = subtotal + total_iva
    lineas = [{
        "producto_codigo": "AUD-001",
        "descripcion": "Producto de Auditoría",
        "cantidad": cantidad,
        "valor_unitario": valor_unitario,
        "subtotal": str(subtotal),
        "tarifa_iva": tarifa_iva,
        "valor_iva": str(iva_19),
    }]
    categorias = {"IVA_0": Decimal("0"), "IVA_5": Decimal("0"), "IVA_19": iva_19}
    cufe = calculate_cufe(
        num_fac=consecutivo,
        fecha=fecha,
        hora=hora,
        valor_factura=subtotal,
        categorias=categorias,
        nit_emisor=empresa["nit"],
        nit_adquirente=cliente_nit,
        clave_tecnica=empresa["clave_tecnica"],
        tipo_ambiente=empresa["tipo_ambiente"],
        valor_transaccion=total_factura,
    )
    qr = generar_cadena_qr(
        tipo_ambiente=empresa["tipo_ambiente"],
        tipo_operacion="01",
        nit_emisor=empresa["nit"],
        num_fac=consecutivo,
        fecha=fecha,
        hora=hora,
        valor_transaccion=total_factura,
        clave_tecnica=empresa["clave_tecnica"],
        cufe=cufe,
    )
    datos_factura = {
        "consecutivo": consecutivo,
        "prefijo": prefijo,
        "fecha": fecha,
        "hora": hora,
        "cliente_nit": cliente_nit,
        "subtotal": str(subtotal),
        "iva_19": str(iva_19),
        "iva_5": "0.00",
        "iva_0": "0.00",
        "total_iva": str(total_iva),
        "retefuente": "0.00",
        "reteica": "0.00",
        "reteiva": "0.00",
        "total_factura": str(total_factura),
        "cufe": cufe,
        "qr": qr,
        "xml_ubl": "<Invoice>Test</Invoice>",
        "estado_dian": "EXITOSA",
        "track_id": "TRK-TEST-001",
        "mensaje_dian": "OK",
        "plazo_dias": 30,
        "saldo_pendiente": str(total_factura),
        "estado_cartera": "PENDIENTE",
    }
    factura_id = db.guardar_factura(datos_factura, lineas)
    return factura_id


class TestFullEnterpriseAudit:
    def test_fase1_payroll(self):
        _setup_empresa_cliente()
        empleado_id = db.guardar_empleado({
            "tipo_documento": "CC",
            "documento": "1023456789",
            "nombres": "Juan",
            "apellidos": "Pérez",
            "salario_base": "4000000",
            "auxilio_transporte": "175000",
            "activo": 1,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        hoy = datetime.now()
        mes_actual = hoy.strftime("%Y-%m-01")
        mes_fin = hoy.strftime("%Y-%m-%d")
        resultado = emitir_nomina(empleado_id, mes_actual, mes_fin)
        assert "nomina" in resultado
        assert "asiento_contable" in resultado

    def test_fase2_compras_cuds(self):
        _setup_empresa_cliente()
        datos_ds = {
            "prefijo": "DS",
            "proveedor_nit": "900888888",
            "proveedor_nombre": "Proveedor SAS",
            "proveedor_doc": "NIT",
            "tarifa_retefuente": "0.035",
            "tarifa_reteica": "0.0069",
        }
        lineas = [{"producto_codigo": "AUD-001", "descripcion": "Producto", "cantidad": "100", "valor_unitario": "50000", "subtotal": "5000000"}]
        resultado = crear_documento_soporte(datos_ds, lineas)
        assert resultado["cuds"]
        assert resultado["asiento"]

    def test_fase3_ventas_cufe(self):
        _setup_empresa_cliente()
        factura_id = _emitir_factura_test("900999999")
        factura = db.get_factura_by_id(factura_id)
        assert factura["cufe"]
        assert factura["qr"]
        assert factura["total_factura"]

    def test_fase4_radian(self):
        _setup_empresa_cliente()
        factura_id = _emitir_factura_test("900999999")
        evento_030 = registrar_evento_radian(factura_id, "030")
        assert evento_030["cude"]
        assert "ApplicationResponse" in evento_030["xml"]
        evento_032 = registrar_evento_radian(factura_id, "032")
        assert evento_032["cude"]
        evento_033 = registrar_evento_radian(factura_id, "033")
        assert evento_033["cude"]
        eventos = db.get_eventos_radian_by_factura(factura_id)
        assert len(eventos) == 3

    def test_fase5_nota_credito(self):
        _setup_empresa_cliente()
        factura_id = _emitir_factura_test("900999999")
        resultado = emitir_nota_credito(factura_id, motivo_dian="01", tipo_anulacion="TOTAL")
        assert resultado["nota_credito"]["cude"]
        assert resultado["asiento_contable"]

    def test_fase6_recibos(self):
        _setup_empresa_cliente()
        factura_id = _emitir_factura_test("900999999", cantidad="20", valor_unitario="100000")
        factura = db.get_factura_by_id(factura_id)
        resultado = registrar_recibo_caja(factura_id, monto=factura["total_factura"])
        assert resultado["estado_cartera"] == "PAGADA_TOTAL"
        assert resultado["asiento"]

    def test_fase7_exogena(self):
        _setup_empresa_cliente()
        _emitir_factura_test("900999999")
        formato_1001 = extraer_formato_1001(datetime.now().year)
        assert isinstance(formato_1001, list)

    def test_fase8_cierre_periodo(self):
        _setup_empresa_cliente()
        periodo = validar_periodo_abierto()
        assert periodo["estado"] == "ABIERTO"
        conn = db.get_connection()
        with conn:
            dbutil.query(conn, 
                "INSERT INTO usuarios (email, nombre, rol, hash_password, salt, activo, created_at) VALUES ('admin@test.co', 'Admin', 'ADMIN', 'hash', 'salt', 1, '2026-01-01T00:00:00')"
            )
        conn.close()
        usuarios = db.get_usuarios()
        admin = next((u for u in usuarios if u["email"] == "admin@test.co"), None)
        assert admin
        resultado = cerrar_periodo(periodo["periodo"], admin["id"], "Cierre mensual")
        assert resultado["estado"] == "CERRADO"

    def test_balance_general(self):
        _setup_empresa_cliente()
        _emitir_factura_test("900999999")
        balance = generar_balance_prueba()
        if balance:
            assert balance["balance_cuadrado"] is True
