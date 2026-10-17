"""Pruebas de la cartera y los recibos de caja de SAP Colombia."""

import re
from sap_colombia import dbutil
import pytest

import sap_colombia.database as db
from sap_colombia.accounts_receivable import calcular_edades_cartera, registrar_recibo_caja


@pytest.fixture(autouse=True)
def setup_db():
    db.init_db()
    conn = db.get_connection()
    try:
        for tabla in [
            "movimientos_contables",
            "recibos_caja",
            "factura_lineas",
            "lineas_nota_credito",
            "notas_credito",
            "asientos_contables",
            "facturas",
        ]:
            dbutil.query(conn, f"DELETE FROM {tabla}")
        conn.commit()
    finally:
        conn.close()


def _crear_factura(total: str, saldo: str, fecha: str, vencimiento: str) -> int:
    return db.guardar_factura(
        {
            "consecutivo": "1",
            "prefijo": "SETP",
            "fecha": fecha,
            "cliente_nit": "800197268",
            "total_factura": total,
            "saldo_pendiente": saldo,
            "fecha_vencimiento": vencimiento,
        },
        [],
    )


def test_calcular_edades_cartera_clasificacion():
    corte = "2026-10-15"
    facturas = {
        "corriente": _crear_factura("100000.00", "100000.00", "2026-10-01", "2026-10-20"),
        "1_a_30": _crear_factura("20000.00", "20000.00", "2026-09-20", "2026-10-10"),
        "31_a_60": _crear_factura("30000.00", "30000.00", "2026-08-20", "2026-09-01"),
        "61_a_90": _crear_factura("40000.00", "40000.00", "2026-07-20", "2026-08-01"),
        "mas_90": _crear_factura("50000.00", "50000.00", "2026-05-01", "2026-05-15"),
    }

    reporte = calcular_edades_cartera(corte)
    detalle = {item["id"]: item for item in reporte["detalle"]}

    for categoria, factura_id in facturas.items():
        assert detalle[factura_id]["categoria"] == categoria

    assert reporte["resumen"]["corriente"] == "100000.00"
    assert reporte["resumen"]["1_a_30"] == "20000.00"
    assert reporte["resumen"]["31_a_60"] == "30000.00"
    assert reporte["resumen"]["61_a_90"] == "40000.00"
    assert reporte["resumen"]["mas_90"] == "50000.00"
    assert reporte["total_saldo"] == "240000.00"


def test_registrar_recibo_caja_parcial():
    factura_id = _crear_factura("1000000.00", "1000000.00", "2026-10-01", "2026-10-31")

    resultado = registrar_recibo_caja(factura_id, "500000.00")

    assert re.fullmatch(r"RC-\d{4}", resultado["recibo"]["numero"])
    assert resultado["nuevo_saldo"] == "500000.00"
    assert resultado["estado_cartera"] == "PAGADA_PARCIAL"
    assert resultado["asiento"]["total_debito"] == "500000.00"
    assert resultado["asiento"]["total_credito"] == "500000.00"

    factura = db.get_factura_by_id(factura_id)
    assert factura["saldo_pendiente"] == "500000.00"
    assert factura["estado_cartera"] == "PAGADA_PARCIAL"


def test_registrar_recibo_caja_total():
    factura_id = _crear_factura("500000.00", "500000.00", "2026-10-01", "2026-10-31")

    resultado = registrar_recibo_caja(factura_id, "500000.00")

    assert resultado["nuevo_saldo"] == "0.00"
    assert resultado["estado_cartera"] == "PAGADA_TOTAL"

    factura = db.get_factura_by_id(factura_id)
    assert factura["saldo_pendiente"] == "0.00"
    assert factura["estado_cartera"] == "PAGADA_TOTAL"


def test_registrar_recibo_caja_validaciones():
    factura_id = _crear_factura("1000000.00", "1000000.00", "2026-10-01", "2026-10-31")

    with pytest.raises(ValueError):
        registrar_recibo_caja(999999, "100000.00")
    with pytest.raises(ValueError):
        registrar_recibo_caja(factura_id, "-100000.00")
    with pytest.raises(ValueError):
        registrar_recibo_caja(factura_id, "2000000.00")
