"""Módulo de Notas Débito Electrónicas (UBL 2.1 DIAN — Tipo 92) para SAP Colombia.

Cumple con la Resolución DIAN 000085 de 2022 y Anexo Técnico 1.9:
- Tipo de documento 92 (DebitNote)
- Referencia al CUFE y consecutivo de la factura padre
- Conceptos DIAN de Nota Débito (1 al 4)
- Cálculo canónico de CUDE (SHA-384)
- Generación de XML UBL 2.1
- Asiento contable de mayor valor a cobrar
"""

import hashlib
import uuid
import xml.etree.ElementTree as ET
from decimal import Decimal
from datetime import datetime, timezone

from sap_colombia.cufe_calculator import (
    calcular_cufe,
    generar_cadena_qr,
    normalizar_numero,
    normalizar_fecha,
    normalizar_hora,
    formatear_valor,
)
from sap_colombia import numeracion
from sap_colombia.accounting_engine import to_decimal
from sap_colombia.dian_client import DianClient
from sap_colombia.dian_factory import get_dian_client
import sap_colombia.database as db

NS_UBL = "http://docs.oasis-open.org/ubl/ns/https://oasis-open.org/ubl/4.0/xmlns-main"
NS_DIAN = "http://www.dian.gov.co/FacturaE/DianExtensions/v20"
NS_XSI = "http://www.w3.org/2001/XMLSchema-instance"
SCHEMA_LOCATION = f"{NS_DIAN} https://www.dian.gov.co/FacturaE/Schemas/CoDian_11.xsd"

CONCEPTOS_DIAN_NOTA_DEBITO = {
    "1": "Intereses",
    "2": "Gastos por cobrar",
    "3": "Cambio de valor",
    "4": "Otros",
}


def calcular_cude(
    num_nd: str,
    fecha: str,
    hora: str,
    valor_subtotal: Decimal,
    categorias_iva: dict,
    nit_emisor: str,
    nit_adquirente: str,
    clave_tecnica: str,
    tipo_ambiente: str,
    valor_total: Decimal,
    **kwargs,
) -> str:
    """Calcula el CUDE (SHA-384, 96 hexadecimales) para la Nota Débito.

    Comparte la cadena canónica con el CUFE de factura y con la nota crédito.
    """
    return calcular_cufe(
        num_nd, fecha, hora, valor_subtotal, categorias_iva,
        nit_emisor, nit_adquirente, clave_tecnica, tipo_ambiente,
        valor_total, **kwargs,
    )


def cadena_qr_nota_debito(
    num_nd: str,
    fecha: str,
    hora: str,
    nit_emisor: str,
    nit_adquirente: str,
    total_subtotal: Decimal,
    total_iva: Decimal,
    total_nota: Decimal,
    cude: str,
    tipo_ambiente: str = "2",
    tipo_operacion: str = "92",
    clave_tecnica: str = "",
) -> str:
    """Genera la cadena QR de la nota débito (10 campos canónicos)."""
    return generar_cadena_qr(
        tipo_ambiente, tipo_operacion, nit_emisor, num_nd,
        fecha, hora, total_nota, clave_tecnica, cude,
    )


