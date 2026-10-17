"""Pruebas TDD para Eventos RADIAN (Resolución 000085/2022) y Notas Débito (tipo 92)."""

import os
from sap_colombia import dbutil
import sys
import unittest.mock
from decimal import Decimal

import pytest

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(BASE_DIR)
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from sap_colombia import database as db
from sap_colombia import radian
from sap_colombia import debit_notes
from sap_colombia.cufe_calculator import calculate_cufe, generar_cadena_qr
from sap_colombia.tax_engine import TaxEngine, LineaFactura
from sap_colombia.ubl_builder import Emisor, Adquirente, UblInvoiceBuilder
from sap_colombia.dian_client import DianClient, TransmisionResult


def _limpiar():
    conn = db.get_connection()
    with conn:
        for tabla in ["kardex", "stock_actual", "recibos_caja", "asientos_contables",
                      "eventos_radian", "notas_debito", "lineas_nota_debito",
                      "factura_lineas", "facturas", "clientes", "empresas"]:
            try:
                dbutil.query(conn, f"DELETE FROM {tabla}")
            except Exception:
                pass
    conn.close()


@pytest.fixture
def setup_db():
    db.init_db()
    _limpiar()
    yield
    _limpiar()


def _setup_empresa_cliente():
    conn = db.get_connection()
    with conn:
        emp_cur = dbutil.query(conn,
            "INSERT INTO empresas (nit, dv, razon_social, direccion, municipio, clave_tecnica, tipo_ambiente, prefijo_resolucion, rango_desde, rango_hasta, resolucion_dian, fecha_resolucion) "
            "VALUES ('9001234567', '1', 'TestCo SAS', 'Cra 1 #2', 'Bogotá', '3fa9c0b1d2e34f5a6b7c8d9e0f1a2b3c', '1', 'PRUE', 990000000, 999999999, '18760000003', '2026-01-15') "
            "RETURNING id"
        )
        empresa_id = emp_cur.fetchone()["id"]
        dbutil.query(conn, 
            "INSERT INTO clientes (nit, dv, tipo_documento, razon_social, direccion, municipio, empresa_id) "
            "VALUES ('8007654321', '2', 'NIT', 'Adquirente SA', 'Av 3 #4', 'Bogotá', ?)",
            (empresa_id,)
        )
    conn.close()


def _emitir_factura_test(cliente_nit="8007654321", subtotal="1000000.00", iva_19="190000.00") -> int:
    datos_fac = {
        "consecutivo": "0000000001",
        "prefijo": "PRUE",
        "fecha": "2026-01-15",
        "hora": "10:00:00-05:00",
        "cliente_nit": cliente_nit,
        "subtotal": subtotal,
        "iva_19": iva_19,
        "iva_5": "0.00",
        "iva_0": "0.00",
        "total_iva": iva_19,
        "retefuente": "0.00",
        "reteica": "0.00",
        "reteiva": "0.00",
        "total_factura": str(Decimal(subtotal) + Decimal(iva_19)),
        "cufe": "a" * 96,
        "qr": "TEST_QR",
        "xml_ubl": "<Invoice/>",
        "estado_dian": "EXITOSA",
        "track_id": "TRK-TEST-001",
        "mensaje_dian": "OK",
        "created_at": "2026-01-15T10:00:00",
    }
    lineas = [{
        "producto_codigo": "P001",
        "descripcion": "Producto Prueba",
        "cantidad": "1",
        "valor_unitario": subtotal,
        "subtotal": subtotal,
        "tarifa_iva": "IVA_19",
        "valor_iva": iva_19,
        "tipo_bien_servicio": "10",
    }]
    fac_id = db.guardar_factura(datos_fac, lineas)
    return fac_id


# === RADIAN Tests ===

