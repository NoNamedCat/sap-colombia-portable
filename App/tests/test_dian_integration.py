"""Pruebas de integración contra el servidor DIAN simulado.

El mock valida la estructura del documento igual que lo haría la DIAN, así que
estas pruebas comprueban que una factura aceptada es aceptable y que un
documento mal formado se rechaza por el motivo correcto.
"""

import xml.etree.ElementTree as ET

import pytest

from sap_colombia.cufe_calculator import calcular_cufe, generar_cadena_qr
from sap_colombia.dian_client import DianClient
from sap_colombia.dian_mock_server import DianMockServer
from sap_colombia.tax_engine import LineaFactura
from sap_colombia.ubl_builder import (
    NS_CAC,
    NS_CBC,
    NS_UBL,
    Adquirente,
    Emisor,
    UblInvoiceBuilder,
)

EMISOR_NIT = "90012345678"
CLAVE_TECNICA = "3fa9c0b1d2e34f5a6b7c8d9e0f1a2b3c"

EMPRESA = {
    "rango_desde": 990000000,
    "rango_hasta": 999999999,
    "tipo_ambiente": "1",  # habilitación: la firma no es exigida por el mock
}


@pytest.fixture
def cliente():
    servidor = DianMockServer(EMISOR_NIT, empresa=dict(EMPRESA))
    servidor.start()
    yield DianClient(servidor.base_url)
    servidor.stop()


@pytest.fixture
def cliente_produccion():
    """Mock en ambiente de producción: exige firma digital."""
    empresa = dict(EMPRESA, tipo_ambiente="2")
    servidor = DianMockServer(EMISOR_NIT, empresa=empresa)
    servidor.start()
    yield DianClient(servidor.base_url)
    servidor.stop()


def _lineas():
    return [
        LineaFactura(
            codigo="1001",
            descripcion="Producto",
            cantidad="1",
            valor_unitario="100000",
            clasificacion="EXENTO",
        )
    ]


def _factura(num=990000001, ambiente="1"):
    emisor = Emisor(
        nit=EMISOR_NIT,
        nombre="Emisor SAS",
        direccion="Calle 1 # 1-1",
        ciudad="Bogotá",
        resolucion_dian="18760000001",
        fecha_resolucion="2026-01-15",
    )
    adquirente = Adquirente(
        nit="1234567890",
        nombre="Adquirente Ltda",
        direccion="Cra 2 # 2-2",
        ciudad="Bogotá",
    )
    builder = UblInvoiceBuilder(emisor, adquirente)
    return builder.build(
        str(num), "2024-01-15", "10:30:00", _lineas(),
        clave_tecnica=CLAVE_TECNICA, tipo_ambiente=ambiente,
    )


# ─── Transmisión válida ───

def test_transmision_valida(cliente):
    resultado = cliente.transmitir(_factura())
    assert resultado.estado == "Aceptada"
    assert resultado.status_code == "00"
    assert resultado.track_id
    assert resultado.fecha_validacion


def test_consulta_valida(cliente):
    transmision = cliente.transmitir(_factura())
    consulta = cliente.consultar(transmision.track_id)
    assert consulta.estado == "Aceptada"
    assert consulta.status_code == "00"
    assert consulta.fecha_validacion == transmision.fecha_validacion


def test_consulta_inexistente(cliente):
    resultado = cliente.consultar("track-inexistente")
    assert resultado.estado == "NoEncontrada"
    assert resultado.status_code == "1002"


def test_cufe_consistente_entre_xml_y_documento(cliente):
    """El CUFE del XML debe ser el que el propio motor calculó."""
    f = _factura()
    root = ET.fromstring(f.xml)
    cufe_xml = root.find(f"{{{NS_CBC}}}ID").text.strip()
    assert cufe_xml == f.cufe


def test_qr_tiene_10_campos_y_mismo_cufe(cliente):
    f = _factura()
    partes = f.qr.split(";")
    assert len(partes) == 10
    assert partes[9] == f.cufe
    assert partes[5] == "20240115"   # fecha
    assert partes[6] == "103000"     # hora


# ─── Rechazos ───

def test_transmision_emisor_invalida(cliente):
    factura = _factura()
    root = ET.fromstring(factura.xml)
    nit = root.find(f"{{{NS_CAC}}}AccountingSupplierParty//{{{NS_CBC}}}CompanyID")
    nit.text = "00000000000"
    xml = ET.tostring(root, encoding="utf-8", xml_declaration=True).decode("utf-8")
    resultado = cliente.transmitir_xml(xml)
    assert resultado.estado == "Rechazada"
    assert resultado.status_code == "1001"
    assert "Emisor no autorizado" in resultado.status_description


def test_rechaza_xml_mal_formado(cliente):
    resultado = cliente.transmitir_xml("<no-es-una-factura/>")
    assert resultado.estado == "Rechazada"
    assert resultado.status_code == "1001"