def construir_xml_debit_note(
    datos_nd: dict,
    factura: dict,
    empresa: dict,
    cliente: dict,
    lineas_nd: list[dict],
) -> str:
    """Construye el XML UBL 2.1 DebitNote (tipo 92) con estructura DIAN."""
    NS_DN = "urn:oasis:names:specification:ubl:schema:xsd:DebitNote-2"
    NS_CAC = "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
    NS_CBC = "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"

    ET.register_namespace("", NS_DN)
    ET.register_namespace("cac", NS_CAC)
    ET.register_namespace("cbc", NS_CBC)
    ET.register_namespace("dian", NS_DIAN)
    ET.register_namespace("xsi", NS_XSI)

    root = ET.Element(f"{{{NS_DN}}}DebitNote")
    root.set(f"{{{NS_XSI}}}schemaLocation", SCHEMA_LOCATION)

    # Cabecera UBL 2.1
    ET.SubElement(root, f"{{{NS_CBC}}}UBLVersionID").text = "UBL 2.1"
    ET.SubElement(root, f"{{{NS_CBC}}}CustomizationID").text = "10"
    ET.SubElement(root, f"{{{NS_CBC}}}ProfileID").text = "DIAN 2.1: Nota Débito de Factura Electrónica de Venta"

    consecutivo = f"{datos_nd.get('prefijo', 'ND')}{datos_nd.get('consecutivo', '')}"
    ET.SubElement(root, f"{{{NS_CBC}}}ID").text = consecutivo
    ET.SubElement(root, f"{{{NS_CBC}}}UUID", schemeName="CUDE-SHA384").text = datos_nd.get("cude", "")
    ET.SubElement(root, f"{{{NS_CBC}}}IssueDate").text = datos_nd.get("fecha", "")
    ET.SubElement(root, f"{{{NS_CBC}}}IssueTime").text = datos_nd.get("hora", "12:00:00-05:00")
    # UBL DebitNoteTypeCode = "1" (nota débito). El tipo de operación DIAN "92"
    # va en ext:UBLExtension/ext:ext/cct:InvoiceTypeCode.
    ET.SubElement(root, f"{{{NS_CBC}}}DebitNoteTypeCode").text = "1"

    # DiscrepancyResponse (concepto DIAN)
    discrepancy = ET.SubElement(root, f"{{{NS_CAC}}}DiscrepancyResponse")
    ET.SubElement(discrepancy, f"{{{NS_CBC}}}ReferenceID").text = datos_nd.get("factura_consecutivo", "")
    ET.SubElement(discrepancy, f"{{{NS_CBC}}}ResponseCode").text = datos_nd.get("concepto_dian", "4")
    ET.SubElement(discrepancy, f"{{{NS_CBC}}}Description").text = datos_nd.get("descripcion_motivo", "")

    # BillingReference
    billing_ref = ET.SubElement(root, f"{{{NS_CAC}}}BillingReference")
    inv_doc_ref = ET.SubElement(billing_ref, f"{{{NS_CAC}}}InvoiceDocumentReference")
    ET.SubElement(inv_doc_ref, f"{{{NS_CBC}}}ID").text = datos_nd.get("factura_consecutivo", "")
    ET.SubElement(inv_doc_ref, f"{{{NS_CBC}}}UUID", schemeName="CUFE-SHA384").text = factura.get("cufe", "")
    ET.SubElement(inv_doc_ref, f"{{{NS_CBC}}}IssueDate").text = factura.get("fecha", "")

    # Emisor (AccountingSupplierParty)
    supplier = ET.SubElement(root, f"{{{NS_CAC}}}AccountingSupplierParty")
    sup_party = ET.SubElement(supplier, f"{{{NS_CAC}}}Party")
    sup_tax = ET.SubElement(sup_party, f"{{{NS_CAC}}}PartyTaxScheme")
    ET.SubElement(sup_tax, f"{{{NS_CBC}}}RegistrationName").text = empresa.get("razon_social", "")
    ET.SubElement(sup_tax, f"{{{NS_CBC}}}CompanyID", schemeAgencyID="195", schemeID=empresa.get("dv", "1")).text = normalizar_numero(empresa.get("nit", ""))

    # Receptor (AccountingCustomerParty)
    customer = ET.SubElement(root, f"{{{NS_CAC}}}AccountingCustomerParty")
    cust_party = ET.SubElement(customer, f"{{{NS_CAC}}}Party")
    cust_tax = ET.SubElement(cust_party, f"{{{NS_CAC}}}PartyTaxScheme")
    ET.SubElement(cust_tax, f"{{{NS_CBC}}}RegistrationName").text = cliente.get("razon_social", "")
    ET.SubElement(cust_tax, f"{{{NS_CBC}}}CompanyID", schemeAgencyID="195", schemeID=cliente.get("dv", "0")).text = normalizar_numero(cliente.get("nit", ""))

    # Totales legales
    monetary = ET.SubElement(root, f"{{{NS_CAC}}}LegalMonetaryTotal")
    ET.SubElement(monetary, f"{{{NS_CBC}}}LineExtensionAmount", currencyID="COP").text = formatear_valor(datos_nd.get("subtotal", "0.00"))
    total_bruto = to_decimal(datos_nd.get("subtotal", "0.00")) + to_decimal(datos_nd.get("total_iva", "0.00"))
    ET.SubElement(monetary, f"{{{NS_CBC}}}TaxInclusiveAmount", currencyID="COP").text = formatear_valor(total_bruto)
    ET.SubElement(monetary, f"{{{NS_CBC}}}PayableAmount", currencyID="COP").text = formatear_valor(datos_nd.get("total_nota", "0.00"))

    # Líneas de la Nota Débito
    for idx, linea in enumerate(lineas_nd, start=1):
        _linea_debit_note_ubl(root, idx, linea)

    # Cadena QR obligatoria en el documento (cbc:Note)
    ET.SubElement(root, f"{{{NS_CBC}}}Note").text = datos_nd.get("qr", "")

    # Bloque DIAN ext (ext:ext → ext:Content)
    ext_el = ET.SubElement(root, f"{{{NS_DIAN}}}ext")
    content = ET.SubElement(ext_el, f"{{{NS_DIAN}}}Content")
    dian_nota = ET.SubElement(content, f"{{{NS_DIAN}}}DebitNote")
    ET.SubElement(dian_nota, f"{{{NS_DIAN}}}Profile", ProfileID="CoDian10", LineID="1", LineCode="92")
    ET.SubElement(dian_nota, f"{{{NS_DIAN}}}InvoiceTypeCode").text = "92"
    ET.SubElement(dian_nota, f"{{{NS_DIAN}}}LineCode").text = "92"
    ET.SubElement(dian_nota, f"{{{NS_DIAN}}}QRCode").text = datos_nd.get("qr", "")
    ET.SubElement(dian_nota, f"{{{NS_DIAN}}}CUFE").text = datos_nd.get("cude", "")
    ET.SubElement(dian_nota, f"{{{NS_DIAN}}}UUID").text = datos_nd.get("cude", "")

    return ET.tostring(root, encoding="utf-8", xml_declaration=True).decode("utf-8")


