"""Información Exógena DIAN: archivos planos radicable (Res. 000162 de 2023).

La implementación anterior emitía **JSON y XML ad-hoc**. La DIAN no ingiere
ninguno de los dos: exige un archivo de texto plano, delimitado, con un
**registro de encabezado** cuyo nombre sigue el patrón

    mmmvvvaaaaaaaacccccccc
    ││││  ││││  ││││││││ ││││││││││
    ││││  ││││  ││││││││ NIT del contribuyente
    ││││  ││││  └ número de identificación (2) o documento del contribuyente
    ││││  │││└ versión del formato (1)
    ││││  └└└ tipo de información exógena (1001, 1003, 1007, 2275, 2276)
    └────  discriminante

con la extensión ``.TXT`` y separador ``|`` (o tabulación).

Formatos implementados:

======  =====================================================
1001    Pagos o abonos en cuenta a terceros y retenciones
1003    Ingresos operacionales (facturas de venta)
1007    Ingresos propios y gastos deducteduvos del contribuyente
2275    Ingresos no constitutivos de renta ni ganancia accidental
2276    Rentas de trabajo y pensiones (obligatorio para empleadores)
======  =====================================================

Conceptos del art. 25 de la Resolución 000162 de 2023 (tipos de retención que
deben reportarse por separado en el 1001):

=====  ================================================
01      ReteFuente practiced sobre renta (Art. 437-1)
02      ReteICA
03      ReteFuente a no residentes
04      Retención en la fuente por.Consumo de tarjetas
05      Retención porisherías (DIAN 2276)
=====  ================================================
"""

from __future__ import annotations

import datetime
import io
import re
from decimal import Decimal, ROUND_HALF_UP

from sap_colombia import dbutil
import sap_colombia.database as db

#: Separador exigido por la DIAN en los archivos planos.
DELIMITADOR = "|"

#: Catálogo de tipos de identificación (columna 3 de los formatos).
TIPO_DOCUMENTO = {
    "13": "NIT",
    "14": "C.C.",
    "15": "N.N.",
    "16": "N.P.",
    "17": "N.F.",
    "18": "N.E.",
    "19": "N.C.",
    "20": "N.R.",
    "21": "N.D.",
    "22": "CE",
    "23": "N.T.",
    "24": "N.C.C.",
    "30": "D.E.",
    "31": "N.C.E.",
    "32": "C.E.",
    "41": "N.R.E.",
    "42": "N.C.E. (R)",
}

CENTAVOS = Decimal("0.01")

#: Columna "cuenta de cargo" del formato 1003 (motivo del ingreso).
CUENTA_CARGO_1003 = {
    "VENTA": "112010",
    "NOTA_CREDITO": "112011",
    "NOTA_DEBITO": "112012",
}


class ErrorExogena(ValueError):
    """Los datos no permiten construir un archivo exógeno válido."""


def _q2(valor) -> Decimal:
    if valor in (None, ""):
        return Decimal("0.00")
    return Decimal(str(valor)).quantize(CENTAVOS, rounding=ROUND_HALF_UP)


def _d(valor) -> str:
    """Importe con 2 decimales, sin separadores ni exponentes."""
    return format(_q2(valor), "f")


def tipo_documento_por_nit(nit: str, tipo: str | None = None) -> str:
    """Código del catálogo DIAN según el tipo de documento del tercero."""
    t = (tipo or "").strip().upper()
    mapa = {
        "NIT": "13", "NI": "13",
        "CC": "14", "C.C.": "14", "CE": "14", "CÉDULA": "14",
        "CC ": "14",
        "NIT ": "13",
        "PASAPORTE": "16", "N.P.": "16",
        "CARTA DE REPRESENTACION": "20",
        "N.R.": "20",
        "NIT EXTRANJERO": "23",
    }
    if t in mapa:
        return mapa[t]
    # Sin tipo explícito: 13 dígitos ⇒ NIT, 9-10 ⇒ cédula, ≥6 ⇒ pasaporte.
    digitos = re.sub(r"\D", "", str(nit or ""))
    if len(digitos) in (9, 10):
        return "13"
    if len(digitos) >= 12:
        return "13"
    if len(digitos) >= 6:
        return "14"
    return "13"


