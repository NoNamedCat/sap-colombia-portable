"""Generador de PDFs formales para ERP SAP Colombia.

Genera PDFs con ReportLab para todos los tipos de documento:
- FACTURA: Factura de Venta formal (DIAN)
- NOTA_CREDITO: Nota Crédito (CUDE)
- NOTA_DEBITO: Nota Débito (CUDE)
- DOCUMENTO_SOPORTE: Documento de Soporte (CUDS)
- RECIBO_CAJA: Recibo de Caja (RC)
- COMPROBANTE_EGRESO: Comprobante de Egreso (CE)
- NOMINA_DESPRENDIBLE: Desprendible de Nómina individual
"""

import io
import io as _io
from datetime import datetime

import qrcode
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    Image,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

TIPOS_DOCUMENTO = (
    "FACTURA",
    "NOTA_CREDITO",
    "NOTA_DEBITO",
    "DOCUMENTO_SOPORTE",
    "RECIBO_CAJA",
    "COMPROBANTE_EGRESO",
    "NOMINA_DESPRENDIBLE",
)

TIPOS_DOCUMENTO = tuple(t.upper() for t in (
    "FACTURA",
    "NOTA_CREDITO",
    "NOTA_DEBITO",
    "DOCUMENTO_SOPORTE",
    "RECIBO_CAJA",
    "COMPROBANTE_EGRESO",
    "NOMINA_DESPRENDIBLE",
))


_ESTILOS = None


def _estilos():
    global _ESTILOS
    if _ESTILOS is None:
        styles = getSampleStyleSheet()
        styles.add(ParagraphStyle(
            name="TítuloDoc",
            parent=styles["Title"],
            fontSize=14,
            leading=18,
            spaceAfter=8,
            alignment=1,
        ))
        styles.add(ParagraphStyle(
            name="CajónRes",
            parent=styles["Normal"],
            fontSize=8,
            leading=11,
            spaceAfter=4,
        ))
        styles.add(ParagraphStyle(
            name="Pie",
            parent=styles["Normal"],
            fontSize=7,
            leading=9,
            textColor=colors.grey,
            alignment=1,
        ))
        _ESTILOS = styles
    return _ESTILOS


def _qr_to_image_bytes(data: str) -> bytes:
    qr = qrcode.make(data)
    buffer = io.BytesIO()
    qr.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer.read()


def _qr_platypus_image(data: str, width=120):
    buf = io.BytesIO(_qr_to_image_bytes(data))
    return Image(buf, width, width)


def _fmt_money(value) -> str:
    if value is None:
        return "0.00"
    try:
        from decimal import Decimal
        d = Decimal(str(value))
        # No thousands separator to keep the value as a single token
        return f"{d:.2f}"
    except Exception:
        return str(value)


def _caja_resolucion(empresa) -> list:
    filas = [
        [Paragraph(f"<b>NIT/DV:</b> {empresa.get('nit', '')}"),
         Paragraph(f"<b>Resolución DIAN:</b> {empresa.get('resolucion_dian', '')}")],
        [Paragraph(f"<b>Rango de numeración:</b> {empresa.get('rango_desde', '')} - {empresa.get('rango_hasta', '')}"),
         Paragraph(f"<b>Fecha resolución:</b> {empresa.get('fecha_resolucion', '')}")],
    ]
    tabla = Table(filas, colWidths=[8 * cm, 8 * cm])
    tabla.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f5f5f5")),
    ]))
    return [Paragraph("<b>RESOLUCIÓN DIAN</b>"), Spacer(1, 4), tabla, Spacer(1, 8)]


def _seccion_emisor(empresa) -> list:
    elementos = [
        Paragraph(f"<b>{empresa.get('razon_social', '')}</b>"),
        Paragraph(f"NIT: {empresa.get('nit', '')}"),
        Paragraph(f"Dirección: {empresa.get('direccion', '')}"),
        Paragraph(f"Municipio: {empresa.get('municipio', '')}"),
        Spacer(1, 8),
    ]
    return elementos