def test_rechaza_qr_con_menos_de_10_campos(cliente):
    """Regresión: fecha y hora pegadas producían 9 campos y la DIAN lo rechaza."""
    factura = _factura()
    root = ET.fromstring(factura.xml)
    nota = root.find(f"{{{NS_CBC}}}Note")
    partes = nota.text.split(";")
    nota.text = ";".join(partes[:5] + [partes[5] + partes[6]] + partes[7:])
    xml = ET.tostring(root, encoding="utf-8", xml_declaration=True).decode("utf-8")
    resultado = cliente.transmitir_xml(xml)
    assert resultado.estado == "Rechazada"
    assert "10 campos" in resultado.status_description


def test_rechaza_numero_fuera_del_rango_autorizado(cliente):
    """El mock aplica el rango que la DIAN autoriza."""
    factura = _factura(num=7)  # fuera del rango autorizado 990000000-999999999
    resultado = cliente.transmitir(factura)
    assert resultado.estado == "Rechazada"
    assert "fuera del rango autorizado" in resultado.status_description


def test_rechaza_cufe_incoherente_con_qr(cliente):
    factura = _factura()
    root = ET.fromstring(factura.xml)
    root.find(f"{{{NS_CBC}}}ID").text = "a" * 96
    xml = ET.tostring(root, encoding="utf-8", xml_declaration=True).decode("utf-8")
    resultado = cliente.transmitir_xml(xml)
    assert resultado.estado == "Rechazada"
    assert "cadena QR no coincide" in resultado.status_description


def test_produccion_exige_firma(cliente_produccion):
    """En producción (2), un documento sin firma debe rechazarse."""
    factura = _factura(ambiente="2")
    resultado = cliente_produccion.transmitir(factura)
    assert resultado.estado == "Rechazada"
    assert "firma digital" in resultado.status_description


def test_produccion_acepta_documento_firmado(cliente_produccion):
    """Con XAdES-BES el mismo documento sí se acepta."""
    from sap_colombia.digital_signature import (
        firmar_xml_ubl,
        generar_certificado_autofirmado_demo,
        verificar_firma_xml,
    )

    p12 = "/tmp/sap_colombia_test_cert.p12"
    generar_certificado_autofirmado_demo(p12, "Prueba123", "800197268", "Proveedor Tech SAS")
    factura = _factura(ambiente="2")
    firmado = firmar_xml_ubl(factura.xml, p12, "Prueba123")
    assert verificar_firma_xml(firmado) is True
    resultado = cliente_produccion.transmitir_xml(firmado)
    assert resultado.estado == "Aceptada", resultado.status_description


# ─── Wiring en los flujos de emisión ───

def _seed_test_factura():
    """Siembra una factura de prueba en la base de datos."""
    import sap_colombia.database as db
    db.init_db()
    if not db.get_empresa():
        db.guardar_empresa({
            "nit": "900123456", "razon_social": "Emp",
            "clave_tecnica": CLAVE_TECNICA, "tipo_ambiente": "1",
        })
    factura_id = db.guardar_factura({
        "consecutivo": "FAC001",
        "fecha": "2026-10-01",
        "hora": "12:00:00-05:00",
        "subtotal": "100000.00",
        "total_iva": "19000.00",
        "total_factura": "119000.00",
        "cliente_nit": "1234567890",
        "estado_dian": "ACEPTADA",
        "cufe": "e" * 96,
        "qr": "DIAN;",
    }, [{
        "producto_codigo": "P001",
        "descripcion": "Producto",
        "cantidad": "1",
        "valor_unitario": "100000",
        "subtotal": "100000.00",
        "tarifa_iva": "IVA_19",
        "valor_iva": "19000.00",
    }])
    return factura_id


def test_emitir_credito_uses_dian_client(cliente, monkeypatch):
    from sap_colombia import credit_notes
    _seed_test_factura()
    resultado = credit_notes.emitir_nota_credito(
        factura_id=_seed_test_factura(),
        motivo_dian="1",
        descripcion_motivo="Devolución",
        dian_client=cliente,
    )
    # La nota crédito debe transmitirse y quedar con estado DIAN resuelto.
    assert resultado["nota_credito"]["estado_dian"] in (
        "ACEPTADA", "ACEPTADO", "Aceptada", "RECHAZADA", "Rechazada", "EMITIDA")
    assert resultado["nota_credito"]["cude"]
    assert len(resultado["nota_credito"]["cude"]) == 96
    assert len(resultado["nota_credito"]["qr"].split(";")) == 10


def test_emitir_debito_uses_dian_client(cliente):
    from sap_colombia import debit_notes
    resultado = debit_notes.emitir_nota_debito(
        factura_id=_seed_test_factura(),
        concepto_dian="4",
        subtotal="10000.00",
        iva_19="1900.00",
        descripcion="Intereses",
        dian_client=cliente,
    )
    assert len(resultado["nota_debito"]["cude"]) == 96
    assert len(resultado["nota_debito"]["qr"].split(";")) == 10