class TestRADIAN:
    def test_evento_030_acuse_recibo(self, setup_db):
        """Evento 030: Acuse de recibo de la Factura Electrónica de Venta."""
        _setup_empresa_cliente()
        fac_id = _emitir_factura_test()

        resultado = radian.registrar_evento_radian(fac_id, "030")

        assert resultado["evento"]["tipo_evento"] == "030"
        assert resultado["evento"]["codigo_evento"] == "030"
        assert resultado["evento"]["estado_dian"] == "Aceptada"
        assert resultado["descripcion"] == "Acuse de Recibo de la Factura Electrónica de Venta"
        assert resultado["cude"] and len(resultado["cude"]) == 96
        assert "ApplicationResponse" in resultado["xml"]

    def test_evento_032_recepcion_bienes(self, setup_db):
        """Evento 032: Recepción de Bienes y/o Prestación de Servicios."""
        _setup_empresa_cliente()
        fac_id = _emitir_factura_test()

        resultado = radian.registrar_evento_radian(fac_id, "032")

        assert resultado["evento"]["tipo_evento"] == "032"
        assert "Recepción" in resultado["descripcion"]
        assert "ApplicationResponse" in resultado["xml"]

    def test_evento_033_aceptacion_expresa(self, setup_db):
        """Evento 033: Aceptación Expresa de la Factura."""
        _setup_empresa_cliente()
        fac_id = _emitir_factura_test()

        resultado = radian.registrar_evento_radian(fac_id, "033")

        assert resultado["evento"]["tipo_evento"] == "033"
        assert "Aceptación" in resultado["descripcion"]

    def test_evento_034_aceptacion_tacita(self, setup_db):
        """Evento 034: Aceptación Tácita a los 3 días hábiles."""
        _setup_empresa_cliente()
        fac_id = _emitir_factura_test()

        resultado = radian.registrar_evento_radian(fac_id, "034")

        assert resultado["evento"]["tipo_evento"] == "034"
        assert "Tácita" in resultado["descripcion"]

    def test_evento_codigo_invalido(self, setup_db):
        """Código de evento inválido debe lanzar ValueError."""
        _setup_empresa_cliente()
        fac_id = _emitir_factura_test()

        with pytest.raises(ValueError, match="inválido"):
            radian.registrar_evento_radian(fac_id, "999")

    def test_evento_factura_no_existe(self, setup_db):
        """Factura inexistente debe lanzar ValueError."""
        _setup_empresa_cliente()

        with pytest.raises(ValueError, match="no encontrada"):
            radian.registrar_evento_radian(99999, "030")

    def test_evento_cu_estructura(self, setup_db):
        """El CUDE debe ser SHA-384 de 96 caracteres."""
        _setup_empresa_cliente()
        fac_id = _emitir_factura_test()

        resultado = radian.registrar_evento_radian(fac_id, "030")
        cude = resultado["cude"]

        assert len(cude) == 96
        assert all(c in "0123456789abcdef" for c in cude)

    def test_evento_xml_estructura(self, setup_db):
        """El XML debe contener ApplicationResponse con referencia al CUFE."""
        _setup_empresa_cliente()
        fac_id = _emitir_factura_test()

        resultado = radian.registrar_evento_radian(fac_id, "030")
        xml = resultado["xml"]

        assert "<ApplicationResponse" in xml
        assert "dian:ObligationReferenceID" in xml
        assert "a" * 96 in xml
        assert "CoDian10" in xml

    def test_eventos_por_factura(self, setup_db):
        """Debe listar todos los eventos de una factura."""
        _setup_empresa_cliente()
        fac_id = _emitir_factura_test()

        radian.registrar_evento_radian(fac_id, "030")
        radian.registrar_evento_radian(fac_id, "032")
        radian.registrar_evento_radian(fac_id, "033")

        eventos = radian.obtener_eventos_factura(fac_id)
        assert len(eventos) == 3
        codigos = [e["codigo_evento"] for e in eventos]
        assert "030" in codigos
        assert "032" in codigos
        assert "033" in codigos

    def test_evento_con_observaciones(self, setup_db):
        """El XML debe incluir observaciones si se proporcionan."""
        _setup_empresa_cliente()
        fac_id = _emitir_factura_test()

        resultado = radian.registrar_evento_radian(fac_id, "030", observaciones="Bienes verificados")
        assert "Bienes verificados" in resultado["xml"]


# === Notas Débito Tests ===