def _partido_ubl(parent, persona, nit):
    """Construye un bloque UBL Party."""
    partido = ET.SubElement(parent, f"{{{NS_UBL}}}Party")
    ET.SubElement(partido, f"{{{NS_UBL}}}PartyIdentification", ID=nit)
    nombre = ET.SubElement(partido, f"{{{NS_UBL}}}PartyName")
    ET.SubElement(nombre, f"{{{NS_UBL}}}Name").text = persona.get("razon_social", "")
    legal = ET.SubElement(partido, f"{{{NS_UBL}}}PartyLegalEntity")
    ET.SubElement(legal, f"{{{NS_UBL}}}PartyLegalEntityName").text = persona.get("razon_social", "")
    direccion = ET.SubElement(partido, f"{{{NS_UBL}}}PostalAddress")
    linea_dir = ET.SubElement(direccion, f"{{{NS_UBL}}}AddressLine")
    ET.SubElement(linea_dir, f"{{{NS_UBL}}}Line1").text = persona.get("direccion", "")
    ET.SubElement(direccion, f"{{{NS_UBL}}}CitySubdivisionName").text = persona.get("municipio", "")
    pais = ET.SubElement(direccion, f"{{{NS_UBL}}}Country")
    ET.SubElement(pais, f"{{{NS_UBL}}}Identification").text = "CO"


def _linea_debit_note_ubl(parent, indice, linea: dict):
    """Construye un elemento cac:DebitNoteLine (UBL 2.1 DIAN)."""
    NS_CAC = "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
    NS_CBC = "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"
    ln = ET.SubElement(parent, f"{{{NS_CAC}}}DebitNoteLine")
    ET.SubElement(ln, f"{{{NS_CBC}}}ID").text = str(indice)
    ET.SubElement(ln, f"{{{NS_CBC}}}DebitedQuantity", unitCode="EA").text = str(linea.get("cantidad", "1"))
    ET.SubElement(ln, f"{{{NS_CBC}}}LineExtensionAmount", currencyID="COP").text = formatear_valor(to_decimal(linea.get("subtotal", "0.00")))
    item = ET.SubElement(ln, f"{{{NS_CAC}}}Item")
    ET.SubElement(item, f"{{{NS_CBC}}}Description").text = linea.get("descripcion", "Item")
    precio = ET.SubElement(ln, f"{{{NS_CAC}}}Price")
    ET.SubElement(precio, f"{{{NS_CBC}}}PriceAmount", currencyID="COP").text = formatear_valor(to_decimal(linea.get("valor_unitario", "0.00")))


def _linea_debit_note(parent, indice, linea: dict):
    """Construye un elemento DebitNoteLine (legacy, retained for compatibility)."""
    ln = ET.SubElement(parent, f"{{{NS_UBL}}}DebitNoteLine")
    ET.SubElement(ln, f"{{{NS_UBL}}}ID").text = str(indice)

    cantidad = ET.SubElement(ln, f"{{{NS_UBL}}}InvoicedQuantity", unitCode="X")
    cantidad.text = formatear_valor(to_decimal(linea.get("cantidad", "1")))

    extension = ET.SubElement(ln, f"{{{NS_UBL}}}LineExtensionAmount", currencyID="COP")
    extension.text = formatear_valor(to_decimal(linea.get("subtotal", "0.00")))

    item = ET.SubElement(ln, f"{{{NS_UBL}}}Item")
    ET.SubElement(item, f"{{{NS_UBL}}}Description").text = linea.get("descripcion", "")
    base_cant = ET.SubElement(item, f"{{{NS_UBL}}}BaseQuantity", unitCode="X")
    base_cant.text = formatear_valor(to_decimal(linea.get("cantidad", "1")))

    precio = ET.SubElement(ln, f"{{{NS_UBL}}}Price")
    precio_el = ET.SubElement(precio, f"{{{NS_UBL}}}PriceAmount", currencyID="COP")
    precio_el.text = formatear_valor(to_decimal(linea.get("valor_unitario", "0.00")))


