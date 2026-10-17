"""Pruebas unitarias TDD para el módulo de Kárdex de Inventario con Costeo Promedio Ponderado."""

import os
from sap_colombia import dbutil
import sys
from decimal import Decimal

import pytest

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(BASE_DIR)
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from sap_colombia import database as db
from sap_colombia import inventory
from sap_colombia.inventory import InventarioError


def _empresa_id() -> int:
    conn = db.get_connection()
    fila = dbutil.query(conn, "SELECT id FROM empresas ORDER BY id LIMIT 1").fetchone()
    conn.close()
    return fila["id"]


@pytest.fixture
def setup_db():
    db.init_db()
    conn = db.get_connection()
    with conn:
        dbutil.query(conn, "DELETE FROM stock_actual")
        dbutil.query(conn, "DELETE FROM kardex")
    conn.close()
    yield
    conn = db.get_connection()
    with conn:
        dbutil.query(conn, "DELETE FROM stock_actual")
        dbutil.query(conn, "DELETE FROM kardex")
    conn.close()


def test_entrada_aumenta_existencias(setup_db):
    resultado = inventory.registrar_entrada(
        producto_codigo="P001",
        bodega_codigo="BODEGA-01",
        cantidad=Decimal("100"),
        costo_unitario=Decimal("50000.00"),
        referencia_documento="COMPRA-001",
        fecha="2026-01-15",
    )
    assert resultado["saldo_nuevo"] == "100"
    assert resultado["costo_promedio"] == "50000.00"
    assert resultado["costo_total_saldo"] == "5000000.00"

    stock = db.get_stock_actual(producto_codigo="P001", bodega_codigo="BODEGA-01")
    assert len(stock) == 1
    assert stock[0]["cantidad"] == "100"
    assert stock[0]["costo_promedio"] == "50000.00"


def test_entrada_recalcula_costo_promedio(setup_db):
    inventory.registrar_entrada(
        producto_codigo="P001",
        bodega_codigo="BODEGA-01",
        cantidad=Decimal("100"),
        costo_unitario=Decimal("50000.00"),
        fecha="2026-01-15",
    )
    inventory.registrar_entrada(
        producto_codigo="P001",
        bodega_codigo="BODEGA-01",
        cantidad=Decimal("100"),
        costo_unitario=Decimal("60000.00"),
        fecha="2026-01-20",
    )

    stock = db.get_stock_actual(producto_codigo="P001", bodega_codigo="BODEGA-01")
    assert len(stock) == 1
    assert stock[0]["cantidad"] == "200"
    # (100 * 50000 + 100 * 60000) / 200 = 55000
    assert stock[0]["costo_promedio"] == "55000.00"


def test_salida_descuenta_stock(setup_db):
    inventory.registrar_entrada(
        producto_codigo="P001",
        bodega_codigo="BODEGA-01",
        cantidad=Decimal("100"),
        costo_unitario=Decimal("50000.00"),
        fecha="2026-01-15",
    )
    resultado = inventory.registrar_salida(
        producto_codigo="P001",
        bodega_codigo="BODEGA-01",
        cantidad=Decimal("30"),
        referencia_documento="FACT-001",
        fecha="2026-01-25",
    )
    assert resultado["saldo_nuevo"] == "70"
    assert resultado["costo_total_saldo"] == "3500000.00"

    stock = db.get_stock_actual(producto_codigo="P001", bodega_codigo="BODEGA-01")
    assert stock[0]["cantidad"] == "70"


def test_salida_sin_stock_arroja_error(setup_db):
    with pytest.raises(InventarioError, match="No hay existencias"):
        inventory.registrar_salida(
            producto_codigo="P999",
            bodega_codigo="BODEGA-01",
            cantidad=Decimal("10"),
        )


def test_salida_excede_stock_arroja_error(setup_db):
    inventory.registrar_entrada(
        producto_codigo="P001",
        bodega_codigo="BODEGA-01",
        cantidad=Decimal("50"),
        costo_unitario=Decimal("10000.00"),
        fecha="2026-01-15",
    )
    with pytest.raises(InventarioError, match="Saldo insuficiente"):
        inventory.registrar_salida(
            producto_codigo="P001",
            bodega_codigo="BODEGA-01",
            cantidad=Decimal("51"),
        )


