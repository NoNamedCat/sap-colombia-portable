"""Módulo de Documento Soporte para No Obligados a Facturar (DIAN).

Permite que empresas que no están obligadas a facturar emitan un
Documento Soporte con código CUDS (SHA-384) y XML UBL 2.1.

Cuenta automáticamente en el PUC con la estructura de partida doble:
- 513501 Gastos Operacionales: Débito
- 236540 Retefuente por Pagar: Crédito
- 236801 ReteICA por Pagar: Crédito
- 220505 Proveedores Nacionales: Crédito
"""

import hashlib
import xml.etree.ElementTree as ET
from decimal import Decimal
from datetime import datetime, timezone

import sap_colombia.database as db
from sap_colombia.accounting_engine import (
    to_decimal,
    contabilizar_documento_soporte,
)


DEFAULT_EMPRESA = {
    "nit": "90012345678",
    "razon_social": "Empresa por Defecto",
    "direccion": "Dirección por defecto",
    "clave_tecnica": "3fa9c0b1d2e34f5a6b7c8d9e0f1a2b3c",
    "tipo_ambiente": "2",
}


def cuds_base(num_ds: str, fecha: str, hora: str, valor_subtotal: Decimal,
              nit_adquirente: str, doc_proveedor: str, clave_tecnica: str,
              tipo_ambiente: str, valor_total: Decimal) -> str:
    """Construye la cadena canónica para el CUDS."""
    partes = [
        str(num_ds).zfill(10),
        fecha,
        hora,
        f"{valor_subtotal:.2f}",
        "01",
        "0.00",
        "04",
        "0.00",
        "03",
        "0.00",
        f"{valor_total:.2f}",
        nit_adquirente,
        doc_proveedor,
        clave_tecnica,
        tipo_ambiente,
    ]
    return "".join(partes)


def calculate_cuds(num_ds, fecha, hora, valor_subtotal, nit_adquirente,
                   doc_proveedor, clave_tecnica, tipo_ambiente,
                   valor_total) -> str:
    """Calcula el CUDS (SHA-384) del documento soporte."""
    cadena = cuds_base(num_ds, fecha, hora, valor_subtotal, nit_adquirente,
                       doc_proveedor, clave_tecnica, tipo_ambiente,
                       valor_total)
    return hashlib.sha384(cadena.encode("utf-8")).hexdigest()


def build_support_document_xml(datos: dict, lineas: list[dict]) -> str:
    """Construye el XML UBL 2.1 del Documento Soporte."""
    NS_DS = "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
    NS_CAC = "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
    NS_CBC = "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"

    ET.register_namespace("", NS_DS)
    ET.register_namespace("cac", NS_CAC)
    ET.register_namespace("cbc", NS_CBC)

    root = ET.Element(f"{{{NS_DS}}}Invoice")

    def _add_cbc(tag, text=None, **kw):
        el = ET.SubElement(root, f"{{{NS_CBC}}}{tag}", **kw)
        if text is not None:
            el.text = str(text)
        return el

    _add_cbc("UBLVersionID", "UBL 2.1")
    _add_cbc("CustomizationID", "10")
    _add_cbc("ProfileID", "DIAN 2.1: Documento Soporte para No Obligados")
    _add_cbc("ID", datos.get("consecutivo", ""))
    _add_cbc("UUID", datos.get("cuds", ""), schemeName="CUDS-SHA384")
    _add_cbc("IssueDate", datos.get("fecha", ""))
    _add_cbc("IssueTime", datos.get("hora", "12:00:00-05:00"))
    _add_cbc("InvoiceTypeCode", "05")

    cbc_obligation = ET.SubElement(root, f"{{{NS_CAC}}}ObligationReferenceID")
    cbc_obligation.text = datos.get("cuds", "")

    cbc_qr = ET.SubElement(root, f"{{{NS_CAC}}}QRCode")
    cbc_qr.text = datos.get("qr", "")

    supplier = ET.SubElement(root, f"{{{NS_CAC}}}AccountingSupplierParty")
    sup_party = ET.SubElement(supplier, f"{{{NS_CAC}}}Party")
    sup_tax = ET.SubElement(sup_party, f"{{{NS_CAC}}}PartyTaxScheme")
    ET.SubElement(sup_tax, f"{{{NS_CBC}}}RegistrationName").text = datos.get("empresa_nombre", "")
    sup_id = ET.SubElement(sup_tax, f"{{{NS_CBC}}}CompanyID", schemeAgencyID="195",
                           schemeID=datos.get("empresa_dv", "0"))
    sup_id.text = str(datos.get("empresa_nit", ""))

    customer = ET.SubElement(root, f"{{{NS_CAC}}}AccountingCustomerParty")
    cust_party = ET.SubElement(customer, f"{{{NS_CAC}}}Party")
    cust_tax = ET.SubElement(cust_party, f"{{{NS_CAC}}}PartyTaxScheme")
    ET.SubElement(cust_tax, f"{{{NS_CBC}}}RegistrationName").text = datos.get("proveedor_nombre", "")
    cust_id = ET.SubElement(cust_tax, f"{{{NS_CBC}}}CompanyID", schemeAgencyID="195",
                            schemeID=datos.get("proveedor_dv", "0"))
    cust_id.text = str(datos.get("proveedor_nit", ""))

    monetary = ET.SubElement(root, f"{{{NS_CAC}}}LegalMonetaryTotal")
    ET.SubElement(monetary, f"{{{NS_CBC}}}LineExtensionAmount", currencyID="COP").text = \
        f"{datos.get('subtotal', '0.00')}"
    ET.SubElement(monetary, f"{{{NS_CBC}}}TaxInclusiveAmount", currencyID="COP").text = \
        f"{datos.get('subtotal', '0.00')}"
    ET.SubElement(monetary, f"{{{NS_CBC}}}PayableAmount", currencyID="COP").text = \
        f"{datos.get('total_documento', '0.00')}"

    for idx, linea in enumerate(lineas, start=1):
        ds_line = ET.SubElement(root, f"{{{NS_CAC}}}InvoiceLine")
        ET.SubElement(ds_line, f"{{{NS_CBC}}}ID").text = str(idx)
        qty = ET.SubElement(ds_line, f"{{{NS_CBC}}}InvoicedQuantity", unitCode="EA")
        qty.text = str(linea.get("cantidad", "1"))
        amt = ET.SubElement(ds_line, f"{{{NS_CBC}}}LineExtensionAmount", currencyID="COP")
        amt.text = f"{linea.get('subtotal', '0.00')}"
        item = ET.SubElement(ds_line, f"{{{NS_CAC}}}Item")
        ET.SubElement(item, f"{{{NS_CBC}}}Description").text = \
            linea.get("descripcion", "Item")
        price = ET.SubElement(ds_line, f"{{{NS_CAC}}}Price")
        ET.SubElement(price, f"{{{NS_CBC}}}PriceAmount", currencyID="COP").text = \
            f"{linea.get('valor_unitario', '0.00')}"

    return ET.tostring(root, encoding="utf-8", xml_declaration=True).decode("utf-8")


