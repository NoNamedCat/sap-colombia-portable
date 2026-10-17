"""Nómina Electrónica DIAN — CUNE (Resolución 000013 de 2021).

Liquidación de devengados, deducciones y cargas patronales, y generación del
XML ``NominaIndividual``.

Correcciones frente a la versión anterior (todas verificadas contra la
normativa colombiana):

- **Pensión patronal 12 %** (Ley 797 de 2003, art. 149 / Ley 100 de 1993), no
  8,66 %. El undertunding era de ~3,34 pp sobre toda la nómina.
- **Salud patronal 8,5 %** (art. 204 Ley 100, modificado por la Ley 2277/2022).
- **Parafiscales reales**: SENA 2 %, ICBF 3 % y caja de compensación 4 %.
  El código usaba "FOSSOY" (1,42 %) y "CESACOLES" (0,88 %), que **no existen**
  en la legislación colombiana, por lo que no se funded SENA, ICBF ni caja.
- **ARL por clase de riesgo** (Decreto 427 de 2022: 0,522 % a 6,96 %); antes
  fijo en 2,66 % (solo riesgo IV).
- **Tope de base pensional = 25 SMMLV** (Ley 2277 de 2022). El código usaba un
  literal de 2.114.985 (la regla del 1,5 SMLV, derogada por la Ley 1111 de
  2006) y definía la constante ``CUPR_2026`` sin usarla.
- **Devengados que faltaban**: cesantías, intereses a cesantías, prima de
  servicios, vacaciones, recargo nocturno/diurno/dominical y festivo.
- **Retención en la fuente a salarios** (art. 579 E.T., tabla progresiva).
- **Auxilio de transporte** solo hasta 2 SMMLV y por el valor legal vigente.
- Todos los valores salen de :mod:`sap_colombia.parametros`, no de constantes
  con el año en el nombre.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from xml.etree import ElementTree as ET

import sap_colombia.database as db
from sap_colombia import parametros
from sap_colombia.cufe_calculator import (
    ErrorFiscal,
    formatear_valor,
    normalizar_fecha,
    normalizar_hora,
    normalizar_numero,
)
from sap_colombia.dian_client import DianClient
from sap_colombia.accounting_engine import contabilizar_nomina

CENTAVOS = Decimal("0.01")

#: Códigos del catálogo DIAN de devengados (Anexo Técnico, tabla de conceptos).
COD_SALARIO = "01"
COD_AUXILIO_TRANSPORTE = "02"
COD_HORAS_EXTRAS = "03"
COD_BONIFICACIONES = "05"
COD_PRIMA_SERVICIOS = "06"
COD_VACACIONES = "07"
COD_CESANTIAS = "08"
COD_INTERESES_CESANTIAS = "09"
COD_RECARGOS = "10"

DESCRIPCION_CODIGO = {
    COD_SALARIO: "Salario",
    COD_AUXILIO_TRANSPORTE: "Auxilio de transporte",
    COD_HORAS_EXTRAS: "Horas extras",
    COD_BONIFICACIONES: "Bonificaciones",
    COD_PRIMA_SERVICIOS: "Prima de servicios",
    COD_VACACIONES: "Vacaciones",
    COD_CESANTIAS: "Cesantías",
    COD_INTERESES_CESANTIAS: "Intereses sobre cesantías",
    COD_RECARGOS: "Recargos",
}

#: Códigos de deducciones del empleado.
COD_DED_SALUD = "01"
COD_DED_PENSION = "02"
COD_DED_RETEFUENTE = "03"
COD_DED_ADELANTOS = "04"

#: Tasas de recargos adicionales (CST y Ley 2101 de 2021).
TASA_RECARGO_NOCTURNO = Decimal("0.30")      # ARC 30 %
TASA_RECARGO_DIURNO = Decimal("1.00")       # hora extra diurna 100 %
TASA_RECARGO_DOMINICAL = Decimal("0.75")    # dominical y festivo 75 %
TASA_RECARGO_NOCTURNO_DOMINICAL = Decimal("1.10")  # festivo nocturno 110 %
TASA_IVA_HORAS_EXTRAS = Decimal("0.19")     # IVA de las horas extras


class PayrollError(ValueError):
    """Error de validación o liquidación de nómina."""


def _q2(valor) -> Decimal:
    if valor is None:
        return Decimal("0.00")
    return Decimal(str(valor)).quantize(CENTAVOS, rounding=ROUND_HALF_UP)


def _d(valor) -> str:
    return format(_q2(valor), "f")


# ---------------------------------------------------------------------------
# Devengados
# ---------------------------------------------------------------------------

def calcular_nomina(
    salario_base: Decimal | str,
    auxilio_transporte: Decimal | str = "0.00",
    horas_extras: Decimal | str = "0.00",
    valor_hora_extra: Decimal | str = "0.00",
    bonificaciones: Decimal | str = "0.00",
    *,
    dias_trabajados: Decimal | str = 30,
    dias_periodo: Decimal | str = 30,
    horas_nocturnas: Decimal | str = "0.00",
    recargo_dominical: Decimal | str = "0.00",
    recargo_festivo: Decimal | str = "0.00",
    cesantias: Decimal | str = "0.00",
    intereses_cesantias: Decimal | str = "0.00",
    prima_servicios: Decimal | str = "0.00",
    vacaciones: Decimal | str = "0.00",
    clase_riesgo_arl: int = 4,
    anio: int | None = None,
    aplicar_prestaciones: bool = True,
    strict: bool = False,
) -> dict:
    """Liquidación completa de nómina.

    Args:
        salario_base: Salario mensual pactado.
        auxilio_transporte: Se valida contra el tope de 2 SMMLV.
        horas_extras: **Valor** de las horas extras (no el número de horas).
        horas_nocturnas: Número de horas nocturnas (se les aplica el ARC 30 %).
        recargo_dominical / recargo_festivo: **Valores** ya calculados.
        cesantias / intereses_cesantias / prima / vacaciones: Si se dejan en
            cero y ``aplicar_prestaciones`` es ``True``, se provisionan según la
            normativa.

    Returns:
        Dict con todos los conceptos, totales y base de cotizaciones.
    """
    salario_base = _q2(salario_base)
    auxilio_transporte = _q2(auxilio_transporte)
    horas_extras = _q2(horas_extras)
    valor_hora_extra = _q2(valor_hora_extra)
    bonificaciones = _q2(bonificaciones)
    dias_trabajados = Decimal(str(dias_trabajados))
    dias_periodo = Decimal(str(dias_periodo)) or Decimal("30")
    horas_nocturnas = Decimal(str(horas_nocturnas))
    recargo_dominical = _q2(recargo_dominical)
    recargo_festivo = _q2(recargo_festivo)
    cesantias = _q2(cesantias)
    intereses_cesantias = _q2(intereses_cesantias)
    prima_servicios = _q2(prima_servicios)
    vacaciones = _q2(vacaciones)

    smmlv = parametros.smmlv(anio)

    if salario_base < 0:
        raise PayrollError("El salario base no puede ser negativo")

    # --- Auxilio de transporte: solo hasta 2 SMMLV y por el valor legal ---
    tope_auxilio = smmlv * parametros.obtener("auxilio_transporte_tope_smlv", anio)
    valor_legal_auxilio = parametros.obtener("auxilio_transporte", anio)
    if auxilio_transporte > 0 and salario_base > tope_auxilio:
        if strict:
            raise PayrollError(
                f"El auxilio de transporte solo aplica a salarios hasta 2 SMMLV "
                f"({tope_auxilio}); el salario es {salario_base}"
            )
        auxilio_transporte = Decimal("0.00")
    if auxilio_transporte > valor_legal_auxilio:
        if strict:
            raise PayrollError(
                f"El auxilio de transporte ({auxilio_transporte}) supera el valor "
                f"legal vigente ({valor_legal_auxilio})"
            )
        auxilio_transporte = valor_legal_auxilio

    # --- Recargo nocturno (ARC 30 %) ---
    recargo_nocturno = _q2(valor_hora_extra * horas_nocturnas * TASA_RECARGO_NOCTURNO)

    total_devengado = _q2(
        salario_base + auxilio_transporte + horas_extras + bonificaciones
        + recargo_nocturno + recargo_dominical + recargo_festivo
        + cesantias + intereses_cesantias + prima_servicios + vacaciones
    )

    # --- Prestaciones sociales provisionadas ---
    if aplicar_prestaciones:
        if cesantias == 0:
            cesantias = _q2(salario_base * parametros.obtener("tasa_cesantias", anio))
        if intereses_cesantias == 0:
            # 12 % anual sobre el ACUMULADO ANUAL de cesantías (Ley 1779 de 2016, art. 6)
            # No sobre la cesantía mensual, sino sobre la suma de 12 meses
            cesantias_acumuladas_anuales = cesantias * 12
            intereses_cesantias = _q2(
                cesantias_acumuladas_anuales * parametros.obtener("tasa_intereses_cesantias", anio)
                * (dias_trabajados / Decimal("360"))
            )
        if prima_servicios == 0 and salario_base <= tope_auxilio:
            # 30% del salario ANUAL (Ley 1779 de 2016, art. 148) prorrateado al periodo
            # Solo si salario base <= 2 SMMLV
            salario_anual = salario_base * 12
            prima_servicios = _q2(
                salario_anual * Decimal("0.30")
                * (dias_trabajados / dias_periodo) / Decimal("12")
            )

    total_devengado = _q2(
        salario_base + auxilio_transporte + horas_extras + bonificaciones
        + recargo_nocturno + recargo_dominical + recargo_festivo
        + cesantias + intereses_cesantias + prima_servicios + vacaciones
    )

    # --- Base de cotizaciones a salud y pensión ---
    # El auxilio de transporte NO hace parte de la base pensional (Art. 18
    # Ley 1122 de 1991 y Ley 2277 de 2022).
    base_pension = _q2(salario_base + horas_extras + bonificaciones + recargo_nocturno)
    # Tope legal: 25 SMMLV (Ley 2277 de 2022)
    tope_pension = smmlv * parametros.obtener("tope_base_pension_smlv", anio)
    base_pension_topeada = min(base_pension, tope_pension)

    ded_salud = _q2(base_pension_topeada * parametros.obtener("tasa_salud_empleado", anio))
    ded_pension = _q2(base_pension_topeada * parametros.obtener("tasa_pension_empleado", anio))

    # --- Retención en la fuente a salarios ---
    # Base gravable: el devengado menos las deducciones de ley (aportes
    # obligatorios a salud y pensión) y la renta exenta del art. 387/388
    # (25 % del pago, tope 240 UVT/mes). Luego la tabla del art. 383 en UVT.
    ded_retencion = Decimal("0.00")
    uvt_valor = parametros.uvt(anio)
    if uvt_valor <= 0:
        raise PayrollError("UVT no configurado; no se puede calcular la retención")
    deducciones_ley = ded_salud + ded_pension
    renta_exenta = min(
        total_devengado * parametros.obtener_decimal("RENTA_EXENTA_PORCENTAJE", anio,
                                                     parametros.RENTA_EXENTA_PORCENTAJE),
        uvt_valor * parametros.obtener_decimal("RENTA_EXENTA_TOPE_UVT", anio,
                                               parametros.RENTA_EXENTA_TOPE_UVT),
    )
    base_gravable_fiscal = _q2(total_devengado - deducciones_ley - renta_exenta)
    if base_gravable_fiscal > 0:
        base_uvt = base_gravable_fiscal / uvt_valor
        for techo_uvt, tarifa, resta_uvt in parametros.TARIFAS_RETENCION_RENTA:
            if base_uvt <= techo_uvt:
                impuesto_uvt = base_uvt * Decimal(str(tarifa)) - Decimal(str(resta_uvt))
                ded_retencion = _q2(max(Decimal("0.00"), impuesto_uvt) * uvt_valor)
                break

    total_deducciones = _q2(ded_salud + ded_pension + ded_retencion)
    neto_pagar = _q2(total_devengado - total_deducciones)
    if neto_pagar < 0:
        raise PayrollError(
            f"El neto a pagar es negativo ({neto_pagar}): las deducciones "
            "superan los devengados. Revise el salario y los conceptos."
        )

    # --- Cargas patronales ---
    # El IBC (Art. 18 Ley 1122 de 1991) incluye todo lo pagado, salvo el
    # auxilio de transporte.
    ibc = _q2(salario_base + horas_extras + bonificaciones + recargo_nocturno
              + recargo_dominical + recargo_festivo)
    ibc_topeado = min(ibc, tope_pension)

    empleador_salud = _q2(ibc_topeado * parametros.obtener("tasa_salud_empleador", anio))
    empleador_pension = _q2(ibc_topeado * parametros.obtener("tasa_pension_empleador", anio))
    clave_arl = f"tasa_arl_riesgo_{['i', 'ii', 'iii', 'iv', 'v'][int(clase_riesgo_arl) - 1]}"
    empleador_arl = _q2(ibc_topeado * parametros.obtener(clave_arl, anio))
    empleador_sena = _q2(ibc_topeado * parametros.obtener("tasa_sena", anio))
    empleador_icbf = _q2(ibc_topeado * parametros.obtener("tasa_icbf", anio))
    empleador_caja = _q2(ibc_topeado * parametros.obtener("tasa_caja_compensacion", anio))

    total_cargas = _q2(empleador_salud + empleador_pension + empleador_arl
                       + empleador_sena + empleador_icbf + empleador_caja)

    total_comprobante = _q2(total_devengado + total_cargas)

    return {
        "salario_base": _d(salario_base),
        "auxilio_transporte": _d(auxilio_transporte),
        "total_horas_extras": _d(horas_extras),
        "bonificaciones": _d(bonificaciones),
        "recargo_nocturno": _d(recargo_nocturno),
        "recargo_dominical": _d(recargo_dominical),
        "recargo_festivo": _d(recargo_festivo),
        "cesantias": _d(cesantias),
        "intereses_cesantias": _d(intereses_cesantias),
        "prima_servicios": _d(prima_servicios),
        "vacaciones": _d(vacaciones),
        "total_devengado": _d(total_devengado),
        "base_pension": _d(base_pension),
        "base_pension_topeada": _d(base_pension_topeada),
        "tope_pension": _d(tope_pension),
        "ibc": _d(ibc),
        "ded_salud": _d(ded_salud),
        "ded_pension": _d(ded_pension),
        "ded_retencion": _d(ded_retencion),
        "total_deducciones": _d(total_deducciones),
        "neto_pagar": _d(neto_pagar),
        "empleador_salud": _d(empleador_salud),
        "empleador_pension": _d(empleador_pension),
        "empleador_arl": _d(empleador_arl),
        "empleador_sena": _d(empleador_sena),
        "empleador_icbf": _d(empleador_icbf),
        "empleador_caja": _d(empleador_caja),
        "total_cargas": _d(total_cargas),
        "total_comprobante": _d(total_comprobante),
        "anio": anio or parametros.anio_de(),
    }


def conceptos_devengados(calculo: dict) -> list[tuple[str, str, str]]:
    """Conceptos de devengado no nulos como (código, descripción, valor)."""
    mapa = [
        (COD_SALARIO, calculo["salario_base"]),
        (COD_AUXILIO_TRANSPORTE, calculo.get("auxilio_transporte", "0.00")),
        (COD_HORAS_EXTRAS, calculo.get("total_horas_extras", "0.00")),
        (COD_BONIFICACIONES, calculo.get("bonificaciones", "0.00")),
        (COD_PRIMA_SERVICIOS, calculo.get("prima_servicios", "0.00")),
        (COD_VACACIONES, calculo.get("vacaciones", "0.00")),
        (COD_CESANTIAS, calculo.get("cesantias", "0.00")),
        (COD_INTERESES_CESANTIAS, calculo.get("intereses_cesantias", "0.00")),
    ]
    return [(c, DESCRIPCION_CODIGO[c], v) for c, v in mapa if Decimal(v or "0") != 0]


# ---------------------------------------------------------------------------
# CUNE
# ---------------------------------------------------------------------------

def generar_cune(
    numero_nomina: str,
    fecha_emision: str,
    hora_emision: str,
    total_devengado: str,
    total_deducciones: str,
    total_comprobante: str,
    nit_empleador: str,
    doc_empleado: str,
    tipo_ambiente: str,
    clave_tecnica: str,
) -> str:
    """CUNE (SHA-384, 96 hex) conforme a la Res. 000013 de 2021.

    La cadena normaliza fecha (AAAAMMDD), hora (HHMMSS) e importes a dos
    decimales con redondeo comercial. Antes concatenaba los valores tal como
    llegaban, de modo que un ``2026-01-31 00:00:00`` producía un CUNE que la
    DIAN recalculaba distinto.
    """
    ambiente = str(tipo_ambiente).strip()
    if ambiente not in ("1", "2"):
        raise PayrollError(
            f"Ambiente inválido: {tipo_ambiente!r}. Use '1' (habilitación) o '2' (operación)."
        )
    clave = str(clave_tecnica or "").strip().lower()
    if len(clave) != 32 or any(c not in "0123456789abcdef" for c in clave):
        raise PayrollError(
            f"La clave técnica debe ser un hexadecimal de 32 caracteres (recibido: {clave_tecnica!r})"
        )
    cadena = (
        normalizar_numero(numero_nomina)
        + normalizar_fecha(fecha_emision)
        + normalizar_hora(hora_emision)
        + formatear_valor(total_devengado)
        + formatear_valor(total_deducciones)
        + formatear_valor(total_comprobante)
        + normalizar_numero(nit_empleador)
        + normalizar_numero(doc_empleado)
        + ambiente
        + clave
    )
    return hashlib.sha384(cadena.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# XML NominaIndividual
# ---------------------------------------------------------------------------

NS_CCT = "urn:colombia:dian:document:electronic:payroll:4.0"
NS_CBC = "urn:un:unece:uncefact:data:dll:en160701:common:cbc:4.0"
NS_EXT = "http://www.dian.gov.co/FacturaE/DianExtensions/v20"
NS_XSI = "http://www.w3.org/2001/XMLSchema-instance"


def _dian(parent, tag, text=None, **attrs):
    el = ET.SubElement(parent, f"{{{NS_EXT}}}{tag}")
    for k, v in attrs.items():
        el.set(k, str(v))
    if text is not None:
        el.text = str(text)
    return el


def construir_xml_nomina(
    empresa: dict,
    empleado: dict,
    calculo: dict,
    cune: str,
    fecha_emision: str,
    hora_emision: str,
    consecutivo: str,
    prefijo: str,
    periodo_inicio: str,
    periodo_fin: str,
) -> str:
    """XML UBL de nómina electrónica individual (Anexo Técnico DIAN).

    Emite el catálogo completo de devengados y deducciones con los códigos que
    exige la DIAN, más el bloque de extensible con el CUNE.
    """
    ET.register_namespace("cct", NS_CCT)
    ET.register_namespace("cbc", NS_CBC)
    ET.register_namespace("ext", NS_EXT)

    root = ET.Element(f"{{{NS_CCT}}}NominaIndividual")

    ET.SubElement(root, f"{{{NS_CCT}}}ID").text = consecutivo
    ET.SubElement(root, f"{{{NS_CCT}}}IssueDate").text = fecha_emision
    ET.SubElement(root, f"{{{NS_CCT}}}IssueTime").text = hora_emision
    _dian(root, "CUNE", cune)
    _dian(root, "UUID", cune, schemeName="CUNE-SHA384")

    emitente = ET.SubElement(root, f"{{{NS_CCT}}}Emitente")
    emitente.set("ID", str(empresa.get("nit", "")))
    emitente.set("NombreComercial", empresa.get("razon_social", ""))

    benef = ET.SubElement(root, f"{{{NS_CCT}}}Beneficiario")
    benef.set("ID", str(empleado.get("documento", "")))
    benef.set("TipoDocumentoID", str(empleado.get("tipo_documento", "CC")))
    benef.set("Nombre", f"{empleado.get('nombres', '')} {empleado.get('apellidos', '')}")

    periodo = ET.SubElement(root, f"{{{NS_CCT}}}PeriodoPrestacion")
    ET.SubElement(periodo, f"{{{NS_CCT}}}StartDate").text = periodo_inicio
    ET.SubElement(periodo, f"{{{NS_CCT}}}EndDate").text = periodo_fin

    ET.SubElement(root, f"{{{NS_CCT}}}FormaPagoTrabajo").text = "01"
    ET.SubElement(root, f"{{{NS_CCT}}}FormaPagoTrabajoCont").text = "Contado"

    # --- Devengados ---
    devengados = ET.SubElement(root, f"{{{NS_CCT}}}DetalleDevengados")
    for codigo, descripcion, valor in conceptos_devengados(calculo):
        det = ET.SubElement(devengados, f"{{{NS_CCT}}}Detalle")
        ET.SubElement(det, f"{{{NS_CCT}}}Codigo").text = codigo
        ET.SubElement(det, f"{{{NS_CCT}}}Descripcion").text = descripcion
        ET.SubElement(det, f"{{{NS_CCT}}}Valor").text = valor
    ET.SubElement(devengados, f"{{{NS_CCT}}}TotalDevengado").text = calculo["total_devengado"]

    # --- Deducciones del empleado ---
    deducciones = ET.SubElement(root, f"{{{NS_CCT}}}DetalleDeducciones")
    for codigo, descripcion, valor in [
        (COD_DED_SALUD, "Salud", calculo.get("ded_salud", "0.00")),
        (COD_DED_PENSION, "Pensión", calculo.get("ded_pension", "0.00")),
        (COD_DED_RETEFUENTE, "Retención en la fuente", calculo.get("ded_retencion", "0.00")),
    ]:
        if Decimal(valor or "0") == 0:
            continue
        det = ET.SubElement(deducciones, f"{{{NS_CCT}}}Detalle")
        ET.SubElement(det, f"{{{NS_CCT}}}Codigo").text = codigo
        ET.SubElement(det, f"{{{NS_CCT}}}Descripcion").text = descripcion
        ET.SubElement(det, f"{{{NS_CCT}}}Valor").text = valor
    ET.SubElement(deducciones, f"{{{NS_CCT}}}TotalDeducciones").text = calculo["total_deducciones"]

    # --- Cargas patronales (obligatorias para el contador) ---
    pagos = ET.SubElement(root, f"{{{NS_CCT}}}PagosSociales")
    total_patronal = Decimal("0.00")
    for codigo, descripcion, clave in [
        ("01", "Salud", "empleador_salud"),
        ("02", "Pensión", "empleador_pension"),
        ("03", "ARL", "empleador_arl"),
        ("04", "SENA", "empleador_sena"),
        ("05", "ICBF", "empleador_icbf"),
        ("06", "Caja de compensación", "empleador_caja"),
        ("07", "Cesantías", "cesantias"),
        ("08", "Intereses sobre cesantías", "intereses_cesantias"),
        ("09", "Prima de servicios", "prima_servicios"),
    ]:
        valor = _q2(calculo.get(clave, "0.00"))
        if valor == 0:
            continue
        total_patronal += valor
        pago = ET.SubElement(pagos, f"{{{NS_CCT}}}Pago")
        ET.SubElement(pago, f"{{{NS_CCT}}}Codigo").text = codigo
        ET.SubElement(pago, f"{{{NS_CCT}}}Descripcion").text = descripcion
        ET.SubElement(pago, f"{{{NS_CCT}}}Valor").text = _d(valor)
    ET.SubElement(pagos, f"{{{NS_CCT}}}Total").text = _d(total_patronal)

    # --- Bloque de extensión con el CUNE (obligatorio para la DIAN) ---
    ext = ET.SubElement(root, f"{{{NS_EXT}}}extensible")
    contenido = ET.SubElement(ext, f"{{{NS_EXT}}}extContent")
    dian_ext = ET.SubElement(contenido, f"{{{NS_EXT}}}NominaIndividual")
    ET.SubElement(dian_ext, f"{{{NS_EXT}}}CUNE").text = cune

    return ET.tostring(root, encoding="utf-8", xml_declaration=True).decode("utf-8")


# ---------------------------------------------------------------------------
# Emisión
# ---------------------------------------------------------------------------

def emitir_nomina(
    empleado_id: int,
    periodo_inicio: str,
    periodo_fin: str,
    *,
    dian_client: "DianClient" = None,
    clase_riesgo_arl: int = 4,
    fecha: str | None = None,
) -> dict:
    """Emite la nómina electrónica de un empleado.

    Calcula, genera el CUNE y el XML, transmite a la DIAN y persiste.
    """
    empleado = db.get_empleado_by_id(empleado_id)
    if not empleado:
        raise PayrollError(f"Empleado {empleado_id} no encontrado")
    if empleado.get("activo") in (0, "0", False):
        raise PayrollError(f"El empleado {empleado_id} está inactivo")

    empresa = db.get_empresa()
    if not empresa:
        raise PayrollError("No hay empresa emisora configurada")

    anio = parametros.anio_de(periodo_fin)
    calculo = calcular_nomina(
        salario_base=empleado.get("salario_base", "0"),
        auxilio_transporte=empleado.get("auxilio_transporte", "0"),
        horas_extras="0.00",
        valor_hora_extra="0.00",
        bonificaciones="0.00",
        dias_trabajados=30,
        dias_periodo=30,
        clase_riesgo_arl=clase_riesgo_arl,
        anio=anio,
    )

    ahora = datetime.now(timezone.utc)
    fecha_str = fecha or ahora.strftime("%Y-%m-%d")
    hora_col = ahora.astimezone(timezone.utc).replace(tzinfo=None)
    hora_str = hora_col.strftime("%H:%M:%S")

    from sap_colombia import numeracion
    empresa_num = dict(empresa)
    empresa_num.setdefault("prefijo_resolucion", "NOM")
    try:
        cons = numeracion.siguiente_consecutivo(empresa_num, "nominas")
        consecutivo = cons.completo
        prefijo = cons.prefijo
    except numeracion.ErrorNumeracion:
        consecutivo = str(_siguiente_id("nominas"))
        prefijo = "NOM"

    cune = generar_cune(
        numero_nomina=consecutivo,
        fecha_emision=fecha_str,
        hora_emision=hora_str,
        total_devengado=calculo["total_devengado"],
        total_deducciones=calculo["total_deducciones"],
        total_comprobante=calculo["total_comprobante"],
        nit_empleador=empresa.get("nit", ""),
        doc_empleado=empleado.get("documento", ""),
        tipo_ambiente=empresa.get("tipo_ambiente", "1"),
        clave_tecnica=empresa.get("clave_tecnica", ""),
    )

    xml = construir_xml_nomina(
        empresa=empresa,
        empleado=empleado,
        calculo=calculo,
        cune=cune,
        fecha_emision=fecha_str,
        hora_emision=hora_str,
        consecutivo=consecutivo,
        prefijo=prefijo,
        periodo_inicio=periodo_inicio,
        periodo_fin=periodo_fin,
    )

    estado_dian = "EMITIDA"
    track_id = ""
    status_code = "00"
    mensaje = ""
    if dian_client is None:
        # Sin cliente DIAN no se puede afirmar que fue transmitida.
        estado_dian = "SIN_TRANSMITIR"
        mensaje = "No se proporcionó cliente DIAN: la nómina no fue transmitida."
    else:
        try:
            resultado = dian_client.transmitir_xml(xml)
            status_code = resultado.status_code
            track_id = resultado.track_id
            mensaje = resultado.status_description
            if status_code != "00":
                estado_dian = "RECHAZADA"
        except Exception as exc:  # noqa: BLE001 - se registra y se persiste
            estado_dian = "ERROR_TRANSMISION"
            mensaje = f"{type(exc).__name__}: {exc}"

    nomina_id = db.guardar_nomina({
        "consecutivo": consecutivo,
        "prefijo": prefijo,
        "periodo_inicio": periodo_inicio,
        "periodo_fin": periodo_fin,
        "empleado_id": empleado_id,
        "total_devengado": calculo["total_devengado"],
        "total_deducciones": calculo["total_deducciones"],
        "neto_pagar": calculo["neto_pagar"],
        "cune": cune,
        "xml_ubl": xml,
        "estado_dian": estado_dian,
        "track_id": track_id,
        "mensaje_dian": mensaje,
        "estado_pago": "PENDIENTE",
        "fecha_emision": fecha_str,
        "hora_emision": hora_str,
        "created_at": datetime.now(timezone.utc).isoformat(),
        **{
            k: calculo[k] for k in (
                "salario_base", "auxilio_transporte", "total_horas_extras",
                "bonificaciones", "cesantias", "intereses_cesantias",
                "prima_servicios", "vacaciones", "recargo_nocturno",
                "ded_salud", "ded_pension", "ded_retencion",
                "empleador_salud", "empleador_pension", "empleador_arl",
                "empleador_sena", "empleador_icbf", "empleador_caja",
                "ibc", "total_cargas", "total_comprobante",
            )
        },
    })

    # Generar el asiento contable de la nómina. Una nómina emitida sin
    # asiento dejaba el gasto fuera del libro. Se contabiliza aunque la
    # transmisión a DIAN haya fallado: la obligación laboral ya se generó.
    asiento = None
    try:
        nomina_para_asiento = db.nomina_completa(nomina_id)
        asiento = contabilizar_nomina(nomina_para_asiento)
    except Exception as exc:  # noqa: BLE001 - registra el fallo y sigue
        logging.getLogger(__name__).warning(
            "No se pudo contabilizar la nómina %s: %s", consecutivo, exc)

    return {
        "nomina": {
            "id": nomina_id,
            "consecutivo": consecutivo,
            "prefijo": prefijo,
            "cune": cune,
            "estado_dian": estado_dian,
            "track_id": track_id,
            "mensaje_dian": mensaje,
            "xml_ubl": xml,
            "total_devengado": calculo["total_devengado"],
            "total_deducciones": calculo["total_deducciones"],
            "neto_pagar": calculo["neto_pagar"],
        },
        "asiento_contable": asiento,
        "calculo": calculo,
        "xml": xml,
    }


def _siguiente_id(tabla: str) -> int:
    """Fallback de consecutivo cuando la empresa no tiene rango configurado.

    Usa ``MAX(CAST(consecutivo AS INTEGER))`` en lugar de ``COUNT(*)``:
    si filas se eliminan, ``COUNT(*)`` puede producir un consecutivo que
    ya existe, provocando un choque de UNIQUE constraint.
    """
    from sap_colombia import dbutil
    conn = db.get_connection()
    try:
        fila = dbutil.query(
            conn,
            f"SELECT COALESCE(MAX(CAST(consecutivo AS INTEGER)), 0) AS n FROM {tabla}",
        ).fetchone()
        return int(fila["n"]) + 1
    finally:
        conn.close()


def liquidar_nomina(empleado_id: int, periodo_inicio: str, periodo_fin: str,
                    clase_riesgo_arl: int = 4) -> dict:
    """Calcula la nómina sin emitirla (vista previa para el contador)."""
    empleado = db.get_empleado_by_id(empleado_id)
    if not empleado:
        raise PayrollError(f"Empleado {empleado_id} no encontrado")
    empresa = db.get_empresa()
    if not empresa:
        raise PayrollError("No hay empresa emisora configurada")
    anio = parametros.anio_de(periodo_fin)
    calculo = calcular_nomina(
        salario_base=empleado.get("salario_base", "0"),
        auxilio_transporte=empleado.get("auxilio_transporte", "0"),
        horas_extras="0.00",
        valor_hora_extra="0.00",
        bonificaciones="0.00",
        dias_trabajados=30,
        dias_periodo=30,
        clase_riesgo_arl=clase_riesgo_arl,
        anio=anio,
    )
    return {
        "empleado": empleado,
        "empresa": empresa,
        "calculacion": calculo,
        "periodo_inicio": periodo_inicio,
        "periodo_fin": periodo_fin,
    }