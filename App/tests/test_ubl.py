"""Pruebas de CUFE, cadena QR y estructura UBL/DIAN.

Comprueban el estándar real del «Anexo Técnico» de factura electrónica de venta:

- Namespaces UBL 2.1 (``Invoice-2``, ``CommonAggregateComponents-2``,
  ``CommonBasicComponents-2``) y la extensión DIAN con sufijo ``/v20``.
- CUFE de 96 hexadecimales sobre la cadena canónica, con redondeo comercial.
- QR de 10 campos con fecha y hora separadas.
- Partidos, documento de referencia, medio de pago y totales en
  ``cac:``/``cbc:``.
"""

import xml.etree.ElementTree as ET
from decimal import Decimal

from sap_colombia.cufe_calculator import (
    calculate_cufe,
    cufe_base,
    generar_cadena_qr,
)
from sap_colombia.tax_engine import LineaFactura
from sap_colombia.ubl_builder import (
    NS_CAC,
    NS_CBC,
    NS_DIAN,
    NS_UBL,
    NS_XSI,
    Adquirente,
    Emisor,
    UblInvoiceBuilder,
    calcular_cufe_de_factura,
)

CLAVE = "3fa9c0b1d2e34f5a6b7c8d9e0f1a2b3c"
NUM_FAC = "990000001"


def _lineas_prueba():
    return [
        LineaFactura(
            codigo="1001",
            descripcion="Producto",
            cantidad="1",
            valor_unitario="100000",
            clasificacion="EXENTO",
        )
    ]


def _builder():
    emisor = Emisor(
        nit="90012345678",
        nombre="Emisor SAS",
        direccion="Calle 1 # 1-1",
        ciudad="Bogotá",
        resolucion_dian="18760000001",
        fecha_resolucion="2026-01-15",
        nit_proveedor="800197268",
    )
    adquirente = Adquirente(
        nit="1234567890",
        nombre="Adquirente Ltda",
        direccion="Cra 2 # 2-2",
        ciudad="Bogotá",
    )
    return UblInvoiceBuilder(emisor, adquirente)


def _factura():
    return _builder().build(
        NUM_FAC, "2024-01-15", "10:30:00", _lineas_prueba(),
        clave_tecnica=CLAVE, tipo_ambiente="2",
    )


# ─── Cadena canónica del CUFE ───

def test_cufe_base_usa_rangos_de_autorizacion_completos():
    """El número conserva sus 9 dígitos cuando el rango DIAN lo autoriza."""
    base = cufe_base(
        NUM_FAC, "2024-01-15", "10:30:00", "119000.00",
        {"IVA_19": Decimal("19000")},
        "90012345678", "1234567890", CLAVE, "1", "119000.00",
    )
    assert base.startswith("990000001")      # número completo, no truncado a 8
    assert "20240115" in base[:32]            # fecha
    assert "103000" in base[:32]              # hora
    assert base.endswith("900123456781234567890" + CLAVE + "1")


def test_cufe_base_numero_corto_se_rellena_a_8():
    base = cufe_base(
        "1001", "2024-01-15", "10:30:00", "100000.00",
        {}, "900", "800", CLAVE, "1", "100000.00",
    )
    assert base.startswith("00001001")


def test_calculate_cufe_deterministico():
    args = (NUM_FAC, "2024-01-15", "10:30:00", "100000.00",
            {"IVA_19": Decimal("19000")},
            "90012345678", "1234567890", CLAVE, "1", "115460.00")
    cufe = calculate_cufe(*args)
    assert len(cufe) == 96
    assert cufe == cufe.lower()
    assert calculate_cufe(*args) == cufe       # determinista


def test_cufe_cambia_si_cambia_cualquier_campo():
    """Propiedad esencial del hash: mover un campo cambia el CUFE."""
    base = dict(
        num_fac=NUM_FAC, fecha="2024-01-15", hora="10:30:00",
        valor_factura="100000.00", categorias={"IVA_19": Decimal("19000")},
        nit_emisor="90012345678", nit_adquirente="1234567890",
        clave_tecnica=CLAVE, tipo_ambiente="1", valor_transaccion="115460.00",
    )
    original = calculate_cufe(**base)
    for campo, valor in [
        ("fecha", "2024-01-16"),
        ("hora", "10:30:01"),
        ("valor_factura", "100000.01"),
        ("nit_adquirente", "1234567891"),
        ("tipo_ambiente", "2"),
    ]:
        variante = dict(base, **{campo: valor})
        assert calculate_cufe(**variante) != original, campo


def test_cadena_qr_diez_campos():
    cufe = calculate_cufe(
        NUM_FAC, "2024-01-15", "10:30:00", "100000.00",
        {"IVA_19": Decimal("19000")},
        "90012345678", "1234567890", CLAVE, "1", "115460.00",
    )
    qr = generar_cadena_qr(
        "1", "01", "90012345678", NUM_FAC, "2024-01-15", "10:30:00",
        "115460.00", CLAVE, cufe,
    )
    partes = qr.split(";")
    assert len(partes) == 10
    assert partes == [
        "DIAN", "1", "01", "90012345678", "990000001",
        "20240115", "103000", "115460.00", CLAVE, cufe,
    ]


# ─── Builder ───

