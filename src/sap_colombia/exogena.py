"""Generador de Información Exógena DIAN — Medios Magnéticos y Certificados de Retención.

Implementa:
- Formato 1001: Pagos o abonos en cuenta y retenciones practicadas a terceros
- Formato 1007: Ingresos propios recibidos
- Certificados de Retención en la Fuente y ReteICA (Art. 378-381 ET)

Normativa: Resolución DIAN sobre Medios Magnéticos para Personas Jurídicas.
"""

import xml.etree.ElementTree as ET
from sap_colombia import dbutil
from decimal import Decimal
from datetime import datetime

import sap_colombia.database as db


# ============================================
# FORMATO 1001 — Pagos o abonos a terceros
# ============================================

def _es_cuenta_gasto(codigo: str) -> bool:
    return codigo.startswith(("51", "52"))


def _es_cuenta_cxp(codigo: str) -> bool:
    return codigo.startswith(("22", "23"))


def _es_retencion_fuente_practicada(codigo: str) -> bool:
    return codigo.startswith("2365")


def _es_reteiva_practicada(codigo: str) -> bool:
    return codigo.startswith("2368")


def extraer_formato_1001(ano: int) -> list[dict]:
    """Extrae datos para el Formato 1001 agrupados por tercero (NIT).

    Fuentes contables:
    - Cuentas de gasto (51xx, 52xx): débitos
    - Cuentas por pagar (22xx, 23xx): créditos
    - Retenciones practicadas (2365xx, 2368xx): créditos

    Returns:
        Lista de registros con campos normativos DIAN, uno por tercero.
    """
    conn = db.get_connection()
    try:
        sql = """
            SELECT m.cuenta_codigo, m.tercero_nit, m.tercero_nombre, m.concepto,
                   m.debito, m.credito, a.fecha
            FROM movimientos_contables m
            JOIN asientos_contables a ON m.asiento_id = a.id
            WHERE (m.cuenta_codigo LIKE '51%%' OR m.cuenta_codigo LIKE '52%%'
                   OR m.cuenta_codigo LIKE '22%%' OR m.cuenta_codigo LIKE '23%%')
              AND a.fecha LIKE ?
            ORDER BY m.tercero_nit, m.id
        """
        filas = [dict(r) for r in dbutil.query(conn, sql, (f"{ano}%",)).fetchall()]
    finally:
        conn.close()

    terceros: dict[str, dict] = {}

    for fila in filas:
        nit = fila["tercero_nit"]
        if not nit:
            continue

        if nit not in terceros:
            terceros[nit] = {
                "tercero_nit": nit,
                "tercero_nombre": fila.get("tercero_nombre", ""),
                "pago_abono_deducible": Decimal("0.00"),
                "pago_abono_no_deducible": Decimal("0.00"),
                "retencion_fuente_practicada": Decimal("0.00"),
                "retencion_iva_practicada": Decimal("0.00"),
                "conceptos": [],
            }

        rec = terceros[nit]
        codigo = fila["cuenta_codigo"]
        deb = Decimal(fila["debito"] or "0.00")
        cred = Decimal(fila["credito"] or "0.00")

        if _es_retencion_fuente_practicada(codigo):
            rec["retencion_fuente_practicada"] += cred
        elif _es_reteiva_practicada(codigo):
            rec["retencion_iva_practicada"] += cred
        elif _es_cuenta_gasto(codigo):
            rec["pago_abono_deducible"] += deb
        elif _es_cuenta_cxp(codigo):
            rec["pago_abono_deducible"] += cred

        rec["conceptos"].append(fila.get("concepto", ""))

    return sorted(terceros.values(), key=lambda x: x["tercero_nit"])


def _buscar_tercero_info(nit: str) -> dict:
    """Busca información del tercero en clientes y proveedores."""
    conn = db.get_connection()
    try:
        # Buscar en clientes
        fila = dbutil.query(conn, 
            "SELECT * FROM clientes WHERE nit = ?", (nit,)
        ).fetchone()
        if fila:
            return dict(fila)
        
        # Si no está en clientes, buscar en proveedores (si existe la tabla)
        try:
            fila = dbutil.query(conn, 
                "SELECT * FROM proveedores WHERE nit = ?", (nit,)
            ).fetchone()
            if fila:
                return dict(fila)
        except Exception:
            # Tabla proveedores no existe, ignorar
            pass
    finally:
        conn.close()
    return {}


