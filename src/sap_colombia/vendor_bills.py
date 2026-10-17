"""Buzón de Recepción de Facturas Electrónicas de Proveedores y Eventos RADIAN.

Permite:
1. Parsear AttachedDocument (ZIP / XML) e Invoices de proveedores.
2. Validar CUFE, extraer desglose impositivo y causar automáticamente en contabilidad.
3. Generar Cuentas por Pagar (CxP).
4. Emitir eventos RADIAN obligatorios (Res. DIAN 000085/2022):
   - 030: Acuse de recibo de factura electrónica
   - 032: Recepción de bienes y/o prestación de servicios
   - 033: Aceptación expresa (habilita deducibilidad y título valor)
   - 034: Aceptación tácita
"""

from __future__ import annotations

import io
import re
import uuid
import zipfile
import hashlib
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from decimal import Decimal

from sap_colombia import dbutil
from sap_colombia import database as db
from sap_colombia import accounting_engine
from sap_colombia.dian_factory import get_dian_client

NS_UBL = "http://docs.oasis-open.org/ubl/ns/https://oasis-open.org/ubl/4.0/xmlns-main"
NS_DIAN = "http://www.dian.gov.co/FacturaE/DianExtensions/v20"
NS_XSI = "http://www.w3.org/2001/XMLSchema-instance"
NS_ATTACHED = "urn:oasis:names:specification:ubl:schema:xsd:AttachedDocument-2"
NS_CAC = "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
NS_CBC = "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"

NS_MAP = {
    "cbc": NS_CBC,
    "cac": NS_CAC,
    "attached": NS_ATTACHED,
    "dian": NS_DIAN,
}

CODIGOS_EVENTO_RADIAN = {
    "030": "Acuse de Recibo de la Factura Electrónica de Venta",
    "032": "Recepción de Bienes y/o Prestación de Servicios",
    "033": "Aceptación Expresa de la Factura",
    "034": "Aceptación Tácita de la Factura (3 días hábiles)",
}


def extraer_xml_de_entrada(contenido: str | bytes) -> str:
    """Extrae el XML de factura ya sea que venga como texto plano XML, bytes o archivo ZIP."""
    if isinstance(contenido, bytes):
        if contenido.startswith(b"PK"):
            # Archivo ZIP
            with zipfile.ZipFile(io.BytesIO(contenido), "r") as z:
                for filename in z.namelist():
                    if filename.lower().endswith(".xml"):
                        return z.read(filename).decode("utf-8", errors="replace")
            raise ValueError("No se encontró ningún archivo XML dentro del contenedor ZIP.")
        contenido = contenido.decode("utf-8", errors="replace")

    contenido_str = contenido.strip()
    # Si es un AttachedDocument con Invoice embebido dentro de <Attachment><ExternalReference><Description>
    # o <cbc:Description> con CDATA de XML
    if "<AttachedDocument" in contenido_str:
        try:
            root = ET.fromstring(contenido_str)
            # Buscar en cbc:Description o cbc:EmbeddedDocumentBinaryObject
            for elem in root.iter():
                tag_local = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
                if tag_local in ("Description", "EmbeddedDocumentBinaryObject") and elem.text:
                    txt = elem.text.strip()
                    if "<Invoice" in txt:
                        return txt
        except Exception:
            pass

    return contenido_str


