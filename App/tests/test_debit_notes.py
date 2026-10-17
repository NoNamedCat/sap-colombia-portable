"""Tests for debit_notes module — CUDE, QR, and UBL XML structure."""
import xml.etree.ElementTree as ET
import unittest.mock as mock
from decimal import Decimal

import pytest

from sap_colombia.debit_notes import (
    calcular_cude,
    cadena_qr_nota_debito,
    construir_xml_debit_note,
)
from sap_colombia.credit_notes import cadena_qr_nota_credito


# ─── Task 1: CUDE canónico ───

CLAVE_TECNICA = "3fa9c0b1d2e34f5a6b7c8d9e0f1a2b3c"


def test_cude_es_96_hex_minusculas():
    """El CUDE debe ser SHA-384: 96 caracteres hexadecimales en minúsculas."""
    cats = {"IVA_19": Decimal("190.00")}
    cude = calcular_cude(
        num_nd="001", fecha="2026-10-12", hora="12:00:00",
        valor_subtotal=Decimal("100000.00"), categorias_iva=cats,
        nit_emisor="900123456", nit_adquirente="800987654",
        clave_tecnica=CLAVE_TECNICA, tipo_ambiente="2",
        valor_total=Decimal("119000.00"),
    )
    assert len(cude) == 96
    assert cude == cude.lower()
    int(cude, 16)


def test_cude_rechaza_clave_tecnica_invalida():
    """Antes una clave arbitraria entraba al hash en silencio (FAB14b)."""
    with pytest.raises(Exception):
        calcular_cude(
            num_nd="001", fecha="2026-10-12", hora="12:00:00",
            valor_subtotal=Decimal("100000.00"), categorias_iva={"IVA_19": Decimal("190.00")},
            nit_emisor="900", nit_adquirente="800",
            clave_tecnica="ABC123", tipo_ambiente="2",
            valor_total=Decimal("119000.00"),
        )


def test_cude_rechaza_ambiente_invalido():
    with pytest.raises(Exception):
        calcular_cude(
            num_nd="001", fecha="2026-10-12", hora="12:00:00",
            valor_subtotal=Decimal("100000.00"), categorias_iva={"IVA_19": Decimal("190.00")},
            nit_emisor="900", nit_adquirente="800",
            clave_tecnica=CLAVE_TECNICA, tipo_ambiente="9",
            valor_total=Decimal("119000.00"),
        )


def test_cufe_usa_rounding_comercial_no_bancario():
    """El CUFE exige ROUND_HALF_UP. Half-even producia un hash distinto."""
    from sap_colombia.cufe_calculator import formatear_valor
    assert formatear_valor("1234.565") == "1234.57"
    assert formatear_valor("1234.575") == "1234.58"
    assert formatear_valor(Decimal("0.005")) == "0.01"


def test_numero_factura_se_normaliza_a_8_digitos():
    from sap_colombia.cufe_calculator import numero_factura_8
    assert numero_factura_8(1) == "00000001"
    assert numero_factura_8("123") == "00000123"
    # Con prefijo: se toma el número, no el prefijo.
    assert numero_factura_8("ND0000000001") == "00000001"


def test_normalizar_hora_rechaza_fecha_pegada():
    """'2026-01-31 00:00:00' no puede convertirse en 14 dígitos."""
    from sap_colombia.cufe_calculator import normalizar_hora
    assert normalizar_hora("14:30:00") == "143000"
    assert normalizar_hora("14:30") == "143000"
    with pytest.raises(Exception):
        normalizar_hora("2026-01-31 00:00:00")


# ─── Task 2: QR DIAN de 10 campos ───

def test_qr_tiene_10_campos_con_fecha_y_hora_separadas():
    """Antes fecha y hora iban pegadas en un campo: 9 en vez de 10."""
    qr = cadena_qr_nota_debito(
        num_nd="1", fecha="2026-10-12", hora="14:30:00",
        nit_emisor="900123456", nit_adquirente="800987654",
        total_subtotal=Decimal("100000.00"), total_iva=Decimal("19000.00"),
        total_nota=Decimal("119000.00"), cude="a" * 96,
        tipo_ambiente="2", tipo_operacion="92",
        clave_tecnica=CLAVE_TECNICA,
    )
    partes = qr.split(";")
    assert len(partes) == 10
    assert partes[0] == "DIAN"
    assert partes[1] == "2"            # ambiente
    assert partes[2] == "92"           # tipo operación nota débito
    assert partes[3] == "900123456"    # NIT emisor
    assert partes[4] == "00000001"     # número de documento, 8 dígitos
    assert partes[5] == "20261012"     # fecha
    assert partes[6] == "143000"       # hora (campo separado)
    assert partes[7] == "119000.00"
    assert partes[8] == CLAVE_TECNICA
    assert partes[9] == "a" * 96


