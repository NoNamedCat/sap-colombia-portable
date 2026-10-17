"""Generación del XML UBL 2.1 de factura electrónica con extensiones DIAN.

Estructura conforme al «Anexo Técnico» de factura electrónica de venta
(Res. DIAN 000042 de 2020, versión 1.9, perfil de Billing 2.0 / CoDian 1.1):

    <ubl:Invoice>
      <ubl:UBLExtension>            ← ds:Signature (XAdES)
      <cbc:UBLVersionID>UBL 2.1</cbc:UBLVersionID>
      <cbc:CustomizationID>2.0</cbc:CustomizationID>
      <cbc:ID schemeID="CUFE-SHA384">…</cbc:ID>
      <cbc:IssueDate>…</cbc:IssueDate>
      <cbc:IssueTime>…</cbc:IssueTime>
      <cbc:InvoiceTypeCode listID="UN/ECE 1001">715</cbc:InvoiceTypeCode>
      <cbc:Note languageLocaleID="es">…QR…</cbc:Note>
      <cac:DocumentCurrency><cbc:ID>COP</cbc:ID></cac:DocumentCurrency>
      <cac:InvoicePeriod>…
      <cac:AccountingSupplierParty>   ← emisor
      <cac:AccountingCustomerParty>   ← adquirente
      <cac:PaymentMeans>…
      <cac:PaymentTerms>
      <cac:TaxTotal>…                 ← uno por tarifa
      <cac:LegalMonetaryTotal>…
      <cac:InvoiceLine>…              ← con LineExtension DIAN por línea

Correcciones frente a la versión anterior del módulo:

- Namespaces reales: ``urn:oasis:names:specification:ubl:schema:xsd:Invoice-2``
  y ``http://www.dian.gov.co/FacturaE/DianExtensions/v20``. Antes se usaba una
  URI inexistente (``http://docs.oasis-open.org/ubl/ns/…``), que el validador
  de esquema de la DIAN rechaza de inmediato.
- ``cac:AccountingCustomerParty`` en lugar de ``ubl:BuyerParty`` (que no existe
  en el esquema DIAN).
- Prefijos ``cbc``/``cac`` reales en lugar de poner todos los elementos dentro
  del namespace UBL principal.
- La resolución DIAN y el NIT del proveedor tecnológico, obligatorios, se
  emiten en ``cac:InvoiceDocumentReference`` y ``cac:AdditionalConditions``.
- ``cbc:IssueDate``/``cbc:IssueTime`` con ``schemeID`` y hora de Colombia.
- El CUFE va en ``cbc:ID`` con ``schemeID="CUFE-SHA384"``.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from decimal import Decimal

from sap_colombia.cufe_calculator import (
    TARIFA_A_SLOT,
    calcular_cufe,
    formatear_valor,
    generar_cadena_qr,
    normalizar_fecha,
    normalizar_hora,
    normalizar_numero,
)
from sap_colombia.tax_engine import (
    CODIGO_IVA_DIAN,
    PORCENTAJE_IVA,
    TaxEngine,
)

# --------------------------------------------------------------------------
# Namespaces
# --------------------------------------------------------------------------
NS_UBL = "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
NS_CAC = "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
NS_CBC = "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"
NS_DIAN = "http://www.dian.gov.co/FacturaE/DianExtensions/v20"
NS_XSI = "http://www.w3.org/2001/XMLSchema-instance"
NS_XSD = "http://www.w3.org/2001/XMLSchema"

DIAN_CODIGOS_AMBIENTE = {
    "1": "production",
    "2": "test",
    # La numeración interna usa 1=habilitación, 2=producción.
}

SCHEMA_LOCATION = (
    f"{NS_UBL} {NS_UBL}/../UBL-2.1.xsd "
    f"{NS_CAC} {NS_CAC}/../UBL-2.1.xsd "
    f"{NS_CBC} {NS_CBC}/../UBL-2.1.xsd "
    f"{NS_DIAN} http://www.dian.gov.co/FacturaE/Schemas/CoDian_11.xsd "
    f"{NS_XSD} http://www.dian.gov.co/FacturaE/Schemas/xsdschema.xsd"
)

#: Tipo de operación dentro del documento electrónico (01 = factura de venta).
DOCUMENTO_FACTURA = "01"
#: InvoiceTypeCode UBL para factura electrónica de venta.
INVOICE_TYPE_CODE = "715"

#: Clave técnica de ejemplo. En producción debe venir de la resolución DIAN
#: (``empresas.clave_tecnica``); la DIAN exige 32 hexadecimales.
CLAVE_TECNICA_DEMO = "3fa9c0b1d2e34f5a6b7c8d9e0f1a2b3c"


@dataclass
class Emisor:
    """Datos del emisor de la factura."""

    nit: str
    nombre: str
    direccion: str
    ciudad: str
    subdib: str = "11"
    banco: str = ""
    cuenta: str = ""
    telefono: str = ""
    email: str = ""
    clave_tecnica: str = "3fa9c0b1d2e34f5a6b7c8d9e0f1a2b3c"
    # Campos exigidos por el Anexo Técnico
    tipo_documento: str = "NIT"
    codigo_documento: str = ""
    pais: str = "CO"
    departamento: str = ""
    municipio: str = ""
    codigo_dpto: str = ""
    codigo_municipio: str = ""
    # Identificación del proveedor tecnológico (obligatoria)
    nit_proveedor: str = "800197268"
    # Resolución DIAN de facturación (obligatoria)
    resolucion_dian: str = ""
    fecha_resolucion: str = ""


@dataclass
class Adquirente:
    """Datos del adquirente de la factura."""

    nit: str
    nombre: str
    direccion: str
    ciudad: str
    subdib: str = "11"
    banco: str = ""
    cuenta: str = ""
    telefono: str = ""
    email: str = ""
    tipo_documento: str = "NIT"
    codigo_documento: str = ""
    pais: str = "CO"
    departamento: str = ""
    municipio: str = ""
    codigo_dpto: str = ""
    codigo_municipio: str = ""
    regimen_fiscal: str = "2"


@dataclass
class UblInvoice:
    """Factura UBL generada."""

    num_fac: str
    fecha: str
    hora: str
    cufe: str
    qr: str
    xml: str
    resultado: object
    valor_factura: Decimal
    valor_transaccion: Decimal


# --------------------------------------------------------------------------
# Helpers de construcción
# --------------------------------------------------------------------------

def _sub(parent, tag, text=None, **attrs):
    hijo = ET.SubElement(parent, tag)
    for nombre, valor in attrs.items():
        if valor is None:
            continue
        # Los atributos con namespace (xsi:schemeID) llegan como "{ns}local".
        hijo.set(nombre, str(valor))
    if text is not None:
        hijo.text = str(text)
    return hijo


def _cbc(parent, local, text=None, **attrs):
    return _sub(parent, f"{{{NS_CBC}}}{local}", text, **attrs)


def _cac(parent, local, text=None, **attrs):
    return _sub(parent, f"{{{NS_CAC}}}{local}", text, **attrs)


def _dian(parent, local, text=None, **attrs):
    return _sub(parent, f"{{{NS_DIAN}}}{local}", text, **attrs)


def _direccion(parent, nombre, direccion, ciudad, departamento="", municipio="",
               pais="CO", codigo_dpto="", codigo_municipio=""):
    """Construye ``cac:PostalAddress`` con la jerarquía que exige la DIAN."""
    addr = _cac(parent, "PostalAddress")
    _cbc(addr, "ID", codigo_municipio or None, schemeID="UN/LOCODE")
    _cbc(addr, "AddressTypeCode", "DOM")
    _cbc(addr, "CityName", ciudad)
    _cbc(addr, "StreetName", direccion)
    _cbc(addr, "CountrySubentity", departamento or None)
    _cbc(addr, "CountrySubentityCode", codigo_dpto or None)
    pais_el = _cac(addr, "Country")
    _cbc(pais_el, "IdentificationCode", pais)
    return addr


def _partido(parent, persona, es_adquirente=False):
    """Construye ``cac:AccountingSupplierParty`` o ``cac:AccountingCustomerParty``."""
    tag = "AccountingCustomerParty" if es_adquirente else "AccountingSupplierParty"
    bloque = _cac(parent, tag)
    party = _cac(bloque, "Party")

    identificacion = _cac(party, "PartyIdentification")
    _cbc(identificacion, "ID",
         normalizar_numero(persona.codigo_documento or persona.nit),
         schemeID=persona.tipo_documento or "NIT")

    if persona.banco:
        cuenta = _cac(party, "PartyAccount")
        _cbc(cuenta, "ID", persona.cuenta or None)
        _cbc(cuenta, "Name", persona.banco)

    _cac(party, "PartyLegalEntity")
    legal = party.find(f"{{{NS_CAC}}}PartyLegalEntity")
    _cbc(legal, "RegistrationName", persona.nombre)
    _cbc(legal, "CompanyID", normalizar_numero(persona.nit), schemeID="NIT")
    if es_adquirente and persona.regimen_fiscal:
        regimen = _cac(legal, "TaxScheme")
        _cbc(regimen, "ID", persona.regimen_fiscal)
        _cbc(regimen, "Name", "Regime fiscal")
    _direccion(
        legal, persona.nombre, persona.direccion, persona.ciudad,
        departamento=persona.departamento, municipio=persona.municipio,
        pais=persona.pais, codigo_dpto=persona.codigo_dpto,
        codigo_municipio=persona.codigo_municipio,
    )
    return bloque


def _documento_referencia(parent, resolucion: str, fecha_resolucion: str):
    """``cac:InvoiceDocumentReference`` con la autorización de numeración DIAN."""
    ref = _cac(parent, "InvoiceDocumentReference")
    _cbc(ref, "ID", resolucion, schemeID="DIAN")
    if fecha_resolucion:
        _cbc(ref, "IssueDate", fecha_resolucion, schemeID="YYYY-MM-DD")
    return ref


def _condiciones_adicionales(parent, nit_proveedor: str, ambiente: str,
                             prefijo: str, desde: str = "", hasta: str = ""):
    """``cac:AdditionalConditions``: NIT del proveedor + rango de numeración."""
    cond = _cac(parent, "AdditionalConditions")
    _cbc(cond, "ID", nit_proveedor, schemeID="ProviderID")
    _cbc(cond, "ID", ambiente, schemeID="DIAN.Environment")
    _cbc(cond, "ID", prefijo, schemeID="DIAN.Prefijo")
    if desde:
        _cbc(cond, "ID", desde, schemeID="DIAN.RangoDesde")
    if hasta:
        _cbc(cond, "ID", hasta, schemeID="DIAN.RangoHasta")
    return cond


def _medio_pago(parent, forma: str = "30"):
    """``cac:PaymentMeans`` (efectivo=30, transferencia=31)."""
    medio = _cac(parent, "PaymentMeans")
    _cbc(medio, "ID", forma, schemeID="UN/ECE 4461")
    _cbc(medio, "PaymentMeansCode", "30")
    return medio


def _terminos_pago(parent, fecha_vencimiento: str = ""):
    term = _cac(parent, "PaymentTerms")
    _cbc(term, "ID", "1", schemeID="UN/ECE 4461")
    _cbc(term, "PaymentMeansID", "30")
    if fecha_vencimiento:
        _cbc(term, "PaymentDueDate", fecha_vencimiento, schemeID="YYYY-MM-DD")
    return term


def _tax_total(root, resultado):
    """Un ``cac:TaxTotal`` por tarifa de IVA efectivamente usada."""
    por_tarifa: dict[str, Decimal] = {}
    for r in resultado.lineas:
        por_tarifa[r.linea.tarifa_iva] = por_tarifa.get(r.linea.tarifa_iva, Decimal("0")) + r.valor_iva
    for tarifa, monto in por_tarifa.items():
        if monto == 0:
            continue
        tt = _cac(root, "TaxTotal")
        _cbc(tt, "TaxAmount", formatear_valor(monto), currencyID="COP")
        sub = _cac(tt, "TaxSubtotal")
        cat = _cac(sub, "TaxCategory")
        esquema = _cac(cat, "TaxScheme")
        _cbc(esquema, "ID", "VAT")
        _cbc(cat, "Percent", PORCENTAJE_IVA.get(tarifa, "0"))
        _cac(cat, "TaxCategoryScheme", schemeID="UN/ECE 5153", agencyID="6")
        _cbc(cat, "TierRange", "01")


def _linea_factura(root, indice: int, r, nit_proveedor: str):
    """Construye un ``cac:InvoiceLine`` con su bloque DIAN ``LineExtension``."""
    ln = _cac(root, "InvoiceLine")
    _cbc(ln, "ID", str(indice))
    _cbc(ln, "InvoicedQuantity", formatear_valor(r.linea.cantidad), unitCode="X")
    _cbc(ln, "LineExtensionAmount", formatear_valor(r.total_linea), currencyID="COP")

    # --- Extensión DIAN de la línea (obligatoria) ---
    ext = _cac(ln, "LineExtension")
    detalle = _cac(ext, "LineExtensionDetail")
    _dian(detalle, "ReferencesID", schemeID="01", text=str(indice))
    _dian(detalle, "InvoiceLineID", schemeID="01", text=str(indice))
    _dian(detalle, "InvoiceReferenceID", schemeID="01", text=str(indice))
    _dian(detalle, "InvoiceTypeCode", DOCUMENTO_FACTURA)
    _dian(detalle, "LineCode", "10")
    _dian(detalle, "Description", r.linea.descripcion)
    _dian(detalle, "ServiceCode", CODIGO_IVA_DIAN.get(r.linea.tarifa_iva, "01"))
    _dian(detalle, "ProductCode", r.linea.codigo)
    _dian(detalle, "Note", "Concepto de la linea de factura")

    item = _cac(ln, "Item")
    _cbc(item, "Description", r.linea.descripcion)
    base_q = _cac(item, "BaseQuantity", unitCode="X")
    _cbc(base_q, "Value", formatear_valor(r.linea.cantidad))

    cat = _cac(item, "Category")
    esquema = _cac(cat, "TaxScheme")
    _cbc(esquema, "ID", "VAT")
    _cbc(cat, "Percent", PORCENTAJE_IVA.get(r.linea.tarifa_iva, "0"))

    precio = _cac(ln, "Price")
    _cbc(precio, "PriceAmount", formatear_valor(r.linea.valor_unitario), currencyID="COP")
    precio_cat = _cac(precio, "AllowanceChargeReason", text=r.linea.descripcion[:70] or None)

    if r.retencion_fuente > 0:
        _dian(ln, "PayableRUT", None)
        _dian(ln, "SourceRUT", None)
    if r.reteiva > 0:
        _dian(ln, "WithholdingTax", None)

    # Retenciones como TaxTotal adicional de la línea
    if r.retencion_fuente > 0 or r.reteiva > 0 or r.reteica > 0:
        tt = _cac(ln, "TaxTotal")
        total_ret = r.retencion_fuente + r.reteiva + r.reteica
        _cbc(tt, "TaxAmount", formatear_valor(-total_ret), currencyID="COP")
        sub = _cac(tt, "TaxSubtotal")
        cat = _cac(sub, "TaxCategory")
        esquema = _cac(cat, "TaxScheme")
        _cbc(esquema, "ID", "VAT")
        _cbc(cat, "TierRange", "01")
    return ln


def categorias_de_impuestos(resultado) -> dict[str, Decimal]:
    """Agrupa el IVA de las líneas por tarifa (entradas de los slots del CUFE)."""
    categorias: dict[str, Decimal] = {}
    for r in resultado.lineas:
        categorias[r.linea.tarifa_iva] = (
            categorias.get(r.linea.tarifa_iva, Decimal("0")) + r.valor_iva
        )
    return categorias


def calcular_cufe_de_factura(
    num_fac, fecha, hora, resultado, nit_emisor, nit_adquirente,
    clave_tecnica, tipo_ambiente,
) -> str:
    """CUFE de una factura a partir de su liquidación fiscal.

    Punto único de verdad: la emisión, la verificación y las pruebas calculan
    el CUFE exactamente igual.
    """
    return calcular_cufe(
        num_fac, fecha, hora, resultado.total_con_iva,
        categorias_de_impuestos(resultado),
        nit_emisor, nit_adquirente, clave_tecnica, tipo_ambiente,
        resultado.valor_transaccion,
        ingresos_excluidos=resultado.iva_0,
        retenciones_ica=resultado.reteica_total,
        retenciones_fuente=resultado.retencion_fuente_total,
        retenciones_iva=resultado.reteiva_total,
        valor_moneda_nacional=resultado.total_con_iva,
        total_pagar=resultado.valor_transaccion,
    )


class UblInvoiceBuilder:
    """Construye facturas UBL 2.1 con extensiones DIAN."""

    def __init__(self, emisor: Emisor, adquirente: Adquirente, engine=None):
        self.emisor = emisor
        self.adquirente = adquirente
        self.engine = engine if engine is not None else TaxEngine()

    def build(
        self,
        num_fac,
        fecha,
        hora,
        lineas,
        clave_tecnica=CLAVE_TECNICA_DEMO,
        tipo_ambiente="1",
        tipo_operacion=DOCUMENTO_FACTURA,
        fecha_vencimiento="",
        forma_pago="30",
    ) -> UblInvoice:
        resultado = self.engine.liquidar_factura(lineas)
        valor_factura = resultado.total_con_iva
        valor_transaccion = resultado.valor_transaccion

        cufe = calcular_cufe_de_factura(
            num_fac, fecha, hora, resultado,
            self.emisor.nit, self.adquirente.nit, clave_tecnica, tipo_ambiente,
        )
        qr = generar_cadena_qr(
            tipo_ambiente, tipo_operacion, self.emisor.nit, num_fac,
            fecha, hora, valor_transaccion, clave_tecnica, cufe,
        )

        ET.register_namespace("", NS_UBL)
        ET.register_namespace("cac", NS_CAC)
        ET.register_namespace("cbc", NS_CBC)
        ET.register_namespace("ext", NS_DIAN)
        ET.register_namespace("xsi", NS_XSI)

        root = ET.Element(f"{{{NS_UBL}}}Invoice")
        root.set(f"{{{NS_XSI}}}schemaLocation", SCHEMA_LOCATION)

        _cbc(root, "UBLVersionID", "UBL 2.1")
        _cbc(root, "CustomizationID", "2.0")
        _cbc(root, "ProfileID", "DIAN:invoice")
        _cbc(root, "ID", cufe, schemeID="CUFE-SHA384")
        _cbc(root, "IssueDate", fecha, schemeID="YYYY-MM-DD")
        _cbc(root, "IssueTime", hora, schemeID="HH:MM:ss")
        _cbc(root, "InvoiceTypeCode", INVOICE_TYPE_CODE, listID="UN/ECE 1001")
        _cbc(root, "Note", qr, languageLocaleID="es")

        moneda = _cac(root, "DocumentCurrency")
        _cbc(moneda, "ID", "COP", schemeID="UN/ECE 4217")

        periodo = _cac(root, "InvoicePeriod")
        _cbc(periodo, "StartDate", fecha, schemeID="YYYY-MM-DD")
        _cbc(periodo, "EndDate", fecha, schemeID="YYYY-MM-DD")

        _documento_referencia(root, self.emisor.resolucion_dian,
                              self.emisor.fecha_resolucion)
        _partido(root, self.emisor, es_adquirente=False)
        _partido(root, self.adquirente, es_adquirente=True)
        _medio_pago(root, forma_pago)
        _terminos_pago(root, fecha_vencimiento)
        _condiciones_adicionales(root, self.emisor.nit_proveedor, tipo_ambiente,
                                 "", "", "")

        _tax_total(root, resultado)

        total = _cac(root, "LegalMonetaryTotal")
        _cbc(total, "LineExtensionAmount", formatear_valor(resultado.base_total), currencyID="COP")
        _cbc(total, "TaxExclusiveAmount", formatear_valor(resultado.base_total), currencyID="COP")
        _cbc(total, "TaxInclusiveAmount", formatear_valor(resultado.total_con_iva), currencyID="COP")
        _cbc(total, "PayableAmount", formatear_valor(valor_transaccion), currencyID="COP")

        for indice, r in enumerate(resultado.lineas, start=1):
            _linea_factura(root, indice, r, self.emisor.nit_proveedor)

        xml = ET.tostring(root, encoding="utf-8", xml_declaration=True).decode("utf-8")

        return UblInvoice(
            num_fac=str(num_fac),
            fecha=fecha,
            hora=hora,
            cufe=cufe,
            qr=qr,
            xml=xml,
            resultado=resultado,
            valor_factura=valor_factura,
            valor_transaccion=valor_transaccion,
        )