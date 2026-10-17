"""Tests para firma digital XAdES-BES y cliente SOAP 1.2 DIAN."""

import base64
import hashlib
import os
import uuid

import pytest
from lxml import etree

from sap_colombia import digital_signature as ds
from sap_colombia.dian_soap_client import ConfigDian, DianSoapClient, ErrorDian


@pytest.fixture(scope="module")
def cert_p12(tmp_path_factory):
    """Genera un certificado PKCS#12 autofirmado para los tests."""
    ruta = tmp_path_factory.mktemp("certs") / "test_cert.p12"
    ds.generar_certificado_autofirmado_demo(
        ruta, "testpass123", "90012345678", "Saluki Solutions S.A.S."
    )
    return str(ruta)


@pytest.fixture
def xml_ubl_minimal():
    """XML UBL 2.1 mínimo con namespace DIAN."""
    return (
        '<Invoice xmlns="http://docs.oasis-open.org/ubl/ns/'
        'https://oasis-open.org/ubl/4.0/xmlns-main" '
        'xmlns:dian="https://www.dian.gov.co/FacturaE/DianExtensions" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        '<dian:ObligationReferenceID>C123</dian:ObligationReferenceID>'
        '<ProfileID>CoDian10</ProfileID>'
        '<ID>123</ID>'
        '<IssueDate>2025-01-15</IssueDate>'
        '<InvoiceTotalAmount CurrencyID="COP">500000.00</InvoiceTotalAmount>'
        '</Invoice>'
    )


# ---------------------------------------------------------------------------
# Certificado
# ---------------------------------------------------------------------------

class TestCertificado:
    def test_generar_p12(self, cert_p12):
        assert os.path.exists(cert_p12)
        assert os.path.getsize(cert_p12) > 1000

    def test_cargar_certificado(self, cert_p12):
        key, cert = ds.cargar_certificado(cert_p12, "testpass123")
        assert key is not None
        assert cert is not None
        assert cert.public_key().key_size == 2048

    def test_cargar_certificado_password_incorrecta(self, cert_p12):
        with pytest.raises(ds.ErrorFirma):
            ds.cargar_certificado(cert_p12, "password_errada")

    def test_cargar_certificado_no_existe(self):
        with pytest.raises(ds.ErrorFirma):
            ds.cargar_certificado("/ruta/que/no/existe.p12", "pass")


# ---------------------------------------------------------------------------
# Firma
# ---------------------------------------------------------------------------

class TestFirmar:
    def test_firmar_incluye_ubl_extension(self, xml_ubl_minimal, cert_p12):
        firmado = ds.firmar_xml_ubl(xml_ubl_minimal, cert_p12, "testpass123")
        assert "UBLExtension" in firmado
        assert "xmldsig-" in firmado

    def test_firmar_incluye_xades(self, xml_ubl_minimal, cert_p12):
        firmado = ds.firmar_xml_ubl(xml_ubl_minimal, cert_p12, "testpass123")
        assert "QualifyingProperties" in firmado
        assert "SignedProperties" in firmado
        assert "SigningCertificate" in firmado

    def test_firmar_incluye_enveloped_signature(self, xml_ubl_minimal, cert_p12):
        firmado = ds.firmar_xml_ubl(xml_ubl_minimal, cert_p12, "testpass123")
        assert "enveloped-signature" in firmado
        assert "rsa-sha256" in firmado
        assert "xmlenc#sha256" in firmado

    def test_firmar_incluye_certificado_base64(self, xml_ubl_minimal, cert_p12):
        firmado = ds.firmar_xml_ubl(xml_ubl_minimal, cert_p12, "testpass123")
        assert "X509Certificate" in firmado
        root = etree.fromstring(firmado.encode())
        cert_el = root.find(".//{http://www.w3.org/2000/09/xmlsig#}X509Certificate")
        assert cert_el is not None
        cert_bytes = base64.b64decode(cert_el.text)
        assert len(cert_bytes) > 100

    def test_firmar_idempotente_no_re_firma(self, xml_ubl_minimal, cert_p12):
        firmado = ds.firmar_xml_ubl(xml_ubl_minimal, cert_p12, "testpass123")
        with pytest.raises(ds.ErrorFirma):
            ds.firmar_xml_ubl(firmado, cert_p12, "testpass123")

    def test_firmar_dos_veces_mismo_cert(self, xml_ubl_minimal, cert_p12):
        f1 = ds.firmar_xml_ubl(xml_ubl_minimal, cert_p12, "testpass123")
        f2 = ds.firmar_xml_ubl(xml_ubl_minimal, cert_p12, "testpass123")
        assert ds.verificar_firma_xml(f1)
        assert ds.verificar_firma_xml(f2)


# ---------------------------------------------------------------------------
# Verificación
# ---------------------------------------------------------------------------