def nombre_archivo(formato: str, nit: str, anio: int, mes: int = 1, version: int = 1) -> str:
    """Nombre del archivo exógeno según el patrón ``mmmvvvaaaaaaaacccccccc``."""
    if len(formato) != 4:
        raise ErrorExogena(f"El formato debe tener 4 dígitos: {formato!r}")
    digitos = re.sub(r"\D", "", str(nit or ""))
    if not digitos:
        raise ErrorExogena("NIT del contribuyente requerido para nombrar el archivo")
    # El nombre es mmmvvv + NIT (14) + dígito verificador (1).
    # El NIT se alinea a 14 dígitos por la izquierda con ceros; el dígito
    # verificador es el último dígito del NIT real (no del rellenado).
    contribuyente = digitos.zfill(14)[-14:]
    discriminante = digitos[-1]
    return f"{formato}{version:02d}{anio}{contribuyente}{discriminante}.TXT"


def encabezado(
    formato: str,
    nit: str,
    anio: int,
    mes: int = 1,
    version: int = 1,
    nit_solicitante: str = "",
    solicita: str = "1",
) -> str:
    """Registro de encabezado (tipo 000) del archivo exógeno.

    Campos: tipo, versión, NIT contribuyente, periodo, tipo de documento y
    nombre del solicitante, NIT del solicitante, GW FTP, fecha de generación,
    formato, medio de entrega, código solicitante, Diligenciamiento, NIT
   的软件 Review, código delTrader, versión del formato, condición特殊.
    """
    digitos = re.sub(r"\D", "", str(nit or ""))
    generado = datetime.datetime.now()
    campos = [
        "000",                                   # 1. Tipo de registro
        f"{version:02d}",                        # 2. Versión del formato
        digitos,                                 # 3. NIT del contribuyente
        f"{anio:04d}{mes:02d}",                  # 4. Periodo
        "22",                                    # 5. Tipo de documento (NIT)
        "1",                                     # 6. ¿Solicita? (1=si)
        re.sub(r"\D", "", str(nit_solicitante or digitos)),
        generado.strftime("%Y%m%d%H%M%S"),       # 8. Fecha de generación
        formato,                                 # 9. Formato
        "1",                                     # 10. Medio de entrega
        "0",                                     # 11. Código solicitante
        "",                                      # 12. Diligenciamiento
        "",                                      # 13. NIT/software review
        "",                                      # 14. Código del Trader
        f"{version:02d}",                        # 15. Versión del formato
        "",                                      # 16. Condición especial
    ]
    return DELIMITADOR.join(campos)


def linea(formato: str, registros: list[dict], nit: str, anio: int, mes: int = 1,
          version: int = 1) -> str:
    """Construye el archivo exógeno completo (encabezado + registros)."""
    salida = io.StringIO()
    salida.write(encabezado(formato, nit, anio, mes, version) + "\n")
    for r in registros:
        salida.write(DELIMITADOR.join(str(v) for v in r["valores"]) + "\n")
    return salida.getvalue()


# ============================================================
# Helpers de terceros
# ============================================================

def _buscar_tercero(nit: str) -> dict:
    conn = db.get_connection()
    try:
        fila = dbutil.query(
            conn,
            "SELECT nit, dv, tipo_documento, razon_social, direccion, "
            "municipio FROM clientes WHERE nit = ?",
            (nit,),
        ).fetchone()
    finally:
        conn.close()
    return dict(fila) if fila else {}


def _partes_nombre(nombre: str) -> tuple[str, str]:
    """Separa apellidos y nombres para la exógena.

    Formato esperado: "Primer Apellido / Segundo Apellido / Primer Nombre /
    Otros Nombres". Si no viene así, se reparte por palabras.
    """
    texto = (nombre or "").strip()
    if "/" in texto:
        partes = [p.strip() for p in texto.split("/") if p.strip()]
        if len(partes) >= 3:
            return f"{partes[0]} {partes[1]}".strip(), f"{partes[2]} {partes[3] if len(partes) > 3 else ''}".strip()
        if len(partes) == 2:
            return partes[0], partes[1]
    palabras = texto.split()
    if len(palabras) >= 2:
        mitad = len(palabras) // 2
        return " ".join(palabras[:mitad]), " ".join(palabras[mitad:])
    if palabras:
        return "", palabras[0]
    return "", ""