def test_qr_nota_credito_mismo_formato_que_debito():
    kwargs = dict(
        fecha="2026-10-12", hora="12:00:00",
        nit_emisor="900", nit_adquirente="800",
        total_subtotal=Decimal("100.00"), total_iva=Decimal("19.00"),
        total_nota=Decimal("119.00"), cude="b" * 96,
        tipo_ambiente="2", clave_tecnica=CLAVE_TECNICA,
    )
    qr_nd = cadena_qr_nota_debito(num_nd="1", **kwargs)
    qr_nc = cadena_qr_nota_credito(num_nc="1", tipo_operacion="91", **kwargs)
    assert len(qr_nd.split(";")) == len(qr_nc.split(";")) == 10
    # Solo difieren en el tipo de operación
    assert qr_nd.split(";")[2] == "92"
    assert qr_nc.split(";")[2] == "91"


def test_qr_rechaza_cufe_mal_formado():
    with pytest.raises(Exception):
        cadena_qr_nota_debito(
            num_nd="1", fecha="2026-10-12", hora="12:00:00",
            nit_emisor="900", nit_adquirente="800",
            total_subtotal=Decimal("1.00"), total_iva=Decimal("0.00"),
            total_nota=Decimal("1.00"), cude="corto",
            tipo_ambiente="2", clave_tecnica=CLAVE_TECNICA,
        )


# ─── Task 3: UBL DebitNote XML ───

NS_DN = "urn:oasis:names:specification:ubl:schema:xsd:DebitNote-2"
NS_CAC = "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
NS_CBC = "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"
NS_DIAN = "http://www.dian.gov.co/FacturaE/DianExtensions/v20"


def _build_test_xml():
    return construir_xml_debit_note(
        datos_nd={"consecutivo": "001", "prefijo": "ND", "fecha": "2026-10-12",
                  "hora": "12:00:00-05:00", "subtotal": "100000.00",
                  "total_iva": "19000.00", "total_nota": "119000.00",
                  "cude": "c" * 96, "qr": "DIAN;", "descripcion_motivo": "Intereses",
                  "factura_consecutivo": "FAC001"},
        factura={"consecutivo": "FAC001", "cufe": "d" * 96, "fecha": "2026-10-01"},
        empresa={"nit": "900", "razon_social": "Emp", "direccion": "Dir",
                 "municipio": "Cali", "subdivision": "11"},
        cliente={"nit": "800", "razon_social": "Cli", "direccion": "Dir", "municipio": "Cali"},
        lineas_nd=[{"descripcion": "Test", "cantidad": 1, "valor_unitario": "100000.00", "subtotal": "100000.00"}],
    )


def test_xml_has_ubl_debitnote_root():
    """Root must be standard UBL DebitNote-2."""
    root = ET.fromstring(_build_test_xml())
    assert root.tag == f"{{{NS_DN}}}DebitNote"


def test_xml_has_dian_ext_block():
    """Must have DIAN ext block with ext:ext/Content."""
    root = ET.fromstring(_build_test_xml())
    ext = root.find(f"{{{NS_DIAN}}}ext")
    assert ext is not None, "Missing DIAN ext block"


def test_xml_has_billing_reference():
    """Must have cac:BillingReference to parent invoice."""
    root = ET.fromstring(_build_test_xml())
    billing = root.find(f"{{{NS_CAC}}}BillingReference")
    assert billing is not None, "Missing cac:BillingReference"


def test_xml_has_legal_monetary_total():
    """Must have cac:LegalMonetaryTotal with COP amounts."""
    root = ET.fromstring(_build_test_xml())
    lmt = root.find(f"{{{NS_CAC}}}LegalMonetaryTotal")
    assert lmt is not None, "Missing cac:LegalMonetaryTotal"


def test_xml_has_debit_note_lines():
    """Must have cac:DebitNoteLine for each line."""
    root = ET.fromstring(_build_test_xml())
    lines = root.findall(f"{{{NS_CAC}}}DebitNoteLine")
    assert len(lines) == 1, f"Expected 1 DebitNoteLine, got {len(lines)}"
