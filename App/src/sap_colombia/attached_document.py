"""Generador de Contenedor Electrónico (AttachedDocument) UBL 2.1 para la DIAN.

Combina el documento electrónico firmado por el emisor (Invoice, CreditNote, DebitNote)
y el ApplicationResponse oficial firmado por la DIAN en un contenedor estándar UBL 2.1,
conforme al Anexo Técnico de Facturación Electrónica de Colombia.
"""

from __future__ import annotations

import io
import re
import uuid
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

NS_ATTACHED = "urn:oasis:names:specification:ubl:schema:xsd:AttachedDocument-2"
NS_CAC = "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
NS_CBC = "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"


def _limpiar_texto(valor: str | None) -> str:
    return (valor or "").strip()


def extraer_metadatos_xml(xml_content: str) -> dict:
    """Extrae metadatos clave (emisor, adquirente, consecutivo, CUFE, fecha) de un XML UBL."""
    root = ET.fromstring(xml_content)

    def cbc(tag, parent=root):
        el = parent.find(f".//{{{NS_CBC}}}{tag}")
        return el.text.strip() if el is not None and el.text else ""

    def cac(tag, parent=root):
        return parent.find(f".//{{{NS_CAC}}}{tag}")

    consecutivo = cbc("ID")
    cufe = cbc("UUID") or cbc("ID")
    fecha = cbc("IssueDate")
    hora = cbc("IssueTime")

    emisor_nit = ""
    emisor_nombre = ""
    supplier = cac("AccountingSupplierParty")
    if supplier is None:
        supplier = cac("SenderParty")
    if supplier is not None:
        comp_id = supplier.find(f".//{{{NS_CBC}}}CompanyID")
        if comp_id is None:
            comp_id = supplier.find(f".//{{{NS_CBC}}}ID")
        emisor_nit = comp_id.text.strip() if comp_id is not None and comp_id.text else ""
        reg_name = supplier.find(f".//{{{NS_CBC}}}RegistrationName")
        emisor_nombre = reg_name.text.strip() if reg_name is not None and reg_name.text else "Emisor"

    adquirente_nit = ""
    adquirente_nombre = ""
    customer = cac("AccountingCustomerParty")
    if customer is None:
        customer = cac("ReceiverParty")
    if customer is not None:
        cust_id = customer.find(f".//{{{NS_CBC}}}CompanyID")
        if cust_id is None:
            cust_id = customer.find(f".//{{{NS_CBC}}}ID")
        adquirente_nit = cust_id.text.strip() if cust_id is not None and cust_id.text else ""
        cust_name = customer.find(f".//{{{NS_CBC}}}RegistrationName")
        adquirente_nombre = cust_name.text.strip() if cust_name is not None and cust_name.text else "Adquirente"

    return {
        "consecutivo": consecutivo,
        "cufe": cufe,
        "fecha": fecha,
        "hora": hora,
        "emisor_nit": emisor_nit,
        "emisor_nombre": emisor_nombre,
        "adquirente_nit": adquirente_nit,
        "adquirente_nombre": adquirente_nombre,
    }