class TestNotasDebito:
    @pytest.fixture(autouse=True)
    def mock_dian(self):
        mock_result = TransmisionResult(estado="Aceptada", track_id="TRK-TEST", status_code="00", status_description="OK")
        with unittest.mock.patch.object(DianClient, "transmitir_xml", return_value=mock_result):
            yield

    def test_concepto_1_intereses(self, setup_db):
        """Concepto DIAN 1: Intereses."""
        _setup_empresa_cliente()
        fac_id = _emitir_factura_test()

        resultado = debit_notes.emitir_nota_debito(
            factura_id=fac_id,
            concepto_dian="1",
            subtotal="50000.00",
            iva_19="9500.00",
            descripcion="Intereses moratorios",
        )

        nd = resultado["nota_debito"]
        assert nd["concepto_dian"] == "1"
        assert nd["total_nota"] == "59500.00"
        assert "Intereses" in nd["descripcion_motivo"]

    def test_concepto_2_gastos_por_cobrar(self, setup_db):
        """Concepto DIAN 2: Gastos por cobrar."""
        _setup_empresa_cliente()
        fac_id = _emitir_factura_test()

        resultado = debit_notes.emitir_nota_debito(
            factura_id=fac_id,
            concepto_dian="2",
            subtotal="30000.00",
            iva_19="5700.00",
        )

        nd = resultado["nota_debito"]
        assert nd["concepto_dian"] == "2"
        assert "Gastos por cobrar" in nd["descripcion_motivo"]

    def test_concepto_3_cambio_valor(self, setup_db):
        """Concepto DIAN 3: Cambio de valor."""
        _setup_empresa_cliente()
        fac_id = _emitir_factura_test()

        resultado = debit_notes.emitir_nota_debito(
            factura_id=fac_id,
            concepto_dian="3",
            subtotal="20000.00",
        )

        nd = resultado["nota_debito"]
        assert nd["concepto_dian"] == "3"

    def test_concepto_4_otros(self, setup_db):
        """Concepto DIAN 4: Otros."""
        _setup_empresa_cliente()
        fac_id = _emitir_factura_test()

        resultado = debit_notes.emitir_nota_debito(
            factura_id=fac_id,
            concepto_dian="4",
            subtotal="10000.00",
        )

        nd = resultado["nota_debito"]
        assert nd["concepto_dian"] == "4"

    def test_concepto_invalido(self, setup_db):
        """Concepto DIAN inválido debe lanzar ValueError."""
        _setup_empresa_cliente()
        fac_id = _emitir_factura_test()

        with pytest.raises(ValueError, match="inválido"):
            debit_notes.emitir_nota_debito(fac_id, "99", "10000.00")

    def test_factura_no_existe(self, setup_db):
        """Factura inexistente debe lanzar ValueError."""
        _setup_empresa_cliente()

        with pytest.raises(ValueError, match="no encontrada"):
            debit_notes.emitir_nota_debito(99999, "1", "10000.00")

    def test_xml_tipo_92(self, setup_db):
        """El XML debe ser DebitNote tipo 92 con referencia al CUFE."""
        _setup_empresa_cliente()
        fac_id = _emitir_factura_test()

        resultado = debit_notes.emitir_nota_debito(
            factura_id=fac_id,
            concepto_dian="1",
            subtotal="50000.00",
            iva_19="9500.00",
        )

        xml = resultado["nota_debito"]["xml_ubl"]
        assert "<DebitNote" in xml
        assert "92" in xml
        assert "a" * 96 in xml

    def test_cude_calculado(self, setup_db):
        """El CUDE debe ser SHA-384 válido."""
        _setup_empresa_cliente()
        fac_id = _emitir_factura_test()

        resultado = debit_notes.emitir_nota_debito(
            factura_id=fac_id,
            concepto_dian="1",
            subtotal="50000.00",
        )

        cude = resultado["nota_debito"]["cude"]
        assert len(cude) == 96

    def test_saldo_factura_aumenta(self, setup_db):
        """El saldo pendiente de la factura debe aumentar con la Nota Débito."""
        _setup_empresa_cliente()
        fac_id = _emitir_factura_test(subtotal="1000000.00", iva_19="190000.00")

        resultado = debit_notes.emitir_nota_debito(
            factura_id=fac_id,
            concepto_dian="1",
            subtotal="50000.00",
            iva_19="9500.00",
        )

        factura = db.get_factura_by_id(fac_id)
        assert Decimal(factura["saldo_pendiente"]) > Decimal("1190000.00")

    def test_asiento_contable(self, setup_db):
        """El asiento debe tener 1305 Debito y crédito a ingreso."""
        _setup_empresa_cliente()
        fac_id = _emitir_factura_test()

        resultado = debit_notes.emitir_nota_debito(
            factura_id=fac_id,
            concepto_dian="1",
            subtotal="50000.00",
            iva_19="9500.00",
        )

        asiento = resultado["asiento_contable"]
        movimientos = asiento["movimientos"]
        cuenta_debito = [m for m in movimientos if m["cuenta_codigo"] == "130505"]
        assert len(cuenta_debito) == 1
        assert cuenta_debito[0]["debito"] == "59500.00"
        assert cuenta_debito[0]["credito"] == "0.00"

    def test_multi_lineas(self, setup_db):
        """Nota Débito con múltiples líneas."""
        _setup_empresa_cliente()
        fac_id = _emitir_factura_test()

        lineas = [
            {"producto_codigo": "ND-01", "descripcion": "Intereses 1er período", "cantidad": 1, "valor_unitario": "30000.00", "subtotal": "30000.00", "tarifa_iva": "IVA_19", "valor_iva": "5700.00"},
            {"producto_codigo": "ND-02", "descripcion": "Intereses 2do período", "cantidad": 1, "valor_unitario": "20000.00", "subtotal": "20000.00", "tarifa_iva": "IVA_19", "valor_iva": "3800.00"},
        ]
        resultado = debit_notes.emitir_nota_debito(
            factura_id=fac_id,
            concepto_dian="1",
            subtotal="50000.00",
            iva_19="9500.00",
            lineas=lineas,
        )

        nd = resultado["nota_debito"]
        assert nd["subtotal"] == "50000.00"
        assert nd["total_iva"] == "9500.00"
        assert nd["total_nota"] == "59500.00"