class TestVerificar:
    def test_verificar_firmado_valido(self, xml_ubl_minimal, cert_p12):
        firmado = ds.firmar_xml_ubl(xml_ubl_minimal, cert_p12, "testpass123")
        assert ds.verificar_firma_xml(firmado) is True

    def test_adulterar_campo_documento(self, xml_ubl_minimal, cert_p12):
        firmado = ds.firmar_xml_ubl(xml_ubl_minimal, cert_p12, "testpass123")
        tampered = firmado.replace("C123", "C999")
        with pytest.raises(ds.ErrorFirma, match="adulter"):
            ds.verificar_firma_xml(tampered)

    def test_adulterar_monto(self, xml_ubl_minimal, cert_p12):
        firmado = ds.firmar_xml_ubl(xml_ubl_minimal, cert_p12, "testpass123")
        tampered = firmado.replace("500000.00", "999999.00")
        with pytest.raises(ds.ErrorFirma, match="adulter"):
            ds.verificar_firma_xml(tampered)

    def test_adulterar_signed_info(self, xml_ubl_minimal, cert_p12):
        firmado = ds.firmar_xml_ubl(xml_ubl_minimal, cert_p12, "testpass123")
        tampered = firmado.replace(
            "http://www.w3.org/2001/04/xmldsig-more#rsa-sha256",
            "http://www.w3.org/2001/04/xmldsig#rsa-sha1",
        )
        with pytest.raises(ds.ErrorFirma):
            ds.verificar_firma_xml(tampered)

    def test_sin_bloque_firma(self, xml_ubl_minimal):
        with pytest.raises(ds.ErrorFirma, match="UBLExtension"):
            ds.verificar_firma_xml(xml_ubl_minimal)

    def test_firmar_con_xml_bytes(self, xml_ubl_minimal, cert_p12):
        firmado = ds.firmar_xml_ubl(xml_ubl_minimal.encode("utf-8"), cert_p12, "testpass123")
        assert isinstance(firmado, str)
        assert ds.verificar_firma_xml(firmado) is True


# ---------------------------------------------------------------------------
# Cliente SOAP 1.2
# ---------------------------------------------------------------------------

class TestSoapClient:
    def test_build_soap_envelope(self):
        cfg = ConfigDian(
            url_transmit="https://diaprod.dian.gov.co/dian-tva-cotd-v13/TransmitDocument",
            user_api="pruebas",
            password_api="pass123",
        )
        client = DianSoapClient(cfg)
        xml = "<Invoice><ID>1</ID></Invoice>"
        envelope = client._build_soap_envelope("pruebas", "pass123", xml)
        assert "<soap:Envelope" in envelope
        assert "wsse:Security" in envelope
        assert "UsernameToken" in envelope
        assert "PasswordDigest" in envelope
        assert "<Invoice>" in envelope

    def test_ws_security_nonce_y_creados(self):
        cfg = ConfigDian(url_transmit="https://test.dian.gov.co", user_api="u", password_api="p")
        client = DianSoapClient(cfg)
        header = client._build_ws_security_header("user", "pass")
        assert "Nonce" in header
        assert "Created" in header
        assert "EncodingType" in header
        # El digest debe ser base64 válido
        nonce_start = header.find("<wsse:Nonce")
        nonce_end = header.find("</wsse:Nonce>")
        nonce_b64 = header[nonce_start + len("<wsse:Nonce EncodingType=\"http://docs.oasis-open.org/wss/2004/08/security/wssecurity/1.0#Base64\">"):nonce_end]
        decoded = base64.b64decode(nonce_b64)
        assert len(decoded) == 16

    def test_parse_response_ok(self):
        cfg = ConfigDian(url_transmit="https://test.dian.gov.co", user_api="u", password_api="p")
        client = DianSoapClient(cfg)
        body = (
            '<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope">'
            '<soap:Body><TransmitResponse>'
            '<Status>ACCEPTED</Status>'
            '<MessageID>MSG001</MessageID>'
            '</TransmitResponse></soap:Body></soap:Envelope>'
        )
        result = client._parse_response(body)
        assert result["TransmitResponse"]["Status"] == "ACCEPTED"
        assert result["TransmitResponse"]["MessageID"] == "MSG001"

    def test_parse_response_fault(self):
        cfg = ConfigDian(url_transmit="https://test.dian.gov.co", user_api="u", password_api="p")
        client = DianSoapClient(cfg)
        body = (
            '<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope">'
            '<soap:Body><soap:Fault>'
            '<faultcode>soap:Server</faultcode>'
            '<faultstring>Documento inválido</faultstring>'
            '</soap:Fault></soap:Body></soap:Envelope>'
        )
        with pytest.raises(Exception, match="fault"):
            client._parse_response(body)

    def test_transmitir_sin_credenciales(self):
        cfg = ConfigDian(url_transmit="https://test.dian.gov.co")
        client = DianSoapClient(cfg)
        with pytest.raises(ErrorDian):
            client.transmitir_documentos("<Invoice/>")