def construir_xml_formato_1001(ano: int) -> str:
    """Construye el XML oficial DIAN Formato 1001.

    Estructura:
    - <ExogenaFormato1001>
      - <Encabezado> con NIT, DV, Razon_Social, Periodo
      - <Registros> con un <Registro> por tercero
    """
    registros = extraer_formato_1001(ano)
    empresa = db.get_empresa()
    nit_emisor = empresa["nit"] if empresa else ""
    dv_emisor = empresa.get("dv", "") if empresa else ""

    root = ET.Element("ExogenaFormato1001")

    enc = ET.SubElement(root, "Encabezado")
    ET.SubElement(enc, "NIT").text = nit_emisor
    ET.SubElement(enc, "DV").text = dv_emisor or ""
    ET.SubElement(enc, "Razon_Social").text = empresa["razon_social"] if empresa else ""
    ET.SubElement(enc, "Periodo").text = str(ano)
    ET.SubElement(enc, "Fecha_Generacion").text = datetime.now().strftime("%Y-%m-%d")

    regs_elem = ET.SubElement(root, "Registros")
    for rec in registros:
        reg = ET.SubElement(regs_elem, "Registro")
        ET.SubElement(reg, "NIT").text = rec["tercero_nit"]
        ET.SubElement(reg, "Concepto").text = ", ".join(rec["conceptos"][:3])
        ET.SubElement(reg, "Tipo_Doc").text = "NIT"
        ET.SubElement(reg, "Numero_Doc").text = rec["tercero_nit"]

        info = _buscar_tercero_info(rec["tercero_nit"])
        nombre = rec["tercero_nombre"] or info.get("razon_social", "")
        ET.SubElement(reg, "Primer_Apellido").text = nombre.split()[0] if nombre else ""
        ET.SubElement(reg, "Segundo_Apellido").text = nombre.split()[1] if len(nombre.split()) > 1 else ""
        ET.SubElement(reg, "Primer_Nombre").text = nombre.split()[-1] if nombre else ""
        ET.SubElement(reg, "Otros_Nombres").text = ""
        ET.SubElement(reg, "Razon_Social").text = info.get("razon_social", "") if info else ""
        ET.SubElement(reg, "Direccion").text = info.get("direccion", "") if info else ""
        ET.SubElement(reg, "Depto").text = info.get("municipio", "") if info else ""
        ET.SubElement(reg, "Mpio").text = info.get("municipio", "") if info else ""
        ET.SubElement(reg, "Pago_Abono_Deducible").text = str(rec["pago_abono_deducible"])
        ET.SubElement(reg, "Pago_Abono_No_Deducible").text = str(rec["pago_abono_no_deducible"])
        ET.SubElement(reg, "Retencion_Fuente_Practicada").text = str(rec["retencion_fuente_practicada"])
        ET.SubElement(reg, "Retencion_IVA_Practicada").text = str(rec["retencion_iva_practicada"])

    xml_str = ET.tostring(root, encoding="unicode")
    xml_str = xml_str.replace("><", ">\n<")
    return xml_str


# ============================================
# FORMATO 1003 — Ingresos operacionales
# ============================================