def _seccion_adquirente(cliente) -> list:
    if not cliente:
        cliente = {}
    elementos = [
        Paragraph(f"<b>{cliente.get('razon_social', cliente.get('proveedor_nombre', 'N/A'))}</b>"),
        Paragraph(f"Documento: {cliente.get('tipo_documento', '')} {cliente.get('nit', '')}"),
        Paragraph(f"Dirección: {cliente.get('direccion', '')}"),
        Paragraph(f"Municipio: {cliente.get('municipio', '')}"),
        Spacer(1, 8),
    ]
    return elementos


def _tabla_lineas_factura(lineas) -> list:
    if not lineas:
        return []
    filas = [[
        Paragraph("<b>Código</b>"),
        Paragraph("<b>Descripción</b>"),
        Paragraph("<b>Cant.</b>"),
        Paragraph("<b>V. Unit.</b>"),
        Paragraph("<b>Base</b>"),
        Paragraph("<b>IVA</b>"),
    ]]
    for l in lineas:
        filas.append([
            str(l.get("producto_codigo", "")),
            str(l.get("descripcion", "")),
            str(l.get("cantidad", "")),
            _fmt_money(l.get("valor_unitario")),
            _fmt_money(l.get("subtotal")),
            _fmt_money(l.get("valor_iva")),
        ])
    tabla = Table(filas, colWidths=[
        2.5 * cm, 5 * cm, 2 * cm, 3 * cm, 3 * cm, 3 * cm
    ])
    tabla.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#333333")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#fafafa")]),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return [Spacer(1, 6), tabla, Spacer(1, 8)]


def _tabla_impuestos(datos) -> list:
    filas = [
        [Paragraph("<b>Concepto</b>"), Paragraph("<b>Valor</b>")],
        [Paragraph("Subtotal"), Paragraph(_fmt_money(datos.get("subtotal")))],
        [Paragraph("IVA 19%"), Paragraph(_fmt_money(datos.get("iva_19")))],
        [Paragraph("IVA 5%"), Paragraph(_fmt_money(datos.get("iva_5")))],
        [Paragraph("IVA 0%"), Paragraph(_fmt_money(datos.get("iva_0")))],
        [Paragraph("<b>Total IVA</b>"), Paragraph(f"<b>{_fmt_money(datos.get('total_iva'))}</b>")],
        [Paragraph("Retención en la Fuente"), Paragraph(_fmt_money(datos.get("retefuente")))],
        [Paragraph("ReteICA"), Paragraph(_fmt_money(datos.get("reteica")))],
        [Paragraph("ReteIVA"), Paragraph(_fmt_money(datos.get("reteiva")))],
        [Paragraph("<b>TOTAL FACTURA</b>"), Paragraph(f"<b>{_fmt_money(datos.get('total_factura'))}</b>")],
    ]
    tabla = Table(filas, colWidths=[8 * cm, 5 * cm])
    tabla.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#333333")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
    ]))
    return [Spacer(1, 6), tabla, Spacer(1, 10)]


def _seccion_cufe(cufe: str) -> list:
    elementos = [
        Paragraph(f"<b>CUFE:</b> {cufe}"),
        Spacer(1, 6),
        Paragraph(f"<font size=6>{cufe}</font>"),
        Spacer(1, 6),
    ]
    return elementos


def _seccion_ley_1231() -> list:
    texto = ("En caso de disputa o divergencia entre el contenido del documento electrónico y el "
             "comprobante en papel, este primará frente a la Administración y a terceros. "
             "Ley 1231 de 2008, Art. 44 y 57. Decreto 1082 de 2015, Art. 2.2.1.4.20.")
    return [Paragraph(f"<font size=6>{texto}</font>"), Spacer(1, 8)]