def test_devolucion_reingresa_existencias(setup_db):
    inventory.registrar_entrada(
        producto_codigo="P001",
        bodega_codigo="BODEGA-01",
        cantidad=Decimal("100"),
        costo_unitario=Decimal("50000.00"),
        fecha="2026-01-15",
    )
    inventory.registrar_salida(
        producto_codigo="P001",
        bodega_codigo="BODEGA-01",
        cantidad=Decimal("20"),
        referencia_documento="FACT-001",
        fecha="2026-01-25",
    )
    resultado = inventory.registrar_devolucion(
        producto_codigo="P001",
        bodega_codigo="BODEGA-01",
        cantidad=Decimal("10"),
        referencia_documento="NC-001",
        fecha="2026-02-01",
    )
    assert resultado["saldo_nuevo"] == "90"

    stock = db.get_stock_actual(producto_codigo="P001", bodega_codigo="BODEGA-01")
    assert stock[0]["cantidad"] == "90"


def test_kardex_registra_movimientos(setup_db):
    inventory.registrar_entrada(
        producto_codigo="P001",
        bodega_codigo="BODEGA-01",
        cantidad=Decimal("100"),
        costo_unitario=Decimal("50000.00"),
        fecha="2026-01-15",
    )
    inventory.registrar_salida(
        producto_codigo="P001",
        bodega_codigo="BODEGA-01",
        cantidad=Decimal("30"),
        referencia_documento="FACT-001",
        fecha="2026-01-25",
    )

    kardex = db.get_kardex(producto_codigo="P001", bodega_codigo="BODEGA-01")
    assert len(kardex) == 2
    assert kardex[0]["tipo_movimiento"] == "SALIDA"
    assert kardex[0]["cantidad_salida"] == "30"
    assert kardex[0]["saldo_cantidad"] == "70"
    assert kardex[1]["tipo_movimiento"] == "ENTRADA"
    assert kardex[1]["cantidad_entrada"] == "100"


def test_multibodega(setup_db):
    inventory.registrar_entrada(
        producto_codigo="P001",
        bodega_codigo="BODEGA-01",
        cantidad=Decimal("50"),
        costo_unitario=Decimal("10000.00"),
        fecha="2026-01-15",
    )
    inventory.registrar_entrada(
        producto_codigo="P001",
        bodega_codigo="BODEGA-02",
        cantidad=Decimal("80"),
        costo_unitario=Decimal("12000.00"),
        fecha="2026-01-15",
    )

    stock_b1 = db.get_stock_actual(producto_codigo="P001", bodega_codigo="BODEGA-01")
    stock_b2 = db.get_stock_actual(producto_codigo="P001", bodega_codigo="BODEGA-02")
    assert stock_b1[0]["cantidad"] == "50"
    assert stock_b2[0]["cantidad"] == "80"
    assert stock_b2[0]["costo_promedio"] == "12000.00"


def test_registrar_factura_descuenta_stock(setup_db):
    inventory.registrar_entrada(
        producto_codigo="P001",
        bodega_codigo="BODEGA-01",
        cantidad=Decimal("100"),
        costo_unitario=Decimal("10000.00"),
        fecha="2026-01-15",
    )
    lineas = [
        {"producto_codigo": "P001", "cantidad": Decimal("25")},
    ]
    inventory.registrar_factura(factura_id=1, lineas=lineas)

    stock = db.get_stock_actual(producto_codigo="P001", bodega_codigo="BODEGA-01")
    assert stock[0]["cantidad"] == "75"


def test_registrar_nota_credito_reingresa_stock(setup_db):
    conn = db.get_connection()
    with conn:
        dbutil.query(conn, "DELETE FROM movimientos_contables")
        dbutil.query(conn, "DELETE FROM asientos_contables")
    conn.close()
    inventory.registrar_entrada(
        producto_codigo="P001",
        bodega_codigo="BODEGA-01",
        cantidad=Decimal("100"),
        costo_unitario=Decimal("10000.00"),
        fecha="2026-01-15",
    )
    lineas = [
        {"producto_codigo": "P001", "cantidad": Decimal("25")},
    ]
    inventory.registrar_factura(factura_id=1, lineas=lineas)
    inventory.registrar_nota_credito(nc_id=1, lineas=lineas)

    stock = db.get_stock_actual(producto_codigo="P001", bodega_codigo="BODEGA-01")
    assert stock[0]["cantidad"] == "100"


# ---------------------------------------------------------------------------
# Contabilización del inventario (kárdex -> partida doble)
# ---------------------------------------------------------------------------