def extraer_formato_1003(ano: int) -> list[dict]:
    """Extrae datos para el Formato 1003 agrupados por cliente.

    Fuentes:
    - Facturas del año

    Returns:
        Lista de registros con campos: nit_tercero, nombre_tercero, fecha,
        consecutivo, tipo_operacion, subtotal, iva_19, iva_5, iva_0, total.
    """
    conn = db.get_connection()
    try:
        sql = """
            SELECT f.consecutivo, f.fecha, f.cliente_nit, f.subtotal,
                   f.iva_19, f.iva_5, f.iva_0, f.total_factura, f.prefijo
            FROM facturas f
            WHERE f.fecha LIKE ?
            ORDER BY f.fecha, f.consecutivo
        """
        filas = [dict(r) for r in dbutil.query(conn, sql, (f"{ano}%",)).fetchall()]
    finally:
        conn.close()

    registros = []
    for fila in filas:
        nit = fila["cliente_nit"]
        if not nit:
            continue
        info = _buscar_tercero_info(nit)
        nombre = info.get("razon_social", "")

        registros.append({
            "nit_tercero": nit,
            "nombre_tercero": nombre,
            "fecha": fila["fecha"],
            "consecutivo": f"{fila['prefijo'] or ''}{fila['consecutivo']}",
            "tipo_operacion": "VENTA",
            "subtotal": Decimal(fila["subtotal"] or "0.00"),
            "iva_19": Decimal(fila["iva_19"] or "0.00"),
            "iva_5": Decimal(fila["iva_5"] or "0.00"),
            "iva_0": Decimal(fila["iva_0"] or "0.00"),
            "total": Decimal(fila["total_factura"] or "0.00"),
        })

    return sorted(registros, key=lambda x: x["nit_tercero"])


def construir_xml_formato_1003(ano: int) -> str:
    """Construye el XML oficial DIAN Formato 1003."""
    registros = extraer_formato_1003(ano)
    empresa = db.get_empresa()
    nit_emisor = empresa["nit"] if empresa else ""
    dv_emisor = empresa.get("dv", "") if empresa else ""

    root = ET.Element("ExogenaFormato1003")

    enc = ET.SubElement(root, "Encabezado")
    ET.SubElement(enc, "NIT").text = nit_emisor
    ET.SubElement(enc, "DV").text = dv_emisor or ""
    ET.SubElement(enc, "Razon_Social").text = empresa["razon_social"] if empresa else ""
    ET.SubElement(enc, "Periodo").text = str(ano)
    ET.SubElement(enc, "Fecha_Generacion").text = datetime.now().strftime("%Y-%m-%d")

    regs_elem = ET.SubElement(root, "Registros")
    for rec in registros:
        reg = ET.SubElement(regs_elem, "Registro")
        ET.SubElement(reg, "NIT").text = rec["nit_tercero"]
        ET.SubElement(reg, "Nombre_Tercero").text = rec["nombre_tercero"]
        ET.SubElement(reg, "Fecha").text = rec["fecha"]
        ET.SubElement(reg, "Consecutivo").text = rec["consecutivo"]
        ET.SubElement(reg, "Tipo_Operacion").text = rec["tipo_operacion"]
        ET.SubElement(reg, "Subtotal").text = str(rec["subtotal"])
        ET.SubElement(reg, "IVA_19").text = str(rec["iva_19"])
        ET.SubElement(reg, "IVA_5").text = str(rec["iva_5"])
        ET.SubElement(reg, "IVA_0").text = str(rec["iva_0"])
        ET.SubElement(reg, "Total").text = str(rec["total"])

    xml_str = ET.tostring(root, encoding="unicode")
    xml_str = xml_str.replace("><", ">\n<")
    return xml_str


# ============================================
# FORMATO 1007 — Ingresos propios recibidos
# ============================================