def _seccion_qr(qr_data: str) -> list:
    if not qr_data:
        return []
    return [
        Spacer(1, 6),
        Paragraph("<b>Código QR Ley 1430 de 2011:</b>"),
        _qr_platypus_image(qr_data, width=100),
        Spacer(1, 10),
    ]


def _titulo_documento(tipo: str) -> Paragraph:
    titulos = {
        "FACTURA": "FACTURA DE VENTA",
        "NOTA_CREDITO": "NOTA CRÉDITO",
        "NOTA_DEBITO": "NOTA DÉBITO",
        "DOCUMENTO_SOPORTE": "DOCUMENTO DE SOPORTE",
        "RECIBO_CAJA": "RECIBO DE CAJA",
        "COMPROBANTE_EGRESO": "COMPROBANTE DE EGRESO",
        "NOMINA_DESPRENDIBLE": "DESPRENDIBLE DE NÓMINA",
    }
    return Paragraph(titulos.get(tipo, tipo), _estilos()["TítuloDoc"])


def _seccion_referencia_padre(documento) -> list:
    consecutivo_padre = documento.get("factura_consecutivo", "")
    cufe_padre = documento.get("cufe_factura", "")
    if not consecutivo_padre:
        return []
    return [
        Paragraph(f"<b>Documento padre:</b> {consecutivo_padre}"),
        Paragraph(f"<b>CUFE padre:</b> {cufe_padre}"),
        Spacer(1, 6),
    ]


def _seccion_motivo(documento) -> list:
    motivo = documento.get("motivo_dian") or documento.get("concepto_dian")
    desc = documento.get("descripcion_motivo", "")
    if not motivo:
        return []
    return [
        Paragraph(f"<b>Concepto DIAN:</b> {motivo}"),
        Paragraph(f"<b>Descripción:</b> {desc}"),
        Spacer(1, 6),
    ]


def _build_factura(factura, empresa, cliente) -> list:
    elementos = []
    elementos.append(_titulo_documento("FACTURA"))
    elementos.extend(_caja_resolucion(empresa))

    tabla_info = Table([
        [
            Paragraph("<b>Emisor</b>"),
            Paragraph("<b>Adquirente</b>"),
        ],
        [
            Paragraph(
                f"<b>{empresa.get('razon_social', '')}</b><br/>"
                f"NIT: {empresa.get('nit', '')}<br/>"
                f"Dirección: {empresa.get('direccion', '')}<br/>"
                f"{empresa.get('municipio', '')}",
            ),
            Paragraph(
                f"<b>{cliente.get('razon_social', 'N/A')}</b><br/>"
                f"Documento: {cliente.get('tipo_documento', '')} {cliente.get('nit', '')}<br/>"
                f"Dirección: {cliente.get('direccion', '')}<br/>"
                f"{cliente.get('municipio', '')}",
            ),
        ],
    ], colWidths=[8.5 * cm, 8.5 * cm])
    tabla_info.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#333333")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    elementos.append(tabla_info)
    elementos.append(Spacer(1, 8))

    tabla_datos = Table([
        ["Consecutivo:", f"<b>{factura.get('consecutivo', '')}</b>"],
        ["Fecha:", f"{factura.get('fecha', '')} {factura.get('hora', '')}"],
        ["CUFE:", factura.get("cufe", "")],
        ["Track ID:", factura.get("track_id", "")],
        ["Estado DIAN:", factura.get("estado_dian", "")],
    ], colWidths=[4 * cm, 8 * cm])
    tabla_datos.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f5f5f5")),
    ]))
    elementos.append(tabla_datos)
    elementos.append(Spacer(1, 10))

    elementos.extend(_tabla_lineas_factura(factura.get("lineas", [])))
    elementos.extend(_tabla_impuestos(factura))
    elementos.extend(_seccion_qr(factura.get("qr", "")))
    elementos.extend(_seccion_cufe(factura.get("cufe", "")))
    elementos.extend(_seccion_ley_1231())
    return elementos


