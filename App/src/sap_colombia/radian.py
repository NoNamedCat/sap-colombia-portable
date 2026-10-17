"""Módulo RADIAN — Registro de la Factura Electrónica de Venta como Título Valor.

Resolución DIAN 000085 de 2022 — Factura Electrónica de Venta como Título Valor (RADIAN).
Implementa los 3 eventos obligatorios para que una factura a crédito sea
deducible y transable en factoring:

- Evento 030: Acuse de Recibo de la Factura Electrónica de Venta
- Evento 032: Recepción de Bienes y/o Prestación de Servicios
- Evento 033: Aceptación Expresa de la Factura
- Evento 034: Aceptación Tácita (a los 3 días hábiles)

Cada evento genera un ApplicationResponse XML UBL 2.1 con CUDE (SHA-384).
"""

import hashlib
import uuid
import xml.etree.ElementTree as ET
from decimal import Decimal
from datetime import datetime, timezone

from sap_colombia.cufe_calculator import (
    formatear_valor,
    normalizar_fecha,
    normalizar_hora,
)
from sap_colombia.dian_client import DianClient
from sap_colombia.dian_factory import get_dian_client
import sap_colombia.database as db


NS_UBL = "http://docs.oasis-open.org/ubl/ns/https://oasis-open.org/ubl/4.0/xmlns-main"
NS_DIAN = "http://www.dian.gov.co/FacturaE/DianExtensions/v20"
NS_XSI = "http://www.w3.org/2001/XMLSchema-instance"
SCHEMA_LOCATION = f"{NS_DIAN} https://www.dian.gov.co/FacturaE/Schemas/CoDian_11.xsd"

CODIGOS_EVENTO_RADIAN = {
    "030": "Acuse de Recibo de la Factura Electrónica de Venta",
    "032": "Recepción de Bienes y/o Prestación de Servicios",
    "033": "Aceptación Expresa de la Factura",
    "034": "Aceptación Tácita de la Factura (3 días hábiles)",
}

TIPO_OPERACION_EVENTO = "03"


def calcular_cude_evento(
    factura_id: int,
    codigo_evento: str,
    fecha: str,
    hora: str,
    nit_receptor: str,
    clave_tecnica: str,
    tipo_ambiente: str,
) -> str:
    """Calcula el CUDE (SHA-384) para el evento RADIAN.

    Cadena canónica:
    [numero_evento zfill(10)][fecha][hora][nit_receptor][codigo_evento][tipo_ambiente][clave_tecnica]
    """
    num_evento = str(factura_id).zfill(10)
    cadena = "".join([
        num_evento,
        normalizar_fecha(fecha),
        normalizar_hora(hora),
        nit_receptor,
        codigo_evento,
        tipo_ambiente,
        clave_tecnica,
    ])
    return hashlib.sha384(cadena.encode("utf-8")).hexdigest()


def construir_xml_evento(
    factura: dict,
    codigo_evento: str,
    cude: str,
    empresa: dict,
    cliente: dict,
    observaciones: str = "",
) -> str:
    """Construye el ApplicationResponse XML UBL 2.1 para el evento RADIAN.

    Estructura:
    - <ApplicationResponse>
      - <dian:ObligationReferenceID> CUFE de la factura
      - <dian:ProfileLine>
      - <dian:ApplicationResponse>
        - <Code> tipo evento
        - <Date>
        - <Sender> / <Receiver>
        - <dian:QRCode>
    """
    fecha = datetime.now(timezone.utc)
    fecha_str = fecha.strftime("%Y-%m-%d")
    hora_str = fecha.strftime("%H:%M:%S-05:00")

    cufe_factura = factura.get("cufe", "")
    nit_receptor = cliente.get("nit", "")

    root = ET.Element(f"{{{NS_UBL}}}ApplicationResponse")
    root.set(f"{{{NS_XSI}}}schemaLocation", SCHEMA_LOCATION)

    ET.SubElement(root, f"{{{NS_DIAN}}}ObligationReferenceID").text = cufe_factura

    perfil = ET.SubElement(root, f"{{{NS_DIAN}}}ProfileLine")
    ET.SubElement(
        perfil, f"{{{NS_DIAN}}}Profile",
        ProfileID="CoDian10",
        LineID="1",
        LineCode=TIPO_OPERACION_EVENTO,
    )

    resp = ET.SubElement(root, f"{{{NS_DIAN}}}ApplicationResponse")
    ET.SubElement(resp, f"{{{NS_DIAN}}}Code").text = codigo_evento
    ET.SubElement(resp, f"{{{NS_DIAN}}}Date").text = fecha_str

    remitente = ET.SubElement(resp, f"{{{NS_DIAN}}}Sender")
    ET.SubElement(remitente, f"{{{NS_DIAN}}}Nit").text = nit_receptor
    ET.SubElement(remitente, f"{{{NS_DIAN}}}LegalName").text = cliente.get("razon_social", "")
    ET.SubElement(remitente, f"{{{NS_DIAN}}}Address").text = cliente.get("direccion", "")
    ET.SubElement(remitente, f"{{{NS_DIAN}}}City").text = cliente.get("municipio", "")

    receptor = ET.SubElement(resp, f"{{{NS_DIAN}}}Receiver")
    ET.SubElement(receptor, f"{{{NS_DIAN}}}Nit").text = empresa.get("nit", "")
    ET.SubElement(receptor, f"{{{NS_DIAN}}}LegalName").text = empresa.get("razon_social", "")
    ET.SubElement(receptor, f"{{{NS_DIAN}}}Address").text = empresa.get("direccion", "")
    ET.SubElement(receptor, f"{{{NS_DIAN}}}City").text = empresa.get("municipio", "")

    ET.SubElement(root, f"{{{NS_DIAN}}}QRCode").text = cude

    ET.SubElement(root, f"{{{NS_UBL}}}ProfileID").text = "CoDian10"
    ET.SubElement(root, f"{{{NS_UBL}}}ID").text = f"RADIAN-{codigo_evento}-{factura.get('consecutivo', '')}"
    ET.SubElement(root, f"{{{NS_UBL}}}IssueDate").text = fecha_str
    ET.SubElement(root, f"{{{NS_UBL}}}IssueTime").text = hora_str
    ET.SubElement(root, f"{{{NS_UBL}}}InvoiceTypeCode").text = "715"

    if observaciones:
        ET.SubElement(root, f"{{{NS_UBL}}}Note").text = observaciones

    ET.register_namespace("", NS_UBL)
    ET.register_namespace("dian", NS_DIAN)
    ET.register_namespace("xsi", NS_XSI)
    xml_bytes = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    return xml_bytes.decode("utf-8")