def extraer_formato_1007(ano: int) -> list[dict]:
    """Extrae datos para el Formato 1007 agrupados por cliente.

    Fuentes contables:
    - Cuentas de ingreso operacional (4135xx): créditos (ventas)
    - Devoluciones (4175xx): débitos (se restan)

    Returns:
        Lista de registros con ingresos netos por cliente.
    """
    conn = db.get_connection()
    try:
        sql = """
            SELECT m.cuenta_codigo, m.tercero_nit, m.tercero_nombre, m.concepto,
                   m.debito, m.credito, a.fecha
            FROM movimientos_contables m
            JOIN asientos_contables a ON m.asiento_id = a.id
            WHERE (m.cuenta_codigo LIKE '4135%%' OR m.cuenta_codigo LIKE '4175%%')
              AND a.fecha LIKE ?
            ORDER BY m.tercero_nit, m.id
        """
        filas = [dict(r) for r in dbutil.query(conn, sql, (f"{ano}%",)).fetchall()]
    finally:
        conn.close()

    clientes: dict[str, dict] = {}

    for fila in filas:
        nit = fila["tercero_nit"]
        if not nit:
            continue

        if nit not in clientes:
            clientes[nit] = {
                "tercero_nit": nit,
                "tercero_nombre": fila.get("tercero_nombre", ""),
                "ingresos_recibidos": Decimal("0.00"),
                "devoluciones": Decimal("0.00"),
                "ingresos_netos": Decimal("0.00"),
                "conceptos": [],
            }

        rec = clientes[nit]
        codigo = fila["cuenta_codigo"]
        deb = Decimal(fila["debito"] or "0.00")
        cred = Decimal(fila["credito"] or "0.00")

        if codigo.startswith("4135"):
            rec["ingresos_recibidos"] += cred
        elif codigo.startswith("4175"):
            rec["devoluciones"] += deb

        rec["ingresos_netos"] = rec["ingresos_recibidos"] - rec["devoluciones"]
        rec["conceptos"].append(fila.get("concepto", ""))

    return sorted(clientes.values(), key=lambda x: x["tercero_nit"])


def construir_xml_formato_1007(ano: int) -> str:
    """Construye el XML oficial DIAN Formato 1007."""
    registros = extraer_formato_1007(ano)
    empresa = db.get_empresa()
    nit_emisor = empresa["nit"] if empresa else ""
    dv_emisor = empresa.get("dv", "") if empresa else ""

    root = ET.Element("ExogenaFormato1007")

    enc = ET.SubElement(root, "Encabezado")
    ET.SubElement(enc, "NIT").text = nit_emisor
    ET.SubElement(enc, "DV").text = dv_emisor or ""
    ET.SubElement(enc, "Razon_Social").text = empresa["razon_social"] if empresa else ""
    ET.SubElement(enc, "Periodo").text = str(ano)
    ET.SubElement(enc, "Fecha_Generacion").text = datetime.now().strftime("%Y-%m-%d")

    regs_elem = ET.SubElement(root, "Registros")
    for rec in registros:
        reg = ET.SubElement(regs_elem, "Registro")
        ET.SubElement(reg, "NIT").text = rec["tercero_nit"]
        ET.SubElement(reg, "Concepto").text = ", ".join(rec["conceptos"][:3])
        ET.SubElement(reg, "Tipo_Doc").text = "NIT"
        ET.SubElement(reg, "Numero_Doc").text = rec["tercero_nit"]

        info = _buscar_tercero_info(rec["tercero_nit"])
        nombre = rec["tercero_nombre"] or info.get("razon_social", "")
        ET.SubElement(reg, "Razon_Social").text = info.get("razon_social", "") if info else ""
        ET.SubElement(reg, "Direccion").text = info.get("direccion", "") if info else ""
        ET.SubElement(reg, "Depto").text = info.get("municipio", "") if info else ""
        ET.SubElement(reg, "Mpio").text = info.get("municipio", "") if info else ""
        ET.SubElement(reg, "Ingresos_Recibidos").text = str(rec["ingresos_recibidos"])
        ET.SubElement(reg, "Devoluciones").text = str(rec["devoluciones"])
        ET.SubElement(reg, "Ingresos_Netos").text = str(rec["ingresos_netos"])

    xml_str = ET.tostring(root, encoding="unicode")
    xml_str = xml_str.replace("><", ">\n<")
    return xml_str


# ============================================
# CERTIFICADOS DE RETENCIÓN (Art. 378-381 ET)
# ============================================