def emitir_nota_debito(
    factura_id: int,
    concepto_dian: str,
    subtotal: Decimal | str,
    iva_19: Decimal | str = "0.00",
    iva_5: Decimal | str = "0.00",
    descripcion: str = "",
    lineas: list[dict] | None = None,
    dian_client: "DianClient" = None,
) -> dict:
    """Emite una Nota Débito formalmente vinculada a una factura de venta.

    Flujo:
    1. Carga factura original y valida existencia.
    2. Calcula CUDE SHA-384 y genera código QR.
    3. Construye el XML UBL 2.1 DebitNote (tipo 92).
    4. Guarda el registro en base de datos.
    5. Genera el asiento contable de mayor valor a cobrar.

    Args:
        factura_id: ID de la factura de venta.
        concepto_dian: Código DIAN del concepto (1-4).
        subtotal: Monto de la nota débito (base).
        iva_19: IVA 19% de la nota.
        iva_5: IVA 5% de la nota.
        descripcion: Descripción del motivo.
        lineas: Listado de líneas de la nota.

    Returns:
        dict con datos de la nota débito, asiento contable y nuevo saldo.
    """
    if str(concepto_dian) not in CONCEPTOS_DIAN_NOTA_DEBITO:
        raise ValueError(
            f"Concepto DIAN de Nota Débito inválido: {concepto_dian}. "
            f"Valores permitidos: {list(CONCEPTOS_DIAN_NOTA_DEBITO.keys())}"
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
    fecha_nd = ahora.strftime("%Y-%m-%d")
    hora_nd = ahora.strftime("%H:%M:%S-05:00")

    # Consecutivo dentro del rango autorizado por la DIAN.
    empresa_para_num = dict(empresa or {})
    empresa_para_num.setdefault("prefijo_resolucion", "ND")
    try:
        cons_nd = numeracion.siguiente_consecutivo(
            empresa_para_num, "notas_debito")
        consecutivo_nd = cons_nd.numero_str
        prefijo_nd = cons_nd.prefijo
    except numeracion.ErrorNumeracion:
        notas_existentes = db.get_notas_debito()
        consecutivo_nd = str(len(notas_existentes) + 1)
        prefijo_nd = "ND"

    subtotal_nd = to_decimal(subtotal)
    iva_19_nd = to_decimal(iva_19)
    iva_5_nd = to_decimal(iva_5)
    total_iva_nd = iva_19_nd + iva_5_nd
    total_nota_nd = subtotal_nd + total_iva_nd

    lineas_nd = lineas if lineas else [{
        "producto_codigo": "",
        "descripcion": descripcion or CONCEPTOS_DIAN_NOTA_DEBITO[str(concepto_dian)],
        "cantidad": 1,
        "valor_unitario": subtotal_nd,
        "subtotal": subtotal_nd,
        "tarifa_iva": "IVA_19" if iva_19_nd > 0 else ("IVA_5" if iva_5_nd > 0 else "IVA_0"),
        "valor_iva": total_iva_nd,
    }]

    categorias_iva = {
        "IVA_0": Decimal("0.00"),
        "IVA_5": iva_5_nd,
        "IVA_19": iva_19_nd,
    }

    cude = calcular_cude(
        num_nd=consecutivo_nd,
        fecha=fecha_nd,
        hora=hora_nd,
        valor_subtotal=subtotal_nd,
        categorias_iva=categorias_iva,
        nit_emisor=empresa.get("nit", ""),
        nit_adquirente=cliente.get("nit", ""),
        clave_tecnica=empresa.get("clave_tecnica", ""),
        tipo_ambiente=empresa.get("tipo_ambiente", "2"),
        valor_total=total_nota_nd,
    )

    qr = cadena_qr_nota_debito(
        num_nd=f"{prefijo_nd}{consecutivo_nd}",
        fecha=fecha_nd,
        hora=hora_nd,
        nit_emisor=empresa.get("nit", ""),
        nit_adquirente=cliente.get("nit", ""),
        total_subtotal=subtotal_nd,
        total_iva=total_iva_nd,
        total_nota=total_nota_nd,
        cude=cude,
        tipo_ambiente=empresa.get("tipo_ambiente", "2"),
        tipo_operacion="92",
        clave_tecnica=empresa.get("clave_tecnica", ""),
    )

    datos_nd = {
        "consecutivo": consecutivo_nd,
        "prefijo": prefijo_nd,
        "fecha": fecha_nd,
        "hora": hora_nd,
        "factura_id": factura_id,
        "factura_consecutivo": f"{factura.get('prefijo', '')}{factura.get('consecutivo', '')}",
        "cufe_factura": factura.get("cufe", ""),
        "cliente_nit": factura.get("cliente_nit"),
        "concepto_dian": str(concepto_dian),
        "descripcion_motivo": descripcion or CONCEPTOS_DIAN_NOTA_DEBITO[str(concepto_dian)],
        "subtotal": str(subtotal_nd),
        "total_iva": str(total_iva_nd),
        "total_nota": str(total_nota_nd),
        "cude": cude,
        "qr": qr,
        "estado_dian": "",
        "track_id": "",
        "mensaje_dian": "",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    xml_content = construir_xml_debit_note(datos_nd, factura, empresa, cliente, lineas_nd)
    datos_nd["xml_ubl"] = xml_content

    # Transmisión a DIAN
    if dian_client is None:
        dian_client = get_dian_client(str(empresa.get("nit", "")), empresa)
    try:
        resultado = dian_client.transmitir_xml(xml_content)
        datos_nd["estado_dian"] = resultado.estado
        datos_nd["track_id"] = resultado.track_id
        datos_nd["mensaje_dian"] = resultado.status_description
    except Exception as exc:
        datos_nd["estado_dian"] = "ERROR_TRANSMISION"
        datos_nd["track_id"] = ""
        datos_nd["mensaje_dian"] = f"{type(exc).__name__}: {exc}"

    datos_nd["empresa_id"] = empresa["id"]
    nd_id = db.guardar_nota_debito(datos_nd, lineas_nd)
    datos_nd["id"] = nd_id

    # Actualizar saldo de la factura (aumenta el valor a cobrar)
    saldo_actual = to_decimal(factura.get("saldo_pendiente", factura.get("total_factura")))
    nuevo_saldo = saldo_actual + total_nota_nd
    db.actualizar_saldo_factura(factura_id, str(nuevo_saldo), "PENDING")

    # Contabilización: 1305 Debito vs 4135/4210 Credito + IVA
    asiento = _contabilizar_nota_debito(datos_nd, factura)

    return {
        "nota_debito": datos_nd,
        "asiento_contable": asiento,
        "nuevo_saldo_factura": str(nuevo_saldo),
    }


def _contabilizar_nota_debito(datos_nd: dict, factura: dict) -> dict:
    """Genera el asiento contable de la Nota Débito.

    Asiento:
    - 130505 Clientes Nacionales: Débito por total de la nota (aumenta a cobrar)
    - 413501 Ventas Operacionales: Crédito por subtotal (si aplica)
    - 421001 Ingresos por Servicios: Crédito por subtotal (si aplica)
    - 240801 IVA 19%: Crédito por IVA 19%
    - 240802 IVA 5%: Crédito por IVA 5%
    """
    comprobante_num = f"CC-ND-{datos_nd['prefijo']}-{datos_nd['consecutivo']}"
    fecha = datos_nd.get("fecha")
    cliente_nit = str(datos_nd.get("cliente_nit", ""))

    subtotal = to_decimal(datos_nd.get("subtotal", "0.00"))
    iva_19 = to_decimal(datos_nd.get("total_iva", "0.00"))

    # Determinar cuenta de crédito según concepto
    concepto = datos_nd.get("concepto_dian", "4")
    if concepto == "1":
        cuenta_credito = "421001"  # Ingresos por Servicios (intereses)
    elif concepto == "2":
        cuenta_credito = "421001"  # Gastos por cobrar
    elif concepto == "3":
        cuenta_credito = "413501"  # Cambio de valor
    else:
        cuenta_credito = "413501"  # Otros

    movimientos = []

    # Débito: Clientes (aumenta a cobrar)
    if to_decimal(datos_nd.get("total_nota", "0.00")) > 0:
        movimientos.append({
            "cuenta_codigo": "130505",
            "tercero_nit": cliente_nit,
            "tercero_nombre": "Cliente",
            "concepto": f"Nota Débito {datos_nd['prefijo']}-{datos_nd['consecutivo']}",
            "debito": datos_nd.get("total_nota", "0.00"),
            "credito": "0.00",
        })

    # Crédito: Ingreso según concepto
    if subtotal > 0:
        movimientos.append({
            "cuenta_codigo": cuenta_credito,
            "tercero_nit": cliente_nit,
            "tercero_nombre": "Cliente",
            "concepto": f"Nota Débito {CONCEPTOS_DIAN_NOTA_DEBITO.get(concepto, 'Otros')}",
            "debito": "0.00",
            "credito": str(subtotal),
        })

    # Crédito: IVA
    if iva_19 > 0:
        movimientos.append({
            "cuenta_codigo": "240801",
            "tercero_nit": cliente_nit,
            "tercero_nombre": "Cliente",
            "concepto": f"IVA 19% Nota Débito {datos_nd['prefijo']}-{datos_nd['consecutivo']}",
            "debito": "0.00",
            "credito": str(iva_19),
        })

    return {
        "numero_comprobante": comprobante_num,
        "fecha": fecha,
        "tipo_documento": "NOTA_DEBITO",
        "total_debito": str(to_decimal(datos_nd.get("total_nota", "0.00"))),
        "total_credito": str(to_decimal(datos_nd.get("total_nota", "0.00"))),
        "movimientos": movimientos,
    }