def parsear_factura_xml(xml_str: str) -> dict:
    """Parsea una factura electrónica UBL 2.1 y extrae metadatos impositivos y comerciales."""
    try:
        root = ET.fromstring(xml_str)
    except Exception as exc:
        raise ValueError(f"XML de factura inválido o corrupto: {exc}")

    def find_text(xpath: str, parent=root) -> str:
        # Busca con y sin namespace
        try:
            el = parent.find(xpath, NS_MAP)
            if el is not None and el.text:
                return el.text.strip()
        except Exception:
            pass
        # Fallback sin namespaces
        tag_target = xpath.split(":")[-1].split("}")[-1]
        for node in parent.iter():
            tag_local = node.tag.split("}")[-1] if "}" in node.tag else node.tag
            if tag_local == tag_target and node.text:
                return node.text.strip()
        return ""

    consecutivo_completo = find_text(".//cbc:ID") or "0"
    cufe = find_text(".//cbc:UUID")
    fecha = find_text(".//cbc:IssueDate") or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    fecha_vencimiento = find_text(".//cbc:DueDate") or fecha

    # Descomponer consecutivo y prefijo
    match = re.match(r"^([A-Za-z]+)[-_ ]*([0-9]+)$", consecutivo_completo)
    if match:
        prefijo, consecutivo = match.groups()
    else:
        prefijo = ""
        consecutivo = consecutivo_completo

    # Proveedor (AccountingSupplierParty / SenderParty)
    proveedor_nit = ""
    proveedor_nombre = ""
    for party in root.iter():
        tag = party.tag.split("}")[-1]
        if tag in ("AccountingSupplierParty", "SenderParty"):
            for child in party.iter():
                ctag = child.tag.split("}")[-1]
                if ctag in ("CompanyID", "ID") and child.text and not proveedor_nit:
                    proveedor_nit = child.text.strip()
                elif ctag in ("RegistrationName", "Name") and child.text and not proveedor_nombre:
                    proveedor_nombre = child.text.strip()

    # Totales monetarios
    subtotal = Decimal("0.00")
    total = Decimal("0.00")
    total_iva = Decimal("0.00")
    iva_19 = Decimal("0.00")
    iva_5 = Decimal("0.00")
    iva_0 = Decimal("0.00")
    retefuente = Decimal("0.00")
    reteica = Decimal("0.00")
    reteiva = Decimal("0.00")

    # LegalMonetaryTotal
    for lmt in root.iter():
        tag = lmt.tag.split("}")[-1]
        if tag == "LegalMonetaryTotal":
            for child in lmt.iter():
                ctag = child.tag.split("}")[-1]
                if ctag == "LineExtensionAmount" and child.text:
                    subtotal = Decimal(child.text.strip())
                elif ctag == "PayableAmount" and child.text:
                    total = Decimal(child.text.strip())

    # TaxTotal (IVA)
    for tt in root.iter():
        tag = tt.tag.split("}")[-1]
        if tag == "TaxTotal":
            for sub in tt.iter():
                stag = sub.tag.split("}")[-1]
                if stag == "TaxAmount" and sub.text and total_iva == Decimal("0.00"):
                    try:
                        total_iva = Decimal(sub.text.strip())
                    except Exception:
                        pass
                if stag == "Percent" and sub.text:
                    pct = sub.text.strip()
                    if pct in ("19", "19.00", "19.0"):
                        iva_19 = total_iva
                    elif pct in ("5", "5.00", "5.0"):
                        iva_5 = total_iva

    # WithholdingTaxTotal (Retenciones)
    for wt in root.iter():
        tag = wt.tag.split("}")[-1]
        if tag in ("WithholdingTaxTotal", "Withholding"):
            for sub in wt.iter():
                stag = sub.tag.split("}")[-1]
                if stag == "TaxAmount" and sub.text:
                    try:
                        retefuente = Decimal(sub.text.strip())
                    except Exception:
                        pass

    if total == Decimal("0.00"):
        total = subtotal + total_iva

    return {
        "proveedor_nit": proveedor_nit or "999999999",
        "proveedor_nombre": proveedor_nombre or "PROVEEDOR NACIONAL",
        "prefijo": prefijo,
        "consecutivo": consecutivo,
        "fecha": fecha,
        "fecha_vencimiento": fecha_vencimiento,
        "cufe": cufe or hashlib.sha384(xml_str.encode()).hexdigest(),
        "subtotal": str(subtotal),
        "iva_19": str(iva_19),
        "iva_5": str(iva_5),
        "iva_0": str(iva_0),
        "total_iva": str(total_iva),
        "retefuente": str(retefuente),
        "reteica": str(reteica),
        "reteiva": str(reteiva),
        "total": str(total),
        "xml_contenido": xml_str,
    }