def generar_certificado_retencion(tercero_nit: str, ano: int) -> dict:
    """Genera el Certificado de Retención en la Fuente y ReteICA.

    Extrae de los movimientos contables:
    - 135515 (Anticipo Retefuente): débitos = retención en la fuente practicada
    - 135518 (Anticipo ReteICA): débitos = retención ICA practicada

    Conforme a Art. 378-381 del Estatuto Tributario.
    """
    conn = db.get_connection()
    try:
        sql = """
            SELECT m.cuenta_codigo, m.debito, m.credito, m.concepto, a.fecha
            FROM movimientos_contables m
            JOIN asientos_contables a ON m.asiento_id = a.id
            WHERE m.tercero_nit = ?
              AND (m.cuenta_codigo LIKE '135515%%' OR m.cuenta_codigo LIKE '135518%%')
              AND a.fecha LIKE ?
            ORDER BY m.id
        """
        filas = [dict(r) for r in dbutil.query(conn, sql, (tercero_nit, f"{ano}%",)).fetchall()]
    finally:
        conn.close()

    total_retefuente = Decimal("0.00")
    total_reteica = Decimal("0.00")
    detalles = []

    for fila in filas:
        codigo = fila["cuenta_codigo"]
        deb = Decimal(fila["debito"] or "0.00")
        cred = Decimal(fila["credito"] or "0.00")
        monto = deb - cred

        if codigo.startswith("135515"):
            total_retefuente += monto
            detalles.append({
                "tipo": "RETEFUENTE",
                "cuenta": codigo,
                "monto": str(monto),
                "fecha": fila["fecha"],
                "concepto": fila["concepto"],
            })
        elif codigo.startswith("135518"):
            total_reteica += monto
            detalles.append({
                "tipo": "RETEICA",
                "cuenta": codigo,
                "monto": str(monto),
                "fecha": fila["fecha"],
                "concepto": fila["concepto"],
            })

    info_tercero = _buscar_tercero_info(tercero_nit)
    empresa = db.get_empresa()

    return {
        "emisor": {
            "nit": empresa["nit"] if empresa else "",
            "dv": empresa.get("dv", "") if empresa else "",
            "razon_social": empresa["razon_social"] if empresa else "",
        },
        "tercero": {
            "nit": tercero_nit,
            "razon_social": info_tercero.get("razon_social", ""),
            "direccion": info_tercero.get("direccion", ""),
        },
        "periodo": str(ano),
        "total_retefuente": str(total_retefuente),
        "total_reteica": str(total_reteica),
        "total_general": str(total_retefuente + total_reteica),
        "detalles": detalles,
    }


def construir_xml_certificado(certificado: dict) -> str:
    """Construye el XML del Certificado de Retención."""
    root = ET.Element("CertificadoRetencion")

    emisor_elem = ET.SubElement(root, "Emisor")
    ET.SubElement(emisor_elem, "NIT").text = certificado["emisor"]["nit"]
    ET.SubElement(emisor_elem, "DV").text = certificado["emisor"].get("dv", "")
    ET.SubElement(emisor_elem, "Razon_Social").text = certificado["emisor"]["razon_social"]

    tercero_elem = ET.SubElement(root, "Tercero")
    ET.SubElement(tercero_elem, "NIT").text = certificado["tercero"]["nit"]
    ET.SubElement(tercero_elem, "Razon_Social").text = certificado["tercero"]["razon_social"]
    ET.SubElement(tercero_elem, "Direccion").text = certificado["tercero"]["direccion"]

    periodo_elem = ET.SubElement(root, "Periodo")
    periodo_elem.text = certificado["periodo"]

    totales_elem = ET.SubElement(root, "Totales")
    ET.SubElement(totales_elem, "RetencionFuente").text = certificado["total_retefuente"]
    ET.SubElement(totales_elem, "RetencionICA").text = certificado["total_reteica"]
    ET.SubElement(totales_elem, "TotalGeneral").text = certificado["total_general"]

    detalles_elem = ET.SubElement(root, "Detalles")
    for det in certificado["detalles"]:
        det_elem = ET.SubElement(detalles_elem, "Detalle")
        ET.SubElement(det_elem, "Tipo").text = det["tipo"]
        ET.SubElement(det_elem, "Monto").text = det["monto"]
        ET.SubElement(det_elem, "Fecha").text = det["fecha"]
        ET.SubElement(det_elem, "Concepto").text = det["concepto"]

    xml_str = ET.tostring(root, encoding="unicode")
    xml_str = xml_str.replace("><", ">\n<")
    return xml_str