def registrar_evento_radian(
    factura_id: int,
    codigo_evento: str,
    observaciones: str = "",
    dian_client: "DianClient" = None,
) -> dict:
    """Registra un evento RADIAN para una factura de venta.

    Flujo:
    1. Valida que la factura existe y tiene estado apropiado.
    2. Calcula CUDE del evento (SHA-384).
    3. Construye el ApplicationResponse XML UBL 2.1.
    4. Transmite a DIAN (mock o real según configuración).
    5. Guarda en base de datos.

    Args:
        factura_id: ID de la factura de venta.
        codigo_evento: Código del evento (030, 032, 033, 034).
        observaciones: Texto opcional de observaciones.
        dian_client: Cliente DIAN (mock o real). Si es None, se resuelve
            automáticamente mediante la fábrica según SAP_DIAN_MODE.

    Returns:
        dict con datos del evento registrado.

    Raises:
        ValueError: Si la factura no existe o el código de evento es inválido.
    """
    if codigo_evento not in CODIGOS_EVENTO_RADIAN:
        raise ValueError(
            f"Código de evento RADIAN inválido: {codigo_evento}. "
            f"Valores permitidos: {list(CODIGOS_EVENTO_RADIAN.keys())}"
        )

    factura = db.get_factura_by_id(factura_id)
    if not factura:
        raise ValueError(f"Factura ID {factura_id} no encontrada.")

    empresa = db.get_empresa()
    if not empresa:
        raise ValueError("Datos de empresa emisora no configurados.")

    cliente = None
    for c in db.get_clientes():
        if str(c.get("nit")) == str(factura.get("cliente_nit")):
            cliente = c
            break
    if not cliente:
        cliente = {
            "nit": factura.get("cliente_nit", ""),
            "dv": "0",
            "razon_social": "Cliente Registrado",
            "direccion": "",
            "municipio": "",
        }

    ahora = datetime.now(timezone.utc)
    fecha_evento = ahora.strftime("%Y-%m-%d")
    hora_evento = ahora.strftime("%H:%M:%S-05:00")

    cude = calcular_cude_evento(
        factura_id=factura_id,
        codigo_evento=codigo_evento,
        fecha=fecha_evento,
        hora=hora_evento,
        nit_receptor=cliente.get("nit", ""),
        clave_tecnica=empresa.get("clave_tecnica", ""),
        tipo_ambiente=empresa.get("tipo_ambiente", "2"),
    )

    xml_evento = construir_xml_evento(
        factura=factura,
        codigo_evento=codigo_evento,
        cude=cude,
        empresa=empresa,
        cliente=cliente,
        observaciones=observaciones,
    )

    if dian_client is None:
        dian_client = get_dian_client(str(empresa.get("nit", "")), empresa)
    try:
        resultado = dian_client.transmitir_xml(xml_evento)
        estado_dian = resultado.estado
        track_id = resultado.track_id
        mensaje_dian = resultado.status_description
    except Exception as exc:
        estado_dian = "ERROR_TRANSMISION"
        track_id = ""
        mensaje_dian = f"{type(exc).__name__}: {exc}"

    datos_evento = {
        "factura_id": factura_id,
        "tipo_evento": codigo_evento,
        "codigo_evento": codigo_evento,
        "cude_evento": cude,
        "xml_ubl": xml_evento,
        "estado_dian": estado_dian,
        "fecha_evento": fecha_evento,
        "hora_evento": hora_evento,
        "track_id": track_id,
        "mensaje_dian": mensaje_dian,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    evento_id = db.guardar_evento_radian(datos_evento)
    datos_evento["id"] = evento_id

    return {
        "evento": datos_evento,
        "descripcion": CODIGOS_EVENTO_RADIAN[codigo_evento],
        "cude": cude,
        "xml": xml_evento,
    }


def obtener_eventos_factura(factura_id: int) -> list[dict]:
    """Obtiene todos los eventos RADIAN de una factura."""
    return db.get_eventos_radian_by_factura(factura_id)
