"""Notificador de facturas: empaquetado ZIP y envío por correo electrónico."""
import io
import json
import smtplib
import zipfile
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from datetime import datetime


def generar_zip_factura(
    factura_id: int,
    consecutivo: str,
    cufe: str,
    pdf_bytes: bytes,
) -> bytes:
    """Genera un ZIP con el PDF y un XML de manifiesto. Devuelve bytes del ZIP."""
    buf = io.BytesIO()
    pdf_name = f"{consecutivo}.pdf"
    xml_name = f"{consecutivo}_manifest.xml"
    manifiesto_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<factura id="{factura_id}">\n'
        f"  <consecutivo>{consecutivo}</consecutivo>\n"
        f"  <cufe>{cufe}</cufe>\n"
        f"  <archivo>{pdf_name}</archivo>\n"
        f"  <fecha>{datetime.now().isoformat()}</fecha>\n"
        f'</factura>\n'
    )
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(pdf_name, pdf_bytes)
        zf.writestr(xml_name, manifiesto_xml)
    buf.seek(0)
    return buf.read()


def _enviar_smtp(
    smtp_host: str,
    smtp_port: int,
    smtp_user: str | None,
    smtp_pass: str | None,
    email_destino: str,
    asunto: str,
    cuerpo: str,
    archivos: list[dict] | None = None,
) -> bool:
    """Envía un email con smtplib. Devuelve True si se envió correctamente."""
    try:
        msg = MIMEMultipart()
        msg["From"] = smtp_user or "sap@localhost"
        msg["To"] = email_destino
        msg["Subject"] = asunto
        msg.attach(MIMEText(cuerpo, "html", "utf-8"))
        if archivos:
            for f in archivos:
                part = MIMEApplication(f["data"], Name=f["name"])
                part["Content-Disposition"] = f'attachment; filename="{f["name"]}"'
                msg.attach(part)
        with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
            server.starttls()
            if smtp_user:
                server.login(smtp_user, smtp_pass)
            server.send_message(msg)
        return True
    except Exception:
        return False


def enviar_factura_por_correo(
    factura_id: int,
    consecutivo: str,
    cufe: str,
    pdf_bytes: bytes,
    email_destino: str,
    asunto: str | None = None,
    smtp_host: str = "localhost",
    smtp_port: int = 587,
    smtp_user: str | None = None,
    smtp_pass: str | None = None,
) -> dict:
    """Prepara ZIP y envía la factura por correo. Devuelve dict con estado."""
    zip_bytes = generar_zip_factura(
        factura_id=factura_id,
        consecutivo=consecutivo,
        cufe=cufe,
        pdf_bytes=pdf_bytes,
    )
    zip_name = f"{consecutivo}_package.zip"
    cuerpo = (
        "<p>Estimado cliente,</p>"
        f"<p>Adjunto encontrará su factura <b>{consecutivo}</b> con CUFE <b>{cufe}</b>.</p>"
        "<p>Saludos cordiales,<br/>SAP Colombia</p>"
    )
    ok = _enviar_smtp(
        smtp_host=smtp_host,
        smtp_port=smtp_port,
        smtp_user=smtp_user,
        smtp_pass=smtp_pass,
        email_destino=email_destino,
        asunto=asunto or f"Factura {consecutivo}",
        cuerpo=cuerpo,
        archivos=[{"name": zip_name, "data": zip_bytes}],
    )
    return {
        "ok": ok,
        "zip_size": len(zip_bytes),
        "archivo": zip_name,
        "destino": email_destino,
    }