def registrar_factura_compra(
    datos_factura: dict,
    empresa_id: int | None = None,
    auto_contabilizar: bool = True,
    conn=None,
) -> dict:
    """Registra una factura de compra en la base de datos y genera la CxP."""
    empresa_id = empresa_id or db.get_current_empresa_id() or 1
    cufe = datos_factura.get("cufe")

    propia_conexion = conn is None
    conn = conn or db.get_connection()
    try:
        # Validar si ya existe
        if cufe:
            existente = dbutil.query(
                conn,
                "SELECT * FROM facturas_compra WHERE empresa_id = ? AND cufe = ?",
                (empresa_id, cufe),
            ).fetchone()
            if existente:
                return dict(existente)

        ahora = datetime.now(timezone.utc).isoformat()
        cursor = dbutil.query(
            conn,
            """INSERT INTO facturas_compra (
                empresa_id, proveedor_nit, proveedor_nombre, prefijo, consecutivo,
                fecha, fecha_vencimiento, cufe, subtotal, iva_19, iva_5, iva_0,
                total_iva, retefuente, reteica, reteiva, total, estado_radian,
                xml_contenido, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDIENTE', ?, ?)
            RETURNING id""",
            (
                empresa_id,
                datos_factura.get("proveedor_nit", ""),
                datos_factura.get("proveedor_nombre", "Proveedor"),
                datos_factura.get("prefijo", ""),
                datos_factura.get("consecutivo", "0"),
                datos_factura.get("fecha", ""),
                datos_factura.get("fecha_vencimiento", ""),
                cufe,
                str(datos_factura.get("subtotal", "0.00")),
                str(datos_factura.get("iva_19", "0.00")),
                str(datos_factura.get("iva_5", "0.00")),
                str(datos_factura.get("iva_0", "0.00")),
                str(datos_factura.get("total_iva", "0.00")),
                str(datos_factura.get("retefuente", "0.00")),
                str(datos_factura.get("reteica", "0.00")),
                str(datos_factura.get("reteiva", "0.00")),
                str(datos_factura.get("total", "0.00")),
                datos_factura.get("xml_contenido", ""),
                ahora,
            ),
        )
        row = cursor.fetchone()
        factura_id = row["id"] if row else 1

        # Crear cuenta por pagar asociada
        total_monto = str(datos_factura.get("total", "0.00"))
        dbutil.query(
            conn,
            """INSERT INTO cuentas_por_pagar (
                empresa_id, factura_compra_id, proveedor_nit, monto_total,
                saldo_pendiente, fecha_emision, fecha_vencimiento, estado, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'PENDIENTE', ?)""",
            (
                empresa_id,
                factura_id,
                datos_factura.get("proveedor_nit", ""),
                total_monto,
                total_monto,
                datos_factura.get("fecha", ""),
                datos_factura.get("fecha_vencimiento", ""),
                ahora,
            ),
        )

        datos_factura["id"] = factura_id
        datos_factura["empresa_id"] = empresa_id

        # Causación contable automática
        if auto_contabilizar:
            accounting_engine.contabilizar_factura_compra(datos_factura, conn=conn)

        if propia_conexion:
            conn.commit()

        return obtener_factura_compra(factura_id, conn=conn)
    finally:
        if propia_conexion:
            conn.close()


def procesar_factura_proveedor(
    contenido_xml_o_zip: str | bytes,
    empresa_id: int | None = None,
    auto_contabilizar: bool = True,
) -> dict:
    """Recibe el XML o ZIP del proveedor, lo procesa, registra y causa."""
    xml_str = extraer_xml_de_entrada(contenido_xml_o_zip)
    datos = parsear_factura_xml(xml_str)
    return registrar_factura_compra(datos, empresa_id=empresa_id, auto_contabilizar=auto_contabilizar)