def _apellidos_nombres(nombre: str) -> tuple[str, str]:
    """Devuelve (primer_apellido, primer_nombre) como espera la DIAN."""
    apellidos, nombres = _partes_nombre(nombre)
    primer_apellido = apellidos.split()[0] if apellidos else ""
    primer_nombre = nombres.split()[0] if nombres else ""
    return primer_apellido, primer_nombre


# ============================================================
# FORMATO 1001 — Pagos o abonos a terceros y retenciones
# ============================================================

#: Cuentas de retención en la fuente por naturaleza.
CUENTAS_RETEFUENTE_RENTA = ("236505",)
CUENTAS_RETEICA = ("243505",)
CUENTAS_RETEIVA = ("236802",)
CUENTAS_RETE_NO_RESIDENTE = ("236510",)
CUENTAS_RETENCION_CONSUMO = ("236520",)
CUENTAS_APORTES_SALUD = ("237005", "240808", "240809")
CUENTAS_APORTES_PENSION = ("238030", "231010")
CUENTAS_PARA_FISCALES = ("239001",)
CUENTAS_FONDO_SOLIDARIDAD = ("239015",)

#: Cuentas de pago deoqüentes nomina que deben reportarse en el 1001.
CUENTAS_PAGO_NOMINA = ("250505",)


def extraer_formato_1001(ano: int) -> list[dict]:
    """Extrae los registros del formato 1001 desde el libro contable.

    Agrupa por tercero y separa los conceptos de exógena que el art. 25 de la
    Res. 000162/2023 obliga a reportar por separado (retención de renta, de
    ICA, de IVA, de no residentes, de consumo, salud, pensión, parafiscales).
    """
    conn = db.get_connection()
    try:
        filas = dbutil.query(
            conn,
            """
            SELECT m.tercero_nit, m.cuenta_codigo, m.debito, m.credito, a.fecha
            FROM movimientos_contables m
            JOIN asientos_contables a ON a.id = m.asiento_id
            WHERE m.tercero_nit IS NOT NULL
              AND a.fecha LIKE ?
            """,
            (f"{ano}%",),
        ).fetchall()
    finally:
        conn.close()

    acumulado: dict[str, dict] = {}
    for f in filas:
        nit = f["tercero_nit"]
        debito = _q2(f["debito"])
        credito = _q2(f["credito"])
        if debito == 0 and credito == 0:
            continue
        reg = acumulado.setdefault(nit, {
            "nit": nit,
            "cuenta_pago": "",        # cuentas 1-7 del bloque 1
            "fecha_pago": "",
            "pagos_deducibles": Decimal("0.00"),
            "retefuente_renta": Decimal("0.00"),
            "reteica": Decimal("0.00"),
            "reteiva": Decimal("0.00"),
            "rete_no_residente": Decimal("0.00"),
            "retencion_consumo": Decimal("0.00"),
            "salud": Decimal("0.00"),
            "pension": Decimal("0.00"),
            "parafiscales": Decimal("0.00"),
            "fondo_solidaridad": Decimal("0.00"),
            "total_pagado": Decimal("0.00"),
        })
        cuenta = f["cuenta_codigo"]
        # El pago al tercero es el movimiento del pasivo (crédito) o del gasto
        # (débito) asociado al tercero.
        if cuenta.startswith(("22", "23", "25")) or cuenta.startswith(("51", "52", "53")):
            reg["total_pagado"] += credito if credito else debito
            if not reg["fecha_pago"] or f["fecha"] > reg["fecha_pago"]:
                reg["fecha_pago"] = f["fecha"]
            reg["cuenta_pago"] = cuenta

        if cuenta in CUENTAS_RETEFUENTE_RENTA:
            reg["retefuente_renta"] += credito
        elif cuenta in CUENTAS_RETEICA:
            reg["reteica"] += credito
        elif cuenta in CUENTAS_RETEIVA:
            reg["reteiva"] += credito
        elif cuenta in CUENTAS_RETE_NO_RESIDENTE:
            reg["rete_no_residente"] += credito
        elif cuenta in CUENTAS_RETENCION_CONSUMO:
            reg["retencion_consumo"] += credito
        elif cuenta in CUENTAS_APORTES_SALUD:
            reg["salud"] += debito
        elif cuenta in CUENTAS_APORTES_PENSION:
            reg["pension"] += debito
        elif cuenta in CUENTAS_PARA_FISCALES:
            reg["parafiscales"] += debito
        elif cuenta in CUENTAS_FONDO_SOLIDARIDAD:
            reg["fondo_solidaridad"] += debito

    registros = []
    for nit, reg in sorted(acumulado.items()):
        if not reg["cuenta_pago"]:
            continue
        info = _buscar_tercero(nit)
        reg["nombre"] = info.get("razon_social", "")
        reg["tipo_documento"] = tipo_documento_por_nit(nit, info.get("tipo_documento"))
        reg["direccion"] = info.get("direccion", "")
        reg["municipio"] = info.get("municipio", "")
        registros.append(reg)
    return registros


