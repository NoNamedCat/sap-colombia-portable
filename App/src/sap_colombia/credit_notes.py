"""Módulo de Notas Crédito y Débito Electrónicas (UBL 2.1 DIAN) para SAP Colombia.

Cumple con la Resolución 000042 y Anexo Técnico 1.9 de la DIAN:
- Tipo de documento 91 (CreditNote)
- Referencia al CUFE y consecutivo de la factura padre (BillingReference)
- Conceptos de corrección DIAN normalizados (1 al 5)
- Cálculo canónico de CUDE (SHA-384, 96 caracteres)
- Generación de código QR fiscal
- Generación de XML UBL 2.1 con validación DIAN
- Reversión contable automática en el PUC y amortización de cartera
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
from sap_colombia.accounting_engine import to_decimal, contabilizar_nota_credito
from sap_colombia.dian_client import DianClient
from sap_colombia.dian_factory import get_dian_client
import sap_colombia.database as db

CONCEPTOS_DIAN_NOTA_CREDITO = {
    "1": "Devolución parcial de los bienes y/o no aceptación parcial del servicio",
    "2": "Anulación de factura electrónica",
    "3": "Rebaja o descuento parcial o total",
    "4": "Ajuste de precio",
    "5": "Otros",
}


def calcular_cude(
    num_nc: str,
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
    """Calcula el CUDE canónico (SHA-384, 96 hexadecimales).

    Usa la misma cadena base que el CUFE de factura: el CUDE solo difiere en
    el número de documento (el de la nota, 8 dígitos) y en los conceptos que
    la notaReversa exige. Antes cada módulo mantenía su propia variante
    recortada (``zfill(10)``, 14 campos) y la DIAN la recalcula sobre la
    cadena oficial.
    """
    return calcular_cufe(
        num_nc, fecha, hora, valor_subtotal, categorias_iva,
        nit_emisor, nit_adquirente, clave_tecnica, tipo_ambiente,
        valor_total, **kwargs,
    )


def cadena_qr_nota_credito(
    num_nc: str,
    fecha: str,
    hora: str,
    nit_emisor: str,
    nit_adquirente: str,
    total_subtotal: Decimal,
    total_iva: Decimal,
    total_nota: Decimal,
    cude: str,
    tipo_ambiente: str = "2",
    tipo_operacion: str = "91",
    clave_tecnica: str = "",
) -> str:
    """Genera la cadena QR de la nota crédito.

    Formato DIAN de 10 campos. Se mantienen los nombres assemblies heredados
    (``NumDoc=``...) solo para referencia; la cadena emitida es la canónica.
    """
    return generar_cadena_qr(
        tipo_ambiente, tipo_operacion, nit_emisor, num_nc,
        fecha, hora, total_nota, clave_tecnica, cude,
    )


def construir_xml_credit_note(
    nota_credito: dict,
    factura_padre: dict,
    empresa: dict,
    cliente: dict,
    lineas: list[dict],
) -> str:
    """Construye el documento XML UBL 2.1 CreditNote con referencias DIAN."""
    NS_CN = "urn:oasis:names:specification:ubl:schema:xsd:CreditNote-2"
    NS_CAC = "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
    NS_CBC = "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"
    NS_DIAN = "http://www.dian.gov.co/FacturaE/DianExtensions/v20"

    ET.register_namespace("", NS_CN)
    ET.register_namespace("cac", NS_CAC)
    ET.register_namespace("cbc", NS_CBC)

    root = ET.Element(f"{{{NS_CN}}}CreditNote")

    # Cabecera UBL 2.1
    cbc_ubl = ET.SubElement(root, f"{{{NS_CBC}}}UBLVersionID")
    cbc_ubl.text = "UBL 2.1"
    cbc_custom = ET.SubElement(root, f"{{{NS_CBC}}}CustomizationID")
    cbc_custom.text = "10"
    cbc_profile = ET.SubElement(root, f"{{{NS_CBC}}}ProfileID")
    cbc_profile.text = "DIAN 2.1: Nota Crédito de Factura Electrónica de Venta"
    
    cbc_id = ET.SubElement(root, f"{{{NS_CBC}}}ID")
    consecutivo = f"{nota_credito.get('prefijo', 'NC')}{nota_credito.get('consecutivo')}"
    cbc_id.text = consecutivo

    cbc_uuid = ET.SubElement(root, f"{{{NS_CBC}}}UUID", schemeName="CUDE-SHA384")
    cbc_uuid.text = nota_credito.get("cude", "")

    cbc_date = ET.SubElement(root, f"{{{NS_CBC}}}IssueDate")
    cbc_date.text = nota_credito.get("fecha", "")

    cbc_time = ET.SubElement(root, f"{{{NS_CBC}}}IssueTime")
    cbc_time.text = nota_credito.get("hora", "12:00:00-05:00")

    cbc_type = ET.SubElement(root, f"{{{NS_CBC}}}CreditNoteTypeCode")
    # UBL CreditNoteTypeCode = "1" (nota crédito). El tipo de operación DIAN
    # "91" va en ext:UBLExtension/ext:ext/cct:InvoiceTypeCode.
    cbc_type.text = "1"

    # DiscrepancyResponse (Concepto de corrección DIAN)
    discrepancy = ET.SubElement(root, f"{{{NS_CAC}}}DiscrepancyResponse")
    disc_ref = ET.SubElement(discrepancy, f"{{{NS_CBC}}}ReferenceID")
    disc_ref.text = f"{factura_padre.get('prefijo', '')}{factura_padre.get('consecutivo', '')}"
    disc_code = ET.SubElement(discrepancy, f"{{{NS_CBC}}}ResponseCode")
    disc_code.text = str(nota_credito.get("motivo_dian", "2"))
    disc_desc = ET.SubElement(discrepancy, f"{{{NS_CBC}}}Description")
    disc_desc.text = nota_credito.get("descripcion_motivo") or CONCEPTOS_DIAN_NOTA_CREDITO.get(str(nota_credito.get("motivo_dian")), "Ajuste")

    # BillingReference (Referencia obligatoria a factura y CUFE padre)
    billing_ref = ET.SubElement(root, f"{{{NS_CAC}}}BillingReference")
    inv_doc_ref = ET.SubElement(billing_ref, f"{{{NS_CAC}}}InvoiceDocumentReference")
    inv_id = ET.SubElement(inv_doc_ref, f"{{{NS_CBC}}}ID")
    inv_id.text = f"{factura_padre.get('prefijo', '')}{factura_padre.get('consecutivo', '')}"
    inv_uuid = ET.SubElement(inv_doc_ref, f"{{{NS_CBC}}}UUID", schemeName="CUFE-SHA384")
    inv_uuid.text = factura_padre.get("cufe", "")
    inv_date = ET.SubElement(inv_doc_ref, f"{{{NS_CBC}}}IssueDate")
    inv_date.text = factura_padre.get("fecha", "")

    # La cadena QR es obligatoria en el documento (cbc:Note) y también en la
    # extensión DIAN.
    cbc_note = ET.SubElement(root, f"{{{NS_CBC}}}Note")
    cbc_note.text = nota_credito.get("qr", "")

    # Bloque de extensión DIAN: tipo de operación 91 y cadena QR
    ext_dian = ET.SubElement(root, f"{{{NS_DIAN}}}ext")
    content_dian = ET.SubElement(ext_dian, f"{{{NS_DIAN}}}Content")
    nota_dian = ET.SubElement(content_dian, f"{{{NS_DIAN}}}CreditNote")
    ET.SubElement(nota_dian, f"{{{NS_DIAN}}}Profile",
                  ProfileID="CoDian10", LineID="1", LineCode="91")
    ET.SubElement(nota_dian, f"{{{NS_DIAN}}}InvoiceTypeCode").text = "91"
    ET.SubElement(nota_dian, f"{{{NS_DIAN}}}LineCode").text = "91"
    ET.SubElement(nota_dian, f"{{{NS_DIAN}}}QRCode").text = nota_credito.get("qr", "")
    ET.SubElement(nota_dian, f"{{{NS_DIAN}}}UUID").text = nota_credito.get("cude", "")
    ET.SubElement(nota_dian, f"{{{NS_DIAN}}}CUDE").text = nota_credito.get("cude", "")

    # Emisor (AccountingSupplierParty)
    supplier = ET.SubElement(root, f"{{{NS_CAC}}}AccountingSupplierParty")
    sup_party = ET.SubElement(supplier, f"{{{NS_CAC}}}Party")
    sup_tax = ET.SubElement(sup_party, f"{{{NS_CAC}}}PartyTaxScheme")
    sup_name = ET.SubElement(sup_tax, f"{{{NS_CBC}}}RegistrationName")
    sup_name.text = empresa.get("razon_social", "")
    sup_id = ET.SubElement(sup_tax, f"{{{NS_CBC}}}CompanyID", schemeAgencyID="195", schemeID=empresa.get("dv", "1"))
    sup_id.text = normalizar_numero(empresa.get("nit", ""))

    # Receptor (AccountingCustomerParty)
    customer = ET.SubElement(root, f"{{{NS_CAC}}}AccountingCustomerParty")
    cust_party = ET.SubElement(customer, f"{{{NS_CAC}}}Party")
    cust_tax = ET.SubElement(cust_party, f"{{{NS_CAC}}}PartyTaxScheme")
    cust_name = ET.SubElement(cust_tax, f"{{{NS_CBC}}}RegistrationName")
    cust_name.text = cliente.get("razon_social", "")
    cust_id = ET.SubElement(cust_tax, f"{{{NS_CBC}}}CompanyID", schemeAgencyID="195", schemeID=cliente.get("dv", "0"))
    cust_id.text = normalizar_numero(cliente.get("nit", ""))

    # Totales Legales (LegalMonetaryTotal)
    monetary = ET.SubElement(root, f"{{{NS_CAC}}}LegalMonetaryTotal")
    line_ext = ET.SubElement(monetary, f"{{{NS_CBC}}}LineExtensionAmount", currencyID="COP")
    line_ext.text = formatear_valor(nota_credito.get("subtotal", "0.00"))
    tax_incl = ET.SubElement(monetary, f"{{{NS_CBC}}}TaxInclusiveAmount", currencyID="COP")
    total_bruto = to_decimal(nota_credito.get("subtotal", "0.00")) + to_decimal(nota_credito.get("total_iva", "0.00"))
    tax_incl.text = formatear_valor(total_bruto)
    payable = ET.SubElement(monetary, f"{{{NS_CBC}}}PayableAmount", currencyID="COP")
    payable.text = formatear_valor(nota_credito.get("total_nota", "0.00"))

    # Líneas de la Nota Crédito
    for idx, linea in enumerate(lineas, start=1):
        cn_line = ET.SubElement(root, f"{{{NS_CAC}}}CreditNoteLine")
        line_id = ET.SubElement(cn_line, f"{{{NS_CBC}}}ID")
        line_id.text = str(idx)
        qty = ET.SubElement(cn_line, f"{{{NS_CBC}}}CreditedQuantity", unitCode="EA")
        qty.text = str(linea.get("cantidad", "1"))
        amt = ET.SubElement(cn_line, f"{{{NS_CBC}}}LineExtensionAmount", currencyID="COP")
        amt.text = formatear_valor(linea.get("subtotal", "0.00"))

        item = ET.SubElement(cn_line, f"{{{NS_CAC}}}Item")
        desc = ET.SubElement(item, f"{{{NS_CBC}}}Description")
        desc.text = linea.get("descripcion", "Item")

        price = ET.SubElement(cn_line, f"{{{NS_CAC}}}Price")
        p_amt = ET.SubElement(price, f"{{{NS_CBC}}}PriceAmount", currencyID="COP")
        p_amt.text = formatear_valor(linea.get("valor_unitario", "0.00"))

    return ET.tostring(root, encoding="utf-8", xml_declaration=True).decode("utf-8")


def emitir_nota_credito(
    factura_id: int,
    motivo_dian: str,
    descripcion_motivo: str = "",
    tipo_anulacion: str = "TOTAL",  # TOTAL o PARCIAL
    lineas_devolucion: list[dict] | None = None,
    dian_client: "DianClient" = None,
) -> dict:
    """Emite una Nota Crédito formalmente vinculada a una factura de venta existente.
    
    Flujo:
    1. Carga factura original y valida existencia y saldos.
    2. Determina montos de subtotal, IVA y retenciones (totales o proporcionales).
    3. Calcula CUDE SHA-384 y genera código QR.
    4. Construye el XML UBL 2.1 CreditNote.
    5. Guarda el registro en base de datos.
    6. Amortiza el saldo en cartera de la factura original.
    7. Genera el asiento contable NIIF en el PUC.
    """
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
            "nit": factura.get("cliente_nit"),
            "dv": "0",
            "razon_social": "Cliente Registrado",
        }

    ahora = datetime.now(timezone.utc)
    fecha_nc = ahora.strftime("%Y-%m-%d")
    hora_nc = ahora.strftime("%H:%M:%S-05:00")

    # Consecutivo dentro del rango autorizado por la DIAN.
    # Antes era len(notas) + 1, que ignora el rango y reutiliza números.
    empresa_para_num = dict(empresa or {})
    empresa_para_num.setdefault("prefijo_resolucion", "NC")
    try:
        cons_nc = numeracion.siguiente_consecutivo(
            empresa_para_num, "notas_credito")
        consecutivo_nc = cons_nc.numero_str
        prefijo_nc = cons_nc.prefijo
    except numeracion.ErrorNumeracion:
        # Sin rango configurado se cae al consecutivo histórico de la empresa.
        notas_existentes = db.get_notas_credito()
        consecutivo_nc = str(len(notas_existentes) + 1)
        prefijo_nc = "NC"

    if tipo_anulacion == "TOTAL" or not lineas_devolucion:
        # Anulación total: toma los montos íntegros de la factura
        subtotal_nc = to_decimal(factura.get("subtotal"))
        iva_19_nc = to_decimal(factura.get("iva_19"))
        iva_5_nc = to_decimal(factura.get("iva_5"))
        total_iva_nc = to_decimal(factura.get("total_iva"))
        retefuente_nc = to_decimal(factura.get("retefuente"))
        reteica_nc = to_decimal(factura.get("reteica"))
        reteiva_nc = to_decimal(factura.get("reteiva"))
        total_nota_nc = to_decimal(factura.get("total_factura"))
        
        lineas_nc = [
            {
                "producto_codigo": l.get("producto_codigo"),
                "descripcion": l.get("descripcion"),
                "cantidad": l.get("cantidad"),
                "valor_unitario": l.get("valor_unitario"),
                "subtotal": l.get("subtotal"),
                "tarifa_iva": l.get("tarifa_iva"),
                "valor_iva": l.get("valor_iva"),
            }
            for l in factura.get("lineas", [])
        ]
    else:
        # Anulación parcial
        subtotal_nc = sum(to_decimal(l.get("subtotal", "0.00")) for l in lineas_devolucion)
        iva_19_nc = sum(to_decimal(l.get("valor_iva", "0.00")) for l in lineas_devolucion if l.get("tarifa_iva") == "IVA_19")
        iva_5_nc = sum(to_decimal(l.get("valor_iva", "0.00")) for l in lineas_devolucion if l.get("tarifa_iva") == "IVA_5")
        total_iva_nc = iva_19_nc + iva_5_nc
        
        # Proporción de retenciones
        subtotal_fac = to_decimal(factura.get("subtotal"))
        ratio = (subtotal_nc / subtotal_fac) if subtotal_fac > 0 else Decimal("0.00")
        retefuente_nc = (to_decimal(factura.get("retefuente")) * ratio).quantize(Decimal("0.01"))
        reteica_nc = (to_decimal(factura.get("reteica")) * ratio).quantize(Decimal("0.01"))
        reteiva_nc = (to_decimal(factura.get("reteiva")) * ratio).quantize(Decimal("0.01"))
        total_nota_nc = subtotal_nc + total_iva_nc - retefuente_nc - reteica_nc - reteiva_nc
        lineas_nc = lineas_devolucion

    categorias_iva = {
        "IVA_0": Decimal("0.00"),
        "IVA_5": iva_5_nc,
        "IVA_19": iva_19_nc,
    }

    # Cálculo del CUDE canónico SHA-384
    cude = calcular_cude(
        num_nc=consecutivo_nc,
        fecha=fecha_nc,
        hora=hora_nc,
        valor_subtotal=subtotal_nc,
        categorias_iva=categorias_iva,
        nit_emisor=empresa.get("nit"),
        nit_adquirente=cliente.get("nit"),
        clave_tecnica=empresa.get("clave_tecnica", "3fa9c0b1d2e34f5a6b7c8d9e0f1a2b3c"),
        tipo_ambiente=empresa.get("tipo_ambiente", "2"),
        valor_total=total_nota_nc,
    )

    qr = cadena_qr_nota_credito(
        num_nc=f"{prefijo_nc}{consecutivo_nc}",
        fecha=fecha_nc,
        hora=hora_nc,
        nit_emisor=empresa.get("nit"),
        nit_adquirente=cliente.get("nit"),
        total_subtotal=subtotal_nc,
        total_iva=total_iva_nc,
        total_nota=total_nota_nc,
        cude=cude,
        tipo_ambiente=empresa.get("tipo_ambiente", "2"),
        tipo_operacion="91",
        clave_tecnica=empresa.get("clave_tecnica", ""),
    )

    datos_nc = {
        "consecutivo": consecutivo_nc,
        "prefijo": prefijo_nc,
        "fecha": fecha_nc,
        "hora": hora_nc,
        "factura_id": factura_id,
        "factura_consecutivo": f"{factura.get('prefijo', '')}{factura.get('consecutivo', '')}",
        "cufe_factura": factura.get("cufe", ""),
        "cliente_nit": factura.get("cliente_nit"),
        "motivo_dian": str(motivo_dian),
        "descripcion_motivo": descripcion_motivo or CONCEPTOS_DIAN_NOTA_CREDITO.get(str(motivo_dian), "Ajuste"),
        "subtotal": str(subtotal_nc),
        "total_iva": str(total_iva_nc),
        "retefuente": str(retefuente_nc),
        "reteica": str(reteica_nc),
        "reteiva": str(reteiva_nc),
        "total_nota": str(total_nota_nc),
        "cude": cude,
        "qr": qr,
        "estado_dian": "",
        "track_id": "",
        "mensaje_dian": "",
    }

    # Generación del XML
    xml_content = construir_xml_credit_note(datos_nc, factura, empresa, cliente, lineas_nc)
    datos_nc["xml_ubl"] = xml_content

    # Transmisión a DIAN
    if dian_client is None:
        dian_client = get_dian_client(str(empresa.get("nit", "")), empresa)
    try:
        resultado = dian_client.transmitir_xml(xml_content)
        datos_nc["estado_dian"] = resultado.estado
        datos_nc["track_id"] = resultado.track_id
        datos_nc["mensaje_dian"] = resultado.status_description
    except Exception as exc:
        datos_nc["estado_dian"] = "ERROR_TRANSMISION"
        datos_nc["track_id"] = ""
        datos_nc["mensaje_dian"] = f"{type(exc).__name__}: {exc}"

    # Guardar en base de datos
    datos_nc["empresa_id"] = empresa["id"]
    nc_id = db.guardar_nota_credito(datos_nc, lineas_nc)
    datos_nc["id"] = nc_id

    # Actualizar cartera de la factura original
    saldo_actual = to_decimal(factura.get("saldo_pendiente", factura.get("total_factura")))
    nuevo_saldo = max(Decimal("0.00"), saldo_actual - total_nota_nc)
    nuevo_estado = "ANULADA" if (tipo_anulacion == "TOTAL" or nuevo_saldo == 0) else "PAGADA_PARCIAL"
    db.actualizar_saldo_factura(factura_id, str(nuevo_saldo), nuevo_estado)

    # Contabilización NIIF automática
    asiento = contabilizar_nota_credito(datos_nc)

    return {
        "nota_credito": datos_nc,
        "asiento_contable": asiento,
        "nuevo_saldo_factura": str(nuevo_saldo),
        "nuevo_estado_cartera": nuevo_estado,
    }