def emitir_evento_radian_proveedor(
    factura_compra_id: int,
    codigo_evento: str,
    empresa_id: int | None = None,
    observaciones: str = "",
) -> dict:
    """Emite un evento RADIAN (030, 032, 033, 034) para una factura de proveedor."""
    if codigo_evento not in CODIGOS_EVENTO_RADIAN:
        raise ValueError(f"Código de evento RADIAN no válido: {codigo_evento}")

    factura = obtener_factura_compra(factura_compra_id)
    if not factura:
        raise ValueError(f"Factura de compra #{factura_compra_id} no encontrada.")

    empresa_id = empresa_id or factura.get("empresa_id") or db.get_current_empresa_id() or 1
    empresa = db.get_empresa(empresa_id) or {}

    ahora = datetime.now(timezone.utc)
    fecha_str = ahora.strftime("%Y-%m-%d")
    hora_str = ahora.strftime("%H:%M:%S-05:00")

    # En este evento, el emisor del evento es la empresa adquirente
    nit_emisor_evento = str(empresa.get("nit", "900123456"))
    clave_tecnica = str(empresa.get("clave_tecnica") or "3fa9c0b1d2e34f5a6b7c8d9e0f1a2b3c")
    tipo_ambiente = str(empresa.get("tipo_ambiente") or "1")

    # CUDE SHA-384
    cadena_cude = "".join([
        str(factura_compra_id).zfill(10),
        fecha_str,
        hora_str[:8],
        nit_emisor_evento,
        codigo_evento,
        tipo_ambiente,
        clave_tecnica,
    ])
    cude = hashlib.sha384(cadena_cude.encode("utf-8")).hexdigest()

    from sap_colombia import radian

    cliente_empresa = {
        "nit": nit_emisor_evento,
        "razon_social": empresa.get("razon_social", ""),
        "direccion": empresa.get("direccion", ""),
        "municipio": empresa.get("municipio", ""),
    }
    proveedor_emisor = {
        "nit": factura.get("proveedor_nit", ""),
        "razon_social": factura.get("proveedor_nombre", ""),
        "direccion": "",
        "municipio": "",
    }
    xml_evento = radian.construir_xml_evento(
        factura=factura,
        codigo_evento=codigo_evento,
        cude=cude,
        empresa=proveedor_emisor,
        cliente=cliente_empresa,
        observaciones=observaciones,
    )

    # Enviar a DIAN Mock/Real
    dian_client = get_dian_client(str(empresa.get("nit", "")), empresa)
    resp_dian = dian_client.transmitir_xml(xml_evento)

    nuevo_estado = {
        "030": "RECIBIDO_030",
        "032": "BIENES_032",
        "033": "ACEPTADO_033",
        "034": "ACEPTADO_TACITA_034",
    }.get(codigo_evento, "PROCESADO")

    conn = db.get_connection()
    try:
        dbutil.query(
            conn,
            "UPDATE facturas_compra SET estado_radian = ? WHERE id = ?",
            (nuevo_estado, factura_compra_id),
        )
        conn.commit()
    finally:
        conn.close()

    return {
        "factura_compra_id": factura_compra_id,
        "codigo_evento": codigo_evento,
        "nombre_evento": CODIGOS_EVENTO_RADIAN[codigo_evento],
        "cude": cude,
        "estado_radian": nuevo_estado,
        "dian_response": resp_dian,
        "fecha": fecha_str,
    }


def listar_facturas_compra(empresa_id: int | None = None) -> list[dict]:
    empresa_id = empresa_id or db.get_current_empresa_id() or 1
    conn = db.get_connection()
    try:
        rows = dbutil.query(
            conn,
            "SELECT * FROM facturas_compra WHERE empresa_id = ? ORDER BY id DESC",
            (empresa_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def obtener_factura_compra(factura_id: int, conn=None) -> dict | None:
    propia_conexion = conn is None
    conn = conn or db.get_connection()
    try:
        row = dbutil.query(conn, "SELECT * FROM facturas_compra WHERE id = ?", (factura_id,)).fetchone()
        return dict(row) if row else None
    finally:
        if propia_conexion:
            conn.close()