def registros_1001(ano: int, nit_contribuyente: str = "") -> list[dict]:
    """Filas del archivo 1001 listas para escribir."""
    filas = []
    for i, r in enumerate(extraer_formato_1001(ano), start=1):
        filas.append({
            "valores": [
                str(i).zfill(10),                       # 1. Número de línea
                r["tipo_documento"],                    # 2. Tipo de documento
                r["nit"],                               # 3. NIT/Documento
                r["nombre"],                            # 4. Razón social
                r["cuenta_pago"],                       # 5. Código de la cuenta
                r["fecha_pago"].replace("-", ""),       # 6. Fecha del pago
                "",                                     # 7. Fecha del pago (2)
                _d(r["total_pagado"]),                   # 8. Valor del pago
                "",                                     # 9. Mnd neg/moneda
                "",                                     # 10. Concepto FE
                _d(r["salud"]),                          # 11. Salud
                _d(r["pension"]),                        # 12. Pensión
                _d(r["parafiscales"]),                   # 13. Fondo de CTOS
                _d(r["fondo_solidaridad"]),              # 14. Fondo de solidaridad
                _d(r["retefuente_renta"]),               # 15. ReteFuente renta (859)
                _d(r["reteica"]),                        # 16. ReteICA (860)
                _d(r["reteiva"]),                        # 17. ReteIVA (862)
                _d(r["rete_no_residente"]),              # 18. Rete a no residentes
                _d(r["retencion_consumo"]),              # 19. Retención consumo
                "",                                     # 20. RAI
                "",                                     # 21. Rate de la operación
                "",                                     # 22. NIT扣 del tercero
            ],
        })
    return filas


# ============================================================
# FORMATO 1003 — Ingresos operacionales
# ============================================================

