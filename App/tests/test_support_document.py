"""Pruebas para el módulo de Documento Soporte para No Obligados a Facturar."""

import xml.etree.ElementTree as ET
from decimal import Decimal

import pytest

import sap_colombia.database as db
from sap_colombia.support_document import (
    calculate_cuds,
    cuds_base,
    crear_documento_soporte,
)


@pytest.fixture(autouse=True)
def setup_db():
    db.init_db()


def test_calculate_cuds_sha384():
    cuds1 = calculate_cuds("DS-0001", "2026-10-10", "12:00:00-05:00",
                           Decimal("100000.00"), "900123456", "NIT",
                           "clave123", "2", Decimal("90000.00"))
    cuds2 = calculate_cuds("DS-0001", "2026-10-10", "12:00:00-05:00",
                           Decimal("100000.00"), "900123456", "NIT",
                           "clave123", "2", Decimal("90000.00"))
    assert len(cuds1) == 96
    assert cuds1 == cuds2
    assert cuds1 == cuds2


def test_crear_documento_soporte_completo():
    lineas = [
        {"descripcion": "Servicio técnico", "cantidad": "1",
         "valor_unitario": "500000.00", "subtotal": "500000.00"},
        {"descripcion": "Consultoría", "cantidad": "2",
         "valor_unitario": "250000.00", "subtotal": "500000.00"},
    ]
    datos = {"proveedor_nit": "800197268", "proveedor_nombre": "Proveedor Test"}

    resultado = crear_documento_soporte(datos, lineas)

    assert "documento" in resultado
    assert "id" in resultado
    assert "cuds" in resultado
    assert "asiento" in resultado
    assert "xml_ubl" in resultado

    doc = resultado["documento"]
    assert Decimal(doc["subtotal"]) == Decimal("1000000.00")
    assert Decimal(doc["retefuente"]) == Decimal("35000.00")
    assert Decimal(doc["reteica"]) == Decimal("6900.00")
    assert Decimal(doc["total_documento"]) == Decimal("958100.00")

    asiento = resultado["asiento"]
    assert asiento is not None
    assert asiento["tipo_documento"] == "DOCUMENTO_SOPORTE"
    assert Decimal(asiento["total_debito"]) == Decimal("1000000.00")
    assert Decimal(asiento["total_credito"]) == Decimal("1000000.00")


def test_partida_doble_documento_soporte():
    lineas = [
        {"descripcion": "Servicio técnico", "cantidad": "1",
         "valor_unitario": "500000.00", "subtotal": "500000.00"},
        {"descripcion": "Consultoría", "cantidad": "2",
         "valor_unitario": "250000.00", "subtotal": "500000.00"},
    ]
    datos = {"proveedor_nit": "800197268", "proveedor_nombre": "Proveedor Test"}

    resultado = crear_documento_soporte(datos, lineas)
    asiento = resultado["asiento"]

    movimientos = asiento["movimientos"]
    por_cuenta = {}
    for m in movimientos:
        cod = m["cuenta_codigo"]
        deb = to_decimal(m.get("debito", "0.00"))
        cred = to_decimal(m.get("credito", "0.00"))
        por_cuenta[cod] = (por_cuenta.get(cod, (Decimal("0"), Decimal("0")))
                           + (Decimal("0"), Decimal("0")))
        por_cuenta[cod] = (por_cuenta[cod][0] + deb, por_cuenta[cod][1] + cred)

    deb_513501 = por_cuenta.get("513501", (Decimal("0"), Decimal("0")))[0]
    cred_236540 = por_cuenta.get("236540", (Decimal("0"), Decimal("0")))[1]
    cred_236801 = por_cuenta.get("236801", (Decimal("0"), Decimal("0")))[1]
    cred_220505 = por_cuenta.get("220505", (Decimal("0"), Decimal("0")))[1]

    assert deb_513501 == Decimal("1000000.00")
    assert cred_236540 == Decimal("35000.00")
    assert cred_236801 == Decimal("6900.00")
    assert cred_220505 == Decimal("958100.00")
    assert deb_513501 == cred_236540 + cred_236801 + cred_220505


def test_xml_ubl_tipo_05():
    lineas = [
        {"descripcion": "Servicio técnico", "cantidad": "1",
         "valor_unitario": "500000.00", "subtotal": "500000.00"},
    ]
    datos = {"proveedor_nit": "800197268", "proveedor_nombre": "Proveedor Test"}

    resultado = crear_documento_soporte(datos, lineas)
    xml_ubl = resultado["xml_ubl"]

    assert "InvoiceTypeCode" in xml_ubl
    assert "CustomizationID" in xml_ubl
    assert "ObligationReferenceID" in xml_ubl
    assert "QRCode" in xml_ubl

    root = ET.fromstring(xml_ubl)
    ns = {"cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
          "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"}

    type_code = root.find("cbc:InvoiceTypeCode", ns)
    assert type_code is not None
    assert type_code.text == "05"

    customization = root.find("cbc:CustomizationID", ns)
    assert customization is not None
    assert customization.text == "10"

    qr = root.find("cac:QRCode", ns)
    assert qr is not None
    assert qr.text is not None


def test_recuperar_desde_db():
    lineas = [
        {"descripcion": "Servicio técnico", "cantidad": "1",
         "valor_unitario": "500000.00", "subtotal": "500000.00"},
    ]
    datos = {"proveedor_nit": "800197268", "proveedor_nombre": "Proveedor Test"}

    resultado = crear_documento_soporte(datos, lineas)
    ds_id = resultado["id"]

    recuperado = db.get_documento_soporte_by_id(ds_id)
    assert recuperado is not None
    assert recuperado["id"] == ds_id
    assert recuperado["proveedor_nit"] == "800197268"
    assert recuperado["cuds"] == resultado["cuds"]
    assert len(recuperado["lineas"]) == 1


def to_decimal(valor):
    if valor is None:
        return Decimal("0.00")
    try:
        return Decimal(str(valor)).quantize(Decimal("0.01"))
    except Exception:
        return Decimal("0.00")
