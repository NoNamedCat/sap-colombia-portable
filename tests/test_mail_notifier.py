"""Pruebas TDD para mail_notifier.py — ZIP + Email."""
import io
import os
import tempfile
import zipfile
from unittest.mock import patch, MagicMock

import pytest


# --- Pruebas: Generar ZIP ---

def test_zip_genera_bytes():
    from sap_colombia import mail_notifier
    buf = mail_notifier.generar_zip_factura(
        factura_id=1,
        consecutivo="SETP990000001",
        cufe="CUFE-DEMO-0001",
        pdf_bytes=b"%PDF-1.4 fake",
    )
    assert isinstance(buf, bytes)
    assert len(buf) > 0


def test_zip_contiene_pdf():
    from sap_colombia import mail_notifier
    buf = mail_notifier.generar_zip_factura(
        factura_id=1,
        consecutivo="SETP990000001",
        cufe="CUFE-DEMO-0001",
        pdf_bytes=b"%PDF-1.4 fake",
    )
    with zipfile.ZipFile(io.BytesIO(buf)) as zf:
        names = zf.namelist()
    assert any(n.endswith(".pdf") for n in names)


def test_zip_contiene_xml_manifest():
    from sap_colombia import mail_notifier
    buf = mail_notifier.generar_zip_factura(
        factura_id=1,
        consecutivo="SETP990000001",
        cufe="CUFE-DEMO-0001",
        pdf_bytes=b"%PDF-1.4 fake",
    )
    with zipfile.ZipFile(io.BytesIO(buf)) as zf:
        names = zf.namelist()
    assert any(n.endswith(".xml") for n in names)


def test_zip_nombre_incluye_consecutivo():
    from sap_colombia import mail_notifier
    buf = mail_notifier.generar_zip_factura(
        factura_id=1,
        consecutivo="SETP990000001",
        cufe="CUFE-DEMO-0001",
        pdf_bytes=b"%PDF-1.4 fake",
    )
    with zipfile.ZipFile(io.BytesIO(buf)) as zf:
        names = zf.namelist()
    assert any("SETP990000001" in n for n in names)


def test_zip_pdf_valido():
    from sap_colombia import mail_notifier
    buf = mail_notifier.generar_zip_factura(
        factura_id=1,
        consecutivo="SETP990000001",
        cufe="CUFE-DEMO-0001",
        pdf_bytes=b"%PDF-1.4 fake",
    )
    with zipfile.ZipFile(io.BytesIO(buf)) as zf:
        pdf_entry = [n for n in zf.namelist() if n.endswith(".pdf")][0]
        pdf_data = zf.read(pdf_entry)
    assert pdf_data.startswith(b"%PDF-")


# --- Pruebas: Enviar email (mock) ---

@patch("sap_colombia.mail_notifier._enviar_smtp")
def test_enviar_factura_por_correo_mock(mock_smtp):
    mock_smtp.return_value = True
    from sap_colombia import mail_notifier
    result = mail_notifier.enviar_factura_por_correo(
        factura_id=1,
        consecutivo="SETP990000001",
        cufe="CUFE-DEMO-0001",
        pdf_bytes=b"%PDF-1.4 fake",
        email_destino="cliente@test.com",
        asunto="Factura SETP990000001",
    )
    assert result["ok"] is True
    mock_smtp.assert_called_once()


@patch("sap_colombia.mail_notifier._enviar_smtp")
def test_enviar_factura_por_correo_devuelve_zip_size(mock_smtp):
    from sap_colombia import mail_notifier
    mock_smtp.return_value = True
    result = mail_notifier.enviar_factura_por_correo(
        factura_id=1,
        consecutivo="SETP990000001",
        cufe="CUFE-DEMO-0001",
        pdf_bytes=b"%PDF-1.4 fake",
        email_destino="cliente@test.com",
        asunto="Factura SETP990000001",
    )
    assert result["ok"] is True
    assert "zip_size" in result
    assert result["zip_size"] > 0


@patch("sap_colombia.mail_notifier._enviar_smtp")
def test_enviar_factura_por_correo_error(mock_smtp):
    from sap_colombia import mail_notifier
    mock_smtp.return_value = False
    result = mail_notifier.enviar_factura_por_correo(
        factura_id=1,
        consecutivo="SETP990000001",
        cufe="CUFE-DEMO-0001",
        pdf_bytes=b"%PDF-1.4 fake",
        email_destino="cliente@test.com",
        asunto="Factura SETP990000001",
    )
    assert result["ok"] is False


# --- Pruebas: _enviar_smtp con mock de smtplib ---

@patch("smtplib.SMTP")
def test_enviar_smtp_llama_smtplib(mock_smtp_cls):
    from sap_colombia import mail_notifier
    mock_server = MagicMock()
    mock_smtp_cls.return_value = mock_server
    mock_server.send_mail.return_value = {}
    result = mail_notifier._enviar_smtp(
        smtp_host="localhost",
        smtp_port=587,
        smtp_user="user",
        smtp_pass="pass",
        email_destino="dest@test.com",
        asunto="Test",
        cuerpo="Hola",
        archivos=[],
    )
    assert result is True
    mock_smtp_cls.assert_called_once()


# --- Pruebas: Integración PDF + ZIP ---

def test_flujo_completo_pdf_zip():
    from sap_colombia import pdf_generator, mail_notifier
    from test_pdf_mail import _factura_sample, EMPRESA, CLIENTE
    pdf_bytes = pdf_generator.generar_pdf_documento(
        tipo="FACTURA",
        documento=_factura_sample(),
        empresa=EMPRESA,
        cliente=CLIENTE,
    )
    zip_buf = mail_notifier.generar_zip_factura(
        factura_id=1,
        consecutivo="SETP990000001",
        cufe="CUFE-DEMO-0001",
        pdf_bytes=pdf_bytes,
    )
    assert len(zip_buf) > 0
    with zipfile.ZipFile(io.BytesIO(zip_buf)) as zf:
        names = zf.namelist()
        assert len(names) >= 2  # PDF + XML
        # PDF en el ZIP debe ser idéntico al original
        pdf_entry = [n for n in names if n.endswith(".pdf")][0]
        assert zf.read(pdf_entry) == pdf_bytes