def construir_attached_document(
    documento_firmado_xml: str,
    application_response_xml: str,
    *,
    consecutivo: str = "",
    fecha: str = "",
    hora: str = "",
    tipo_ambiente: str = "1",
) -> str:
    """Construye el XML UBL 2.1 AttachedDocument asociando la factura y el ApplicationResponse."""
    meta = extraer_metadatos_xml(documento_firmado_xml)

    now = datetime.now(timezone.utc)
    id_doc = consecutivo or f"ATT-{meta['consecutivo'] or uuid.uuid4().hex[:8]}"
    fecha_emision = fecha or meta.get("fecha") or now.strftime("%Y-%m-%d")
    hora_emision = hora or meta.get("hora") or now.strftime("%H:%M:%S-05:00")

    # Armado con ElementTree
    ET.register_namespace("", NS_ATTACHED)
    ET.register_namespace("cac", NS_CAC)
    ET.register_namespace("cbc", NS_CBC)

    root = ET.Element(f"{{{NS_ATTACHED}}}AttachedDocument")

    ET.SubElement(root, f"{{{NS_CBC}}}UBLVersionID").text = "UBL 2.1"
    ET.SubElement(root, f"{{{NS_CBC}}}CustomizationID").text = "Documentos adjuntos"
    ET.SubElement(root, f"{{{NS_CBC}}}ProfileID").text = "DIAN 2.1"
    ET.SubElement(root, f"{{{NS_CBC}}}ProfileExecutionID").text = str(tipo_ambiente)
    ET.SubElement(root, f"{{{NS_CBC}}}ID").text = id_doc
    ET.SubElement(root, f"{{{NS_CBC}}}IssueDate").text = fecha_emision
    ET.SubElement(root, f"{{{NS_CBC}}}IssueTime").text = hora_emision
    ET.SubElement(root, f"{{{NS_CBC}}}DocumentType").text = "Contenedor de Factura Electrónica"

    # SenderParty (Emisor)
    sender = ET.SubElement(root, f"{{{NS_CAC}}}SenderParty")
    s_scheme = ET.SubElement(sender, f"{{{NS_CAC}}}PartyTaxScheme")
    ET.SubElement(s_scheme, f"{{{NS_CBC}}}RegistrationName").text = meta["emisor_nombre"]
    cid_s = ET.SubElement(s_scheme, f"{{{NS_CBC}}}CompanyID")
    cid_s.text = meta["emisor_nit"]
    cid_s.set("schemeAgencyID", "195")
    cid_s.set("schemeID", "4")
    cid_s.set("schemeName", "31")
    s_tax = ET.SubElement(s_scheme, f"{{{NS_CAC}}}TaxScheme")
    ET.SubElement(s_tax, f"{{{NS_CBC}}}ID").text = "01"
    ET.SubElement(s_tax, f"{{{NS_CBC}}}Name").text = "IVA"

    # ReceiverParty (Adquirente)
    receiver = ET.SubElement(root, f"{{{NS_CAC}}}ReceiverParty")
    r_scheme = ET.SubElement(receiver, f"{{{NS_CAC}}}PartyTaxScheme")
    ET.SubElement(r_scheme, f"{{{NS_CBC}}}RegistrationName").text = meta["adquirente_nombre"]
    cid_r = ET.SubElement(r_scheme, f"{{{NS_CBC}}}CompanyID")
    cid_r.text = meta["adquirente_nit"]
    cid_r.set("schemeAgencyID", "195")
    cid_r.set("schemeID", "4")
    cid_r.set("schemeName", "31")
    r_tax = ET.SubElement(r_scheme, f"{{{NS_CAC}}}TaxScheme")
    ET.SubElement(r_tax, f"{{{NS_CBC}}}ID").text = "01"
    ET.SubElement(r_tax, f"{{{NS_CBC}}}Name").text = "IVA"

    # Attachment (Documento firmado principal)
    attachment = ET.SubElement(root, f"{{{NS_CAC}}}Attachment")
    ext_ref = ET.SubElement(attachment, f"{{{NS_CAC}}}ExternalReference")
    ET.SubElement(ext_ref, f"{{{NS_CBC}}}MimeCode").text = "text/xml"
    ET.SubElement(ext_ref, f"{{{NS_CBC}}}EncodingCode").text = "UTF-8"
    desc_el = ET.SubElement(ext_ref, f"{{{NS_CBC}}}Description")
    desc_el.text = documento_firmado_xml.strip()

    # ParentDocumentLineReference (ApplicationResponse oficial de DIAN)
    parent_line = ET.SubElement(root, f"{{{NS_CAC}}}ParentDocumentLineReference")
    ET.SubElement(parent_line, f"{{{NS_CBC}}}LineID").text = "1"
    doc_ref = ET.SubElement(parent_line, f"{{{NS_CAC}}}DocumentReference")
    ET.SubElement(doc_ref, f"{{{NS_CBC}}}ID").text = meta["consecutivo"]
    uuid_el = ET.SubElement(doc_ref, f"{{{NS_CBC}}}UUID")
    uuid_el.text = meta["cufe"]
    uuid_el.set("schemeName", "CUFE-SHA384")
    ET.SubElement(doc_ref, f"{{{NS_CBC}}}IssueDate").text = fecha_emision

    # ResultOfVerification
    res_ver = ET.SubElement(doc_ref, f"{{{NS_CAC}}}ResultOfVerification")
    ET.SubElement(res_ver, f"{{{NS_CBC}}}ValidatorID").text = "DIAN"
    ET.SubElement(res_ver, f"{{{NS_CBC}}}ValidationResultCode").text = "02"
    ET.SubElement(res_ver, f"{{{NS_CBC}}}ValidationDate").text = fecha_emision

    # Adjuntar ApplicationResponse
    app_att = ET.SubElement(doc_ref, f"{{{NS_CAC}}}Attachment")
    app_ext_ref = ET.SubElement(app_att, f"{{{NS_CAC}}}ExternalReference")
    ET.SubElement(app_ext_ref, f"{{{NS_CBC}}}MimeCode").text = "text/xml"
    ET.SubElement(app_ext_ref, f"{{{NS_CBC}}}EncodingCode").text = "UTF-8"
    app_desc = ET.SubElement(app_ext_ref, f"{{{NS_CBC}}}Description")
    app_desc.text = application_response_xml.strip()

    return ET.tostring(root, encoding="utf-8", xml_declaration=True).decode("utf-8")


def empaquetar_contenedor_zip(attached_document_xml: str, nombre_base: str = "AttachedDocument") -> bytes:
    """Comprime el XML AttachedDocument en memoria dentro de un archivo .zip listo para distribución."""
    nombre_clean = re.sub(r"[^a-zA-Z0-9_\-]", "", nombre_base) or "AttachedDocument"
    xml_filename = f"{nombre_clean}.xml"

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(xml_filename, attached_document_xml.encode("utf-8"))
    return buf.getvalue()