def _build_nota_credito(nc, empresa, cliente) -> list:
    elementos = []
    elementos.append(_titulo_documento("NOTA_CREDITO"))
    elementos.extend(_caja_resolucion(empresa))
    elementos.extend(_seccion_emisor(empresa))
    elementos.extend(_seccion_adquirente(cliente))
    elementos.append(Paragraph(f"<b>Consecutivo:</b> {nc.get('consecutivo', '')}"))
    elementos.append(Paragraph(f"<b>Fecha:</b> {nc.get('fecha', '')} {nc.get('hora', '')}"))
    elementos.extend(_seccion_referencia_padre(nc))
    elementos.extend(_seccion_motivo(nc))
    elementos.extend(_tabla_lineas_factura(nc.get("lineas", [])))
    elementos.append(Paragraph(f"<b>Subtotal:</b> {_fmt_money(nc.get('subtotal'))}"))
    elementos.append(Paragraph(f"<b>Total IVA:</b> {_fmt_money(nc.get('total_iva'))}"))
    elementos.append(Paragraph(f"<b>TOTAL NOTA:</b> {_fmt_money(nc.get('total_nota'))}"))
    elementos.append(Spacer(1, 8))
    elementos.extend(_seccion_qr(nc.get("qr", "")))
    elementos.extend(_seccion_cufe(nc.get("cude", "")))
    elementos.extend(_seccion_ley_1231())
    return elementos


def _build_nota_debito(nd, empresa, cliente) -> list:
    elementos = []
    elementos.append(_titulo_documento("NOTA_DEBITO"))
    elementos.extend(_caja_resolucion(empresa))
    elementos.extend(_seccion_emisor(empresa))
    elementos.extend(_seccion_adquirente(cliente))
    elementos.append(Paragraph(f"<b>Consecutivo:</b> {nd.get('consecutivo', '')}"))
    elementos.append(Paragraph(f"<b>Fecha:</b> {nd.get('fecha', '')} {nd.get('hora', '')}"))
    elementos.extend(_seccion_referencia_padre(nd))
    elementos.extend(_seccion_motivo(nd))
    lineas = nd.get("lineas", [])
    if lineas:
        elementos.extend(_tabla_lineas_factura(lineas))
    elementos.append(Paragraph(f"<b>Subtotal:</b> {_fmt_money(nd.get('subtotal'))}"))
    elementos.append(Paragraph(f"<b>Total IVA:</b> {_fmt_money(nd.get('total_iva'))}"))
    elementos.append(Paragraph(f"<b>TOTAL NOTA:</b> {_fmt_money(nd.get('total_nota'))}"))
    elementos.append(Spacer(1, 8))
    elementos.extend(_seccion_qr(nd.get("qr", "")))
    elementos.extend(_seccion_cufe(nd.get("cude", "")))
    elementos.extend(_seccion_ley_1231())
    return elementos


def _build_documento_soporte(ds, empresa, cliente) -> list:
    elementos = []
    elementos.append(_titulo_documento("DOCUMENTO_SOPORTE"))
    elementos.extend(_caja_resolucion(empresa))
    elementos.extend(_seccion_emisor(empresa))
    proveedor = {
        "razon_social": ds.get("proveedor_nombre", ""),
        "nit": ds.get("proveedor_nit", ""),
        "tipo_documento": "NIT",
    }
    elementos.extend(_seccion_adquirente(proveedor))
    elementos.append(Paragraph(f"<b>Consecutivo:</b> {ds.get('consecutivo', '')}"))
    elementos.append(Paragraph(f"<b>Fecha:</b> {ds.get('fecha', '')} {ds.get('hora', '')}"))
    elementos.extend(_tabla_lineas_factura(
        [{"producto_codigo": "", "descripcion": l.get("descripcion", ""),
          "cantidad": l.get("cantidad", ""), "valor_unitario": l.get("valor_unitario", ""),
          "subtotal": l.get("subtotal", ""), "valor_iva": "0.00"}
         for l in ds.get("lineas", [])]
    ))
    elementos.append(Paragraph(f"<b>Subtotal:</b> {_fmt_money(ds.get('subtotal'))}"))
    elementos.append(Paragraph(f"<b>Retención en la Fuente:</b> {_fmt_money(ds.get('retefuente'))}"))
    elementos.append(Paragraph(f"<b>TOTAL DOCUMENTO:</b> {_fmt_money(ds.get('total_documento'))}"))
    elementos.append(Spacer(1, 8))
    elementos.extend(_seccion_qr(ds.get("qr", "")))
    elementos.append(Paragraph(f"<b>CUDS:</b> {ds.get('cuds', '')}"))
    elementos.append(Spacer(1, 6))
    elementos.extend(_seccion_ley_1231())
    return elementos