def extraer_formato_1003(ano: int) -> list[dict]:
    """Ingresos operacionales del contribuyente (facturas de venta).

    El prefijo **no** se vuelve a concatenar: ``facturas.consecutivo`` ya lo
    incluye, por lo que el módulo anterior producía ``SETPSETP000001``.
    """
    conn = db.get_connection()
    try:
        filas = dbutil.query(
            conn,
            """
            SELECT f.consecutivo, f.prefijo, f.fecha, f.cliente_nit, f.subtotal,
                   f.iva_19, f.iva_5, f.iva_0, f.total_factura, f.cufe, f.estado_dian
            FROM facturas f
            WHERE f.fecha LIKE ?
            ORDER BY f.fecha, f.consecutivo
            """,
            (f"{ano}%",),
        ).fetchall()
        notas = dbutil.query(
            conn,
            """
            SELECT nc.consecutivo, nc.prefijo, nc.fecha, nc.cliente_nit,
                   nc.total_nota, nc.cude
            FROM notas_credito nc WHERE nc.fecha LIKE ?
            """,
            (f"{ano}%",),
        ).fetchall()
    finally:
        conn.close()

    registros = []
    for f in filas:
        nit = f["cliente_nit"]
        if not nit:
            continue
        info = _buscar_tercero(nit)
        numero = f["consecutivo"] or ""
        if f["prefijo"] and not str(numero).startswith(str(f["prefijo"])):
            numero = f"{f['prefijo']}{numero}"
        registros.append({
            "tipo_registro": "factura",
            "consecutivo": numero,
            "fecha": f["fecha"],
            "nit_tercero": nit,
            "nombre_tercero": info.get("razon_social", ""),
            "tipo_documento": tipo_documento_por_nit(nit, info.get("tipo_documento")),
            "cuenta_cargo": CUENTA_CARGO_1003["VENTA"],
            "subtotal": _q2(f["subtotal"]),
            "iva_19": _q2(f["iva_19"]),
            "iva_5": _q2(f["iva_5"]),
            "iva_0": _q2(f["iva_0"]),
            "total": _q2(f["total_factura"]),
            "cufe": f["cufe"] or "",
            "estado_dian": f["estado_dian"] or "",
        })
    for n in notas:
        nit = n["cliente_nit"]
        if not nit:
            continue
        info = _buscar_tercero(nit)
        numero = n["consecutivo"] or ""
        if n["prefijo"] and not str(numero).startswith(str(n["prefijo"])):
            numero = f"{n['prefijo']}{numero}"
        registros.append({
            "tipo_registro": "nota_credito",
            "consecutivo": numero,
            "fecha": n["fecha"],
            "nit_tercero": nit,
            "nombre_tercero": info.get("razon_social", ""),
            "tipo_documento": tipo_documento_por_nit(nit, info.get("tipo_documento")),
            "cuenta_cargo": CUENTA_CARGO_1003["NOTA_CREDITO"],
            "subtotal": _q2(n["total_nota"]),
            "iva_19": Decimal("0.00"),
            "iva_5": Decimal("0.00"),
            "iva_0": Decimal("0.00"),
            "total": _q2(n["total_nota"]),
            "cufe": n["cude"] or "",
            "estado_dian": "ACEPTADA",
        })
    return sorted(registros, key=lambda r: (r["fecha"], r["consecutivo"]))


def registros_1003(ano: int) -> list[dict]:
    filas = []
    for i, r in enumerate(extraer_formato_1003(ano), start=1):
        filas.append({
            "valores": [
                str(i).zfill(10),
                r["tipo_documento"],
                r["nit_tercero"],
                r["nombre_tercero"],
                r["cuenta_cargo"],
                r["fecha"].replace("-", ""),
                r["consecutivo"],
                r["cufe"],
                "01" if r["tipo_registro"] == "factura" else "91",
                _d(r["subtotal"]),
                _d(r["iva_19"]),
                _d(r["iva_5"]),
                _d(r["iva_0"]),
                _d(r["total"]),
            ],
        })
    return filas


# ============================================================
# FORMATO 1007 — Ingresos propios y gastos deducibles
# ============================================================

def extraer_formato_1007(ano: int) -> list[dict]:
    """Ingresos y gastos deducibles del contribuyente (grupos 1-5 del 1007)."""
    conn = db.get_connection()
    try:
        filas = dbutil.query(
            conn,
            """
            SELECT m.cuenta_codigo, m.debito, m.credito, a.fecha
            FROM movimientos_contables m
            JOIN asientos_contables a ON a.id = m.asiento_id
            WHERE a.fecha LIKE ? AND m.tercero_nit IS NULL
            """,
            (f"{ano}%",),
        ).fetchall()
    finally:
        conn.close()

    grupos = {"1": Decimal("0.00"), "2": Decimal("0.00"),
              "3": Decimal("0.00"), "4": Decimal("0.00"),
              "5": Decimal("0.00")}
    for f in filas:
        cuenta = f["cuenta_codigo"]
        debito = _q2(f["debito"])
        credito = _q2(f["credito"])
        if cuenta.startswith("41"):
            grupos["1"] += credito - debito       # ingresos no constitutivos
        elif cuenta.startswith("51"):
            grupos["2"] += debito - credito        # gastos deducibles
        elif cuenta.startswith("53"):
            grupos["3"] += debito - credito        # costos
        elif cuenta.startswith("54"):
            grupos["5"] += debito - credito        # otros gastos
    return [{"grupo": g, "valor": v} for g, v in grupos.items()]


