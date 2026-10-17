"""Pruebas de paridad 1:1 para el protocolo WCF SOAP 1.2 de la DIAN y el Mock Server.

Verifica:
1. Transmisión síncrona SendBillSync con compresión ZIP en memoria y Base64.
2. Descompresión ZIP en memoria en el Mock Server y validación canónica de 22 campos (CUFE SHA-384).
3. Consulta síncrona GetStatus vía SOAP 1.2 WCF.
4. Set de pruebas asíncrono SendTestSetAsync con TestSetId.
5. Extracción y decodificación del ApplicationResponse oficial emitido por la DIAN.
6. Construcción y empaquetado del AttachedDocument (Contenedor Electrónico UBL 2.1).
"""

import base64
import xml.etree.ElementTree as ET
import pytest

from sap_colombia.attached_document import (
    construir_attached_document,
    empaquetar_contenedor_zip,
    extraer_metadatos_xml,
)
from sap_colombia.cufe_calculator import calcular_cufe
from sap_colombia.dian_client import DianClient, TransmisionResult
from sap_colombia.dian_factory import get_mock_soap_client
from sap_colombia.dian_mock_server import DianMockServer
from sap_colombia.dian_soap_client import ConfigDian, DianSoapClient
from sap_colombia.digital_signature import firmar_xml_ubl, generar_certificado_autofirmado_demo
from sap_colombia.tax_engine import LineaFactura
from sap_colombia.ubl_builder import Adquirente, Emisor, UblInvoiceBuilder

EMISOR_NIT = "90012345678"
CLAVE_TECNICA = "3fa9c0b1d2e34f5a6b7c8d9e0f1a2b3c"

EMPRESA_CONFIG = {
    "rango_desde": 990000000,
    "rango_hasta": 999999999,
    "tipo_ambiente": "1",
    "clave_tecnica": CLAVE_TECNICA,
}


@pytest.fixture
def servidor_mock():
    servidor = DianMockServer(EMISOR_NIT, empresa=dict(EMPRESA_CONFIG))
    servidor.start()
    yield servidor
    servidor.stop()


@pytest.fixture
def cliente_soap(servidor_mock):
    cfg = ConfigDian(
        url_transmit=f"{servidor_mock.base_url}/WcfDianCustomerServices.svc",
        user_api="pruebas_user",
        password_api="pruebas_pass",
        test_set_id="test-set-uuid-001",
    )
    return DianSoapClient(cfg)


def _crear_factura(num=990000001, ambiente="1", clave=CLAVE_TECNICA):
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
    lineas = [
        LineaFactura(
            codigo="1001",
            descripcion="Producto de prueba",
            cantidad="2",
            valor_unitario="50000",
            clasificacion="EXENTO",
        )
    ]
    builder = UblInvoiceBuilder(emisor, adquirente)
    return builder.build(
        str(num), "2026-10-14", "10:30:00", lineas,
        clave_tecnica=clave, tipo_ambiente=ambiente,
    )


# ---------------------------------------------------------------------------
# Pruebas 1:1 SendBillSync y WCF SOAP 1.2
# ---------------------------------------------------------------------------

def test_wcf_send_bill_sync_exitoso(cliente_soap):
    """Envío SOAP WCF con compresión ZIP en memoria, descompresión en Mock y respuesta DianResponse."""
    factura = _crear_factura()
    resultado = cliente_soap.transmitir_xml(factura.xml, consecutivo="990000001")

    assert resultado.estado == "Aceptada"
    assert resultado.status_code == "00"
    assert resultado.track_id
    assert resultado.xml_base64_bytes
    assert resultado.application_response_xml

    # Verificar que el ApplicationResponse entregado en base64 es un XML válido emitido por DIAN
    root_ar = ET.fromstring(resultado.application_response_xml)
    assert "ApplicationResponse" in root_ar.tag
    dian_name = root_ar.find(".//{urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2}RegistrationName")
    assert "DIAN" in (dian_name.text if dian_name is not None else "")


def test_wcf_get_status(cliente_soap):
    """Consulta síncrona GetStatus vía SOAP WCF tras un envío previo."""
    factura = _crear_factura()
    envio = cliente_soap.transmitir_xml(factura.xml)
    assert envio.estado == "Aceptada"

    consulta = cliente_soap.consultar(envio.track_id)
    assert consulta.estado == "Aceptada"
    assert consulta.status_code == "00"
    assert consulta.track_id == envio.track_id


def test_wcf_send_test_set_async(cliente_soap):
    """Envío asíncrono obligatorio de habilitación SendTestSetAsync con TestSetId."""
    factura = _crear_factura()
    resultado = cliente_soap.send_test_set_async(factura.xml, test_set_id="test-set-001")

    assert resultado.estado == "Aceptada"
    assert resultado.track_id  # Contiene el ZipKey asignado


# ---------------------------------------------------------------------------
# Validación Canónica de 22 campos del CUFE (FAB14b)
# ---------------------------------------------------------------------------

def test_mock_recalcula_cufe_canonico_rechaza_falsificado(servidor_mock, cliente_soap):
    """El Mock Server 1:1 debe recalcular los 22 campos canónicos y rechazar si el CUFE fue alterado."""
    factura = _crear_factura()
    root = ET.fromstring(factura.xml)

    # Falsificar el CUFE en cbc:ID y en el QR para burlar la comprobación superficial
    falso_cufe = "f" * 96
    id_el = root.find(".//{urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2}ID")
    id_el.text = falso_cufe

    nota = root.find(".//{urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2}Note")
    partes = nota.text.split(";")
    partes[9] = falso_cufe
    nota.text = ";".join(partes)

    xml_alterado = ET.tostring(root, encoding="utf-8").decode("utf-8")
    resultado = cliente_soap.transmitir_xml(xml_alterado)

    assert resultado.estado == "Rechazada"
    assert "FAB14b" in resultado.status_description or any("FAB14b" in e for e in resultado.errores)


# ---------------------------------------------------------------------------
# Contenedor Electrónico (AttachedDocument UBL 2.1)
# ---------------------------------------------------------------------------

def test_generar_attached_document_y_zip(cliente_soap):
    """Construcción de AttachedDocument uniendo factura + respuesta DIAN y empaquetado ZIP."""
    factura = _crear_factura()
    envio = cliente_soap.transmitir_xml(factura.xml)

    attached_xml = construir_attached_document(
        documento_firmado_xml=factura.xml,
        application_response_xml=envio.application_response_xml,
    )
    assert attached_xml
    assert "AttachedDocument" in attached_xml
    assert "UBL 2.1" in attached_xml
    assert factura.cufe in attached_xml

    # Verificar metadatos
    meta = extraer_metadatos_xml(attached_xml)
    assert meta["consecutivo"]

    # Comprimir en memoria
    zip_bytes = empaquetar_contenedor_zip(attached_xml, "AttachedDocument_990000001")
    assert zip_bytes.startswith(b"PK")  # Cabecera ZIP