def test_venta_genera_asiento_de_costo_de_ventas():
    """Antes el kárdex se movía sin asiento: el balance mostraba 0 en inventario."""
    from decimal import Decimal
    from sap_colombia import database as db, dbutil, inventory
    from sap_colombia import inventory_accounting as ia

    conn = db.get_connection()
    with conn:
        dbutil.query(conn, "DELETE FROM movimientos_contables")
        dbutil.query(conn, "DELETE FROM asientos_contables")
        dbutil.query(conn, "DELETE FROM kardex")
        dbutil.query(conn, "DELETE FROM stock_actual")
        dbutil.query(conn, "DELETE FROM productos WHERE codigo = 'TESTCONT'")
        dbutil.query(
            conn,
            "INSERT INTO productos (empresa_id, codigo, descripcion, precio_unitario, "
            "tarifa_iva, tipo_bien_servicio, unidad_medida, stock_minimo) "
            "VALUES (?, 'TESTCONT', 'Producto prueba', '100000', 'IVA_19', 'BIENES', 'UNO', '1')",
            (_empresa_id(),),
        )
    conn.close()

    inventory.registrar_entrada(
        "TESTCONT", "BODEGA-01", Decimal(10), Decimal(50000),
        referencia_documento="COMPRA-T1", contabilizar=True,
    )
    resultado = inventory.registrar_factura(
        9001, [{"producto_codigo": "TESTCONT", "cantidad": "4"}]
    )
    assert resultado["costo_ventas"] == "200000.00"

    conn = db.get_connection()
    movimientos = dbutil.query(
        conn,
        "SELECT cuenta_codigo, debito, credito FROM movimientos_contables "
        "WHERE cuenta_codigo IN ('530501','143501') ORDER BY cuenta_codigo",
    ).fetchall()
    conn.close()
    saldos = {m["cuenta_codigo"]: (m["debito"], m["credito"]) for m in movimientos}
    # Costo de ventas 200.000 D / Inventario 300.000 D (500 compra - 200 venta) 500 C
    assert saldos["530501"] == ("200000.00", "0.00")


def test_inventario_concilia_kardex_contra_libro():
    from decimal import Decimal
    from sap_colombia import database as db, dbutil, inventory
    from sap_colombia import inventory_accounting as ia

    conn = db.get_connection()
    with conn:
        dbutil.query(conn, "DELETE FROM movimientos_contables")
        dbutil.query(conn, "DELETE FROM asientos_contables")
        dbutil.query(conn, "DELETE FROM kardex")
        dbutil.query(conn, "DELETE FROM stock_actual")
    conn.close()

    inventory.registrar_entrada(
        "TESTCONT", "BODEGA-01", Decimal(10), Decimal(50000),
        referencia_documento="COMPRA-T2", contabilizar=True,
    )
    inventory.registrar_factura(
        9002, [{"producto_codigo": "TESTCONT", "cantidad": "4"}]
    )
    inventory.registrar_nota_credito(
        8002, [{"producto_codigo": "TESTCONT", "cantidad": "1"}]
    )

    resultado = ia.conciliar_inventario()[0]
    assert resultado["conciliado"] is True, (
        f"El inventario físico ({resultado['saldo_kardex']}) no coincide con "
        f"el libro ({resultado['saldo_contable']})"
    )
    assert resultado["diferencia"] == "0.00"


def test_guardar_asiento_no_sobrescribe_el_existente():
    """Regresión: la colisión de numero_comprobante destruía el asiento previo."""
    from sap_colombia import database as db, dbutil

    conn = db.get_connection()
    with conn:
        dbutil.query(conn, "DELETE FROM movimientos_contables")
        dbutil.query(conn, "DELETE FROM asientos_contables")
    conn.close()

    datos = {
        "numero_comprobante": "DUP-001",
        "fecha": "2026-01-01",
        "tipo_documento": "PRUEBA",
        "glosa": "Asiento original",
        "total_debito": "100.00",
        "total_credito": "100.00",
    }
    movs = [{
        "cuenta_codigo": "143501", "concepto": "Original",
        "debito": "100.00", "credito": "0.00",
    }]
    db.guardar_asiento(datos, movs)
    with pytest.raises(db.AsientoDuplicadoError):
        db.guardar_asiento(
            {**datos, "glosa": "Asiente que intenta pisar"}, movs)

    conn = db.get_connection()
    filas = dbutil.query(
        conn,
        "SELECT glosa FROM asientos_contables WHERE numero_comprobante = 'DUP-001'",
    ).fetchall()
    total = dbutil.query(
        conn,
        "SELECT COUNT(*) AS n FROM movimientos_contables",
    ).fetchone()["n"]
    conn.close()
    assert len(filas) == 1
    assert filas[0]["glosa"] == "Asiento original"
    assert total == 1