def registros_1007(ano: int) -> list[dict]:
    filas = []
    for i, r in enumerate(extraer_formato_1007(ano), start=1):
        filas.append({"valores": [str(i).zfill(10), r["grupo"], _d(r["valor"]), ""]})
    return filas


# ============================================================
# FORMATO 2275 — Ingresos no constitutivos de renta
# ============================================================

def extraer_formato_2275(ano: int) -> list[dict]:
    """Ingresos no constitutivos de renta ni ganancia accidental.

    Art. 40 de la Resolución 000162 de 2023:最有 common son las ventas de
    bienes de activo fijo, recoversiones de cartera de clientes y los
    dividendos. Se reportan desde el libro contable.
    """
    from sap_colombia import parametros
    exclusions = parametros.EXCLUSIONES_RETEICA if hasattr(parametros, "EXCLUSIONES_RETEICA") else set()
    conn = db.get_connection()
    try:
        filas = dbutil.query(
            conn,
            """
            SELECT m.tercero_nit, m.cuenta_codigo, m.credito, a.fecha
            FROM movimientos_contables m
            JOIN asientos_contables a ON a.id = m.asiento_id
            WHERE a.fecha LIKE ? AND m.credito <> '0.00'
              AND m.cuenta_codigo LIKE '41%%'
            """,
            (f"{ano}%",),
        ).fetchall()
    finally:
        conn.close()

    registros = []
    for f in filas:
        nit = f["tercero_nit"]
        if not nit:
            continue
        info = _buscar_tercero(nit)
        registros.append({
            "nit": nit,
            "tipo_documento": tipo_documento_por_nit(nit, info.get("tipo_documento")),
            "nombre": info.get("razon_social", ""),
            "fecha": f["fecha"],
            "cuenta": f["cuenta_codigo"],
            "valor": _q2(f["credito"]),
        })
    return registros


def registros_2275(ano: int) -> list[dict]:
    filas = []
    for i, r in enumerate(extraer_formato_2275(ano), start=1):
        filas.append({
            "valores": [
                str(i).zfill(10),
                r["tipo_documento"],
                r["nit"],
                r["nombre"],
                r["fecha"].replace("-", ""),
                r["cuenta"],
                _d(r["valor"]),
                "",                 # concepto 2275
            ],
        })
    return filas


# ============================================================
# FORMATO 2276 — Rentas de trabajo y pensiones
# ============================================================

def extraer_formato_2276(ano: int) -> list[dict]:
    """Rentas de trabajo, pensiones y retenciones practicadas.

    Obligatorio para cualquier empleador. Fuente: las nóminas emitidas del año.
    """
    conn = db.get_connection()
    try:
        filas = dbutil.query(
            conn,
            """
            SELECT n.consecutivo, n.prefijo, n.periodo_inicio, n.periodo_fin,
                   e.documento, e.tipo_documento, e.nombres, e.apellidos,
                   n.total_devengado, n.total_deducciones, n.neto_pagar
            FROM nominas n
            JOIN empleados e ON e.id = n.empleado_id
            WHERE n.periodo_fin LIKE ? OR n.periodo_inicio LIKE ?
            """,
            (f"{ano}%", f"{ano}%"),
        ).fetchall()
    finally:
        conn.close()

    registros = []
    for f in filas:
        numero = f["consecutivo"] or ""
        if f["prefijo"] and not str(numero).startswith(str(f["prefijo"])):
            numero = f"{f['prefijo']}{numero}"
        nombre_completo = f"{f['nombres'] or ''} / {f['apellidos'] or ''}".strip(" /")
        apellidos, nombres = _partes_nombre(nombre_completo)
        registros.append({
            "tipo_documento": tipo_documento_por_nit(f["documento"], f["tipo_documento"]),
            "documento": f["documento"],
            "apellidos": apellidos,
            "nombres": nombres,
            "periodo_desde": f["periodo_inicio"],
            "periodo_hasta": f["periodo_fin"],
            "consecutivo": numero,
            "devengado": _q2(f["total_devengado"]),
            "deducciones": _q2(f["total_deducciones"]),
            "neto": _q2(f["neto_pagar"]),
        })
    return registros