def _obtener_emisor(emisor: dict | None) -> dict:
    if emisor is not None:
        return emisor
    empresa = db.get_empresa()
    if empresa:
        return empresa
    return DEFAULT_EMPRESA


def _obtener_consecutivo(prefijo: str) -> str:
    docs = db.get_documentos_soporte()
    return f"{prefijo}-{len(docs) + 1:04d}"


def crear_documento_soporte(datos_ds: dict, lineas: list[dict],
                            emisor: dict | None = None) -> dict:
    """Crea un Documento Soporte completo (CUDS, QR, XML, DB y asiento)."""
    datos = dict(datos_ds)
    emisor = _obtener_emisor(emisor)

    prefijo = datos.get("prefijo", "DS")
    consecutivo = datos.get("consecutivo") or _obtener_consecutivo(prefijo)
    datos["prefijo"] = prefijo
    datos["consecutivo"] = consecutivo

    fecha = datos.get("fecha") or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    hora = datos.get("hora") or datetime.now(timezone.utc).strftime("%H:%M:%S-05:00")
    datos["fecha"] = fecha
    datos["hora"] = hora

    subtotal = sum(to_decimal(l.get("subtotal", "0.00")) for l in lineas)
    datos["subtotal"] = str(subtotal)

    rf_rate = Decimal(str(datos.get("tarifa_retefuente", "0.035")))
    ri_rate = Decimal(str(datos.get("tarifa_reteica", "0.0069")))
    retefuente = (subtotal * rf_rate).quantize(Decimal("0.01"))
    reteica = (subtotal * ri_rate).quantize(Decimal("0.01"))
    total_documento = subtotal - retefuente - reteica

    datos["retefuente"] = str(retefuente)
    datos["reteica"] = str(reteica)
    datos["total_documento"] = str(total_documento)
    datos["proveedor_nit"] = datos.get("proveedor_nit", "000000000")
    datos["proveedor_nombre"] = datos.get("proveedor_nombre", "Proveedor")

    clave_tecnica = emisor.get("clave_tecnica", DEFAULT_EMPRESA["clave_tecnica"])
    tipo_ambiente = str(emisor.get("tipo_ambiente", DEFAULT_EMPRESA["tipo_ambiente"]))

    cuds = calculate_cuds(
        num_ds=consecutivo,
        fecha=fecha,
        hora=hora,
        valor_subtotal=subtotal,
        nit_adquirente=datos["proveedor_nit"],
        doc_proveedor=datos.get("proveedor_doc", "NIT"),
        clave_tecnica=clave_tecnica,
        tipo_ambiente=tipo_ambiente,
        valor_total=total_documento,
    )
    datos["cuds"] = cuds
    datos["qr"] = cuds[:16]
    datos["empresa_nit"] = emisor.get("nit", "")
    datos["empresa_nombre"] = emisor.get("razon_social", emisor.get("nombre", ""))
    datos["empresa_dv"] = emisor.get("dv", "0")

    xml_ubl = build_support_document_xml(datos, lineas)
    datos["xml_ubl"] = xml_ubl

    datos.setdefault("estado_dian", "EXITOSA")
    datos.setdefault("track_id", f"TRK-DS-{consecutivo}")
    datos.setdefault("mensaje_dian", "Documento Soporte generado correctamente")
    datos["empresa_id"] = emisor.get("id")

    ds_id = db.guardar_documento_soporte(datos, lineas)
    datos["id"] = ds_id

    asiento = contabilizar_documento_soporte(datos)

    return {
        "documento": datos,
        "id": ds_id,
        "cuds": cuds,
        "asiento": asiento,
        "xml_ubl": xml_ubl,
    }