def _build_recibo_caja(rc, empresa, cliente) -> list:
    elementos = []
    elementos.append(_titulo_documento("RECIBO_CAJA"))
    elementos.extend(_caja_resolucion(empresa))
    elementos.extend(_seccion_emisor(empresa))
    elementos.append(Paragraph(f"<b>Cliente:</b> {cliente.get('razon_social', '') if cliente else ''}"))
    elementos.append(Paragraph(f"<b>Documento:</b> NIT {rc.get('cliente_nit', '')}"))
    elementos.append(Spacer(1, 8))
    tabla = Table([
        ["Número:", f"<b>{rc.get('numero', '')}</b>"],
        ["Fecha:", f"{rc.get('fecha', '')}"],
        ["Factura:", rc.get("factura_consecutivo", "")],
        ["Monto:", f"<b>{_fmt_money(rc.get('monto'))}</b>"],
        ["Medio de pago:", rc.get("medio_pago", "")],
        ["Referencia:", rc.get("referencia", "")],
    ], colWidths=[4 * cm, 8 * cm])
    tabla.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f5f5f5")),
    ]))
    elementos.append(tabla)
    elementos.append(Spacer(1, 10))
    elementos.append(Paragraph(f"Recibí la suma de {_fmt_money(rc.get('monto'))} pesos."))
    elementos.append(Spacer(1, 30))
    elementos.append(Paragraph("_________________________________  ____________________"))
    elementos.append(Paragraph("Firma / Sello  Fecha"))
    return elementos


def _build_comprobante_egreso(ce, empresa, cliente) -> list:
    elementos = []
    elementos.append(_titulo_documento("COMPROBANTE_EGRESO"))
    elementos.extend(_caja_resolucion(empresa))
    elementos.extend(_seccion_emisor(empresa))
    elementos.append(Paragraph(f"<b>Proveedor:</b> {cliente.get('razon_social', '') if cliente else ce.get('proveedor_nombre', '')}"))
    elementos.append(Paragraph(f"<b>Documento:</b> NIT {ce.get('cliente_nit', ce.get('proveedor_nit', ''))}"))
    elementos.append(Spacer(1, 8))
    tabla = Table([
        ["Número:", f"<b>{ce.get('numero', '')}</b>"],
        ["Fecha:", f"{ce.get('fecha', '')}"],
        ["Referencia:", f"{ce.get('referencia', '')}"],
        ["Monto:", f"<b>{_fmt_money(ce.get('monto'))}</b>"],
        ["Medio de pago:", ce.get("medio_pago", "")],
    ], colWidths=[4 * cm, 8 * cm])
    tabla.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f5f5f5")),
    ]))
    elementos.append(tabla)
    elementos.append(Spacer(1, 10))
    elementos.append(Paragraph(f"Comprobante de egreso por {_fmt_money(ce.get('monto'))} pesos."))
    return elementos