def registros_2276(ano: int) -> list[dict]:
    filas = []
    for i, r in enumerate(extraer_formato_2276(ano), start=1):
        filas.append({
            "valores": [
                str(i).zfill(10),
                r["tipo_documento"],
                r["documento"],
                r["apellidos"],
                r["nombres"],
                r["periodo_desde"].replace("-", ""),
                r["periodo_hasta"].replace("-", ""),
                r["consecutivo"],
                _d(r["devengado"]),
                _d(r["deducciones"]),
                _d(r["neto"]),
            ],
        })
    return filas


# ============================================================
# API pública
# ============================================================

FORMATOS = {
    "1001": registros_1001,
    "1003": lambda ano: registros_1003(ano),
    "1007": lambda ano: registros_1007(ano),
    "2275": lambda ano: registros_2275(ano),
    "2276": lambda ano: registros_2276(ano),
}


def generar_archivo(formato: str, anio: int, nit: str, mes: int = 1,
                    version: int = 1) -> str:
    """Devuelve el contenido del archivo exógeno listo para radicar."""
    if formato not in FORMATOS:
        raise ErrorExogena(
            f"Formato no soportado: {formato!r}. Disponibles: {', '.join(sorted(FORMATOS))}"
        )
    registros = FORMATOS[formato](anio)
    return linea(formato, registros, nit, anio, mes, version)


def nombre_archivo_para(formato: str, anio: int, nit: str, mes: int = 1,
                        version: int = 1) -> str:
    return nombre_archivo(formato, nit, anio, mes, version)


def generar_todos(anio: int, nit: str, mes: int = 1) -> dict[str, dict]:
    """Genera los cinco formatos con su nombre de archivo y contenido."""
    salida = {}
    for formato in FORMATOS:
        contenido = generar_archivo(formato, anio, nit, mes)
        salida[formato] = {
            "nombre": nombre_archivo(formato, nit, anio, mes),
            "contenido": contenido,
            "lineas": len(contenido.strip().splitlines()) - 1,
        }
    return salida


# ============================================================
# Certificado de retención en la fuente
# ============================================================

def generar_certificado_retencion(tercero_nit: str, ano: int) -> dict:
    """Certificado de retención en la fuente del año ``ano`` para un tercero.

    Art. 378-1 E.T.: debe expedirse y entregarse entre el 1 de febrero y el
    31 de marzo del año siguiente.
    """
    conn = db.get_connection()
    try:
        empresa = dbutil.query(
            conn, "SELECT nit, razon_social, dv FROM empresas ORDER BY id LIMIT 1"
        ).fetchone()
        info = _buscar_tercero(tercero_nit)
        filas = dbutil.query(
            conn,
            """
            SELECT m.cuenta_codigo, m.debito, m.credito, a.fecha, m.concepto
            FROM movimientos_contables m
            JOIN asientos_contables a ON a.id = m.asiento_id
            WHERE a.fecha LIKE ? AND m.tercero_nit = ?
              AND m.credito <> '0.00'
            """,
            (f"{ano}%", tercero_nit),
        ).fetchall()
    finally:
        conn.close()

    conceptos = []
    total = Decimal("0.00")
    for f in filas:
        cuenta = f["cuenta_codigo"]
        if cuenta not in CUENTAS_RETEFUENTE_RENTA:
            continue
        valor = _q2(f["credito"])
        total += valor
        conceptos.append({
            "cuenta": cuenta,
            "concepto": f["concepto"] or "Retención en la fuente",
            "base": _q2(f["debito"]),
            "valor": valor,
            "fecha": f["fecha"],
        })

    apellidos, nombres = _partes_nombre(info.get("razon_social", ""))
    return {
        "anio": ano,
        "nit_tercero": tercero_nit,
        "tipo_documento": tipo_documento_por_nit(tercero_nit, info.get("tipo_documento")),
        "nombre_tercero": info.get("razon_social", ""),
        "apellidos": apellidos,
        "nombres": nombres,
        "direccion": info.get("direccion", ""),
        "municipio": info.get("municipio", ""),
        "emisor_nit": empresa["nit"] if empresa else "",
        "emisor_nombre": empresa["razon_social"] if empresa else "",
        "conceptos": conceptos,
        "total_retenido": total,
        "periodo_entrega": f"{ano + 1}-02-01 a {ano + 1}-03-31",
    }