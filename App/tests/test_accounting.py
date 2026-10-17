"""Pruebas unitarias para el motor contable PUC y partida doble de SAP Colombia."""

import pytest
from decimal import Decimal
import sap_colombia.database as db
from sap_colombia.accounting_engine import (
    validar_partida_doble,
    contabilizar_factura_venta,
    contabilizar_nota_credito,
    contabilizar_recibo_caja,
    contabilizar_documento_soporte,
    generar_balance_prueba,
    AsientoDescuadradoError,
)


@pytest.fixture(autouse=True)
def setup_db():
    db.init_db()


def test_validar_partida_doble_exitosa():
    movimientos = [
        {"debito": "1190000.00", "credito": "0.00"},
        {"debito": "0.00", "credito": "1000000.00"},
        {"debito": "0.00", "credito": "190000.00"},
    ]
    cuadrado, total_deb, total_cred = validar_partida_doble(movimientos)
    assert cuadrado is True
    assert total_deb == Decimal("1190000.00")
    assert total_cred == Decimal("1190000.00")


def test_validar_partida_doble_falla_descuadrada():
    movimientos = [
        {"debito": "1000000.00", "credito": "0.00"},
        {"debito": "0.00", "credito": "950000.00"},
    ]
    cuadrado, total_deb, total_cred = validar_partida_doble(movimientos)
    assert cuadrado is False
    assert total_deb != total_cred


def test_contabilizar_factura_venta_con_retenciones():
    # Factura con IVA 19%, Retefuente 2.5%, ReteIVA 15% s/IVA, ReteICA 6.9/1000
    # Subtotal: 1,000,000 | IVA: 190,000 | Retefuente: 25,000 | ReteIVA: 28,500 | ReteICA: 6,900
    # Total Neto: 1,000,000 + 190,000 - 25,000 - 28,500 - 6,900 = 1,129,600
    factura = {
        "id": 999,
        "consecutivo": "990001",
        "prefijo": "SETP",
        "fecha": "2026-10-10",
        "cliente_nit": "800197268",
        "subtotal": "1000000.00",
        "iva_19": "190000.00",
        "iva_5": "0.00",
        "retefuente": "25000.00",
        "reteiva": "28500.00",
        "reteica": "6900.00",
        "total_factura": "1129600.00",
    }
    
    asiento = contabilizar_factura_venta(factura)
    assert asiento is not None
    assert asiento["tipo_documento"] == "FACTURA_VENTA"
    assert Decimal(asiento["total_debito"]) == Decimal("1190000.00")
    assert Decimal(asiento["total_credito"]) == Decimal("1190000.00")
    assert Decimal(asiento["total_debito"]) == Decimal(asiento["total_credito"])


def test_contabilizar_nota_credito_reversion():
    nc = {
        "id": 888,
        "consecutivo": "1",
        "prefijo": "NC",
        "fecha": "2026-10-10",
        "cliente_nit": "800197268",
        "subtotal": "500000.00",
        "total_iva": "95000.00",
        "retefuente": "12500.00",
        "reteiva": "14250.00",
        "reteica": "3450.00",
        "total_nota": "564800.00",
        "factura_consecutivo": "SETP-990001",
    }
    asiento = contabilizar_nota_credito(nc)
    assert asiento is not None
    assert asiento["tipo_documento"] == "NOTA_CREDITO"
    # Débitos: 500,000 (devolución) + 95,000 (iva) = 595,000
    # Créditos: 12,500 + 14,250 + 3,450 + 564,800 = 595,000
    assert Decimal(asiento["total_debito"]) == Decimal("595000.00")
    assert Decimal(asiento["total_credito"]) == Decimal("595000.00")


def test_contabilizar_recibo_caja():
    rc = {
        "id": 777,
        "numero": "RC-0001",
        "fecha": "2026-10-10",
        "cliente_nit": "800197268",
        "monto": "500000.00",
        "medio_pago": "TRANSFERENCIA",
    }
    asiento = contabilizar_recibo_caja(rc)
    assert asiento is not None
    assert Decimal(asiento["total_debito"]) == Decimal("500000.00")
    assert Decimal(asiento["total_credito"]) == Decimal("500000.00")


def test_contabilizar_documento_soporte():
    ds = {
        "id": 666,
        "consecutivo": "1",
        "prefijo": "DS",
        "fecha": "2026-10-10",
        "proveedor_nit": "1234567890",
        "proveedor_nombre": "Carlos Rodríguez",
        "subtotal": "300000.00",
        "retefuente": "10500.00",  # 3.5%
        "reteica": "2070.00",     # 6.9/1000
        "total_documento": "287430.00",
    }
    asiento = contabilizar_documento_soporte(ds)
    assert asiento is not None
    assert Decimal(asiento["total_debito"]) == Decimal("300000.00")
    assert Decimal(asiento["total_credito"]) == Decimal("300000.00")


def test_balance_de_prueba():
    balance = generar_balance_prueba()
    assert "cuentas" in balance
    assert Decimal(balance["total_debitos"]) == Decimal(balance["total_creditos"])
    assert balance["balance_cuadrado"] is True