def _build_nomina_desprendible(nomina, empresa, cliente) -> list:
    emp = nomina.get("empleado", {})
    elementos = []
    elementos.append(_titulo_documento("NOMINA_DESPRENDIBLE"))
    elementos.extend(_caja_resolucion(empresa))
    elementos.extend(_seccion_emisor(empresa))
    elementos.extend(_seccion_adquirente({
        "razon_social": f"{emp.get('nombres', '')} {emp.get('apellidos', '')}",
        "nit": emp.get("documento", ""),
        "tipo_documento": emp.get("tipo_documento", ""),
        "direccion": "",
        "municipio": "",
    }))
    elementos.append(Paragraph(f"<b>Consecutivo:</b> {nomina.get('consecutivo', '')}"))
    elementos.append(Paragraph(f"<b>Periodo:</b> {nomina.get('periodo_inicio', '')} - {nomina.get('periodo_fin', '')}"))
    elementos.append(Paragraph(f"<b>Fecha emisión:</b> {nomina.get('fecha_emision', '')} {nomina.get('hora_emision', '')}"))
    elementos.append(Spacer(1, 8))
    tabla = Table([
        ["Concepción", "Valor"],
        ["Salario base", _fmt_money(emp.get("salario_base"))],
        ["Auxilio de transporte", _fmt_money(emp.get("auxilio_transporte"))],
        ["Total devengado", f"<b>{_fmt_money(nomina.get('total_devengado'))}</b>"],
        ["Total deducciones", f"<b>{_fmt_money(nomina.get('total_deducciones'))}</b>"],
        ["NETO PAGAR", f"<b>{_fmt_money(nomina.get('neto_pagar'))}</b>"],
    ], colWidths=[8 * cm, 5 * cm])
    tabla.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#333333")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#f5f5f5")),
    ]))
    elementos.append(tabla)
    elementos.append(Spacer(1, 8))
    elementos.append(Paragraph(f"<b>CUNE:</b> {nomina.get('cune', '')}"))
    elementos.append(Spacer(1, 6))
    elementos.append(Paragraph("Recibido conforme:"))
    elementos.append(Spacer(1, 20))
    elementos.append(Paragraph("_________________________________  ____________________"))
    elementos.append(Paragraph("Firma del trabajador  Fecha"))
    return elementos


def generar_pdf_documento(
    tipo: str,
    documento: dict,
    empresa: dict | None = None,
    cliente: dict | None = None,
) -> bytes:
    """Genera el PDF del documento dado. Devuelve bytes del PDF."""
    tipo = tipo.upper()
    if tipo not in TIPOS_DOCUMENTO:
        raise ValueError(f"Tipo de documento no soportado: {tipo}")

    if empresa is None:
        from sap_colombia import database as db
        empresa = db.get_empresa() or {}
    if cliente is None and tipo not in ("NOMINA_DESPRENDIBLE", "DOCUMENTO_SOPORTE"):
        if isinstance(documento, dict) and documento.get("cliente_nit"):
            from sap_colombia import database as db
            for c in db.get_clientes():
                if c.get("nit") == documento.get("cliente_nit"):
                    cliente = c
                    break

    import reportlab.rl_config
    reportlab.rl_config.pageCompression = 0

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
        title=f"Documento {tipo}",
    )

    if tipo == "FACTURA":
        elementos = _build_factura(documento, empresa, cliente or {})
    elif tipo == "NOTA_CREDITO":
        elementos = _build_nota_credito(documento, empresa, cliente)
    elif tipo == "NOTA_DEBITO":
        elementos = _build_nota_debito(documento, empresa, cliente)
    elif tipo == "DOCUMENTO_SOPORTE":
        elementos = _build_documento_soporte(documento, empresa, cliente)
    elif tipo == "RECIBO_CAJA":
        elementos = _build_recibo_caja(documento, empresa, cliente)
    elif tipo == "COMPROBANTE_EGRESO":
        elementos = _build_comprobante_egreso(documento, empresa, cliente)
    elif tipo == "NOMINA_DESPRENDIBLE":
        elementos = _build_nomina_desprendible(documento, empresa, cliente)
    else:
        raise ValueError(f"Tipo no soportado: {tipo}")

    doc.build(elementos)
    buffer.seek(0)
    return buffer.read()