def test_builder_totales_y_cufe_consistente():
    factura = _factura()
    assert factura.valor_factura == Decimal("119000.00")     # base + IVA
    assert factura.valor_transaccion == Decimal("115460.00")  # menos retenciones
    from sap_colombia.tax_engine import TaxEngine
    esperado = calcular_cufe_de_factura(
        NUM_FAC, "2024-01-15", "10:30:00",
        TaxEngine().liquidar_factura(_lineas_prueba()),
        "90012345678", "1234567890", CLAVE, "2",
    )
    assert factura.cufe == esperado
    assert factura.qr.endswith(factura.cufe)
    assert len(factura.qr.split(";")) == 10


# ─── Estructura XML ───

def test_xml_raiz_y_namespaces():
    factura = _factura()
    root = ET.fromstring(factura.xml)

    assert root.tag == f"{{{NS_UBL}}}Invoice"
    # El namespace UBL debe ser el real de OASIS, no una URI inventada.
    assert NS_UBL == "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
    assert NS_CAC.endswith("CommonAggregateComponents-2")
    assert NS_CBC.endswith("CommonBasicComponents-2")
    assert NS_DIAN.endswith("/v20")
    assert root.get(f"{{{NS_XSI}}}schemaLocation")


def test_xml_campos_cbc_obligatorios():
    root = ET.fromstring(_factura().xml)

    def cbc(local):
        return root.find(f"{{{NS_CBC}}}{local}")

    assert cbc("UBLVersionID").text == "UBL 2.1"
    assert cbc("CustomizationID").text == "2.0"

    id_el = cbc("ID")
    assert id_el.get("schemeID") == "CUFE-SHA384"
    assert len(id_el.text.strip()) == 96

    assert cbc("IssueDate").get("schemeID") == "YYYY-MM-DD"
    assert cbc("IssueDate").text == "2024-01-15"
    assert cbc("IssueTime").get("schemeID") == "HH:MM:ss"
    assert cbc("IssueTime").text == "10:30:00"

    assert cbc("InvoiceTypeCode").text == "715"   # factura electrónica de venta
    assert len(cbc("Note").text.split(";")) == 10  # cadena QR


def test_xml_partidos_y_referencia_dian():
    root = ET.fromstring(_factura().xml)

    sup = root.find(f"{{{NS_CAC}}}AccountingSupplierParty")
    assert sup is not None, "Falta cac:AccountingSupplierParty"
    company = sup.find(f".//{{{NS_CBC}}}CompanyID")
    assert company.text == "90012345678"

    cus = root.find(f"{{{NS_CAC}}}AccountingCustomerParty")
    assert cus is not None, "Falta cac:AccountingCustomerParty"
    assert cus.find(f".//{{{NS_CBC}}}CompanyID").text == "1234567890"

    # Autorización de numeración (obligatoria)
    ref = root.find(f"{{{NS_CAC}}}InvoiceDocumentReference/{{{NS_CBC}}}ID")
    assert ref is not None and ref.get("schemeID") == "DIAN"
    assert ref.text == "18760000001"

    # NIT del proveedor tecnológico (obligatorio)
    cond = root.find(f"{{{NS_CAC}}}AdditionalConditions/{{{NS_CBC}}}ID")
    assert cond is not None and cond.get("schemeID") == "ProviderID"
    assert cond.text == "800197268"

    # Medio de pago
    assert root.find(f"{{{NS_CAC}}}PaymentMeans") is not None


def test_xml_totales():
    root = ET.fromstring(_factura().xml)
    total = root.find(f"{{{NS_CAC}}}LegalMonetaryTotal")
    assert total is not None

    def valor(local):
        return total.find(f"{{{NS_CBC}}}{local}").text

    assert valor("LineExtensionAmount") == "100000.00"
    assert valor("TaxExclusiveAmount") == "100000.00"
    assert valor("TaxInclusiveAmount") == "119000.00"
    assert valor("PayableAmount") == "115460.00"


def test_xml_tax_total_por_tarifa():
    root = ET.fromstring(_factura().xml)
    totales = root.findall(f"{{{NS_CAC}}}TaxTotal")
    assert len(totales) == 1
    assert totales[0].find(f"{{{NS_CBC}}}TaxAmount").text == "19000.00"
    sub = totales[0].find(f"{{{NS_CAC}}}TaxSubtotal")
    assert sub is not None


def test_xml_linea_con_extension_dian():
    root = ET.fromstring(_factura().xml)
    ln = root.find(f"{{{NS_CAC}}}InvoiceLine")
    assert ln is not None
    assert ln.find(f"{{{NS_CBC}}}ID").text == "1"
    assert ln.find(f"{{{NS_CBC}}}InvoicedQuantity").text == "1.00"
    assert ln.find(f"{{{NS_CBC}}}LineExtensionAmount").text == "115460.00"

    # Extensión DIAN obligatoria por línea
    detalle = ln.find(
        f"{{{NS_CAC}}}LineExtension/{{{NS_CAC}}}LineExtensionDetail"
    )
    assert detalle is not None, "Falta la extensión DIAN de la línea"
    assert detalle.find(f"{{{NS_DIAN}}}InvoiceTypeCode").text == "01"
    assert detalle.find(f"{{{NS_DIAN}}}ServiceCode").text == "01"

    item = ln.find(f"{{{NS_CAC}}}Item")
    assert item.find(f"{{{NS_CBC}}}Description").text == "Producto"
    precio = ln.find(f"{{{NS_CAC}}}Price/{{{NS_CBC}}}PriceAmount")
    assert precio.text == "100000.00"
    assert precio.get("currencyID") == "COP"