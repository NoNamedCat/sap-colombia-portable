"""Cálculo del CUFE/CUDE y de la cadena QR para Factura Electrónica DIAN.

El CUFE es el SHA-384 de la concatenación, **sin separadores**, de los campos
de control que define el «Anexo Técnico» de la factura electrónica de venta
(Res. DIAN 000042 de 2020, actualizado por la Res. 000165 de 2023 y el Anexo
Técnico 1.9). La cadena QR es un texto de 10 campos separados por ``;``.

Puntos donde la implementación anterior se apartaba de la norma y que aquí se
corrigen:

1. **Número de campos.** La especificación concatena 22 campos, entre ellos
   los bloques de impuestos T04..T13, los totales en moneda extranjera y
   nacional (T14/T15) y el total a pagar (T16). Antes se concatenaban 14.
2. **Número de factura.** Es el *número* de 8 dígitos, no el prefijo+consecutivo.
   ``zfill(8)`` sobre un identificador que ya traía prefijo no hacía nada útil.
3. **Redondeo.** La guía exige redondeo comercial (half-up) a dos decimales.
   ``format(Decimal, ".2f")`` usa el modo por defecto del contexto, que es
   half-even.
4. **QR.** La fecha y la hora son campos separados; se enviaban concatenadas
   (``20261013193908``), dejando 9 campos en lugar de 10.
5. **Validación.** Cualquier entrada mal formada entraba al hash en silencio.
"""

from __future__ import annotations

import hashlib
import re
from decimal import Decimal, ROUND_HALF_UP

# --------------------------------------------------------------------------
# Códigos de impuesto del catálogo DIAN usados en los slots del CUFE
# --------------------------------------------------------------------------

#: Slots de impuesto obligatorios en la cadena del CUFE, en orden T04..T07.
#: Cada slot es (código, valor); si el valor es 0, el código va en blanco (3
#: espacios) según la guía técnica.
SLOTS_IMPUESTO_ORDEN = ("T04", "T05", "T06", "T07")

CODIGO_T04 = "01"  # Ingresos excluidos
CODIGO_T05 = "02"  # IVA 19%
CODIGO_T06 = "03"  # IVA 5%
CODIGO_T07 = "04"  # IVA 0% / no gravado
CODIGO_VACIO = "   "

#: Mapa desde las tarifas internas del motor tributario a los slots del CUFE.
TARIFA_A_SLOT = {
    "IVA_19": CODIGO_T05,
    "IVA_5": CODIGO_T06,
    "IVA_0": CODIGO_T07,
    "INGRESOS_EXCLUIDOS": CODIGO_T04,
}

#: Ancho fijo de cada valor monetario dentro de la cadena.
ANCHO_VALOR = 0  # sin relleno; la guía solo exige 2 decimales


class ErrorFiscal(ValueError):
    """Datos inválidos para construir el CUFE/CUDE."""


# --------------------------------------------------------------------------
# Normalización
# --------------------------------------------------------------------------

def normalizar_numero(valor) -> str:
    """Extrae solo dígitos de un NIT o número (conserva ceros iniciales)."""
    if valor is None:
        return ""
    return "".join(c for c in str(valor) if c.isdigit())


def formatear_valor(valor) -> str:
    """Formatea un importe a dos decimales con redondeo comercial (half-up).

    ``format(Decimal(x), ".2f")`` redondea half-even: un total de 1234.565
    terminaba en ``1234.56`` en vez de ``1234.57``, cambiando el SHA-384 y
    provoke el rechazo FAB14b de la DIAN.
    """
    if valor is None:
        valor = 0
    if isinstance(valor, float):
        # float -> str conserva la representación corta esperada por Decimal
        valor = repr(valor)
    d = Decimal(str(valor))
    return format(d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), "f")


def normalizar_fecha(fecha) -> str:
    """Normaliza una fecha a ``AAAAMMDD`` (8 dígitos).

    Acepta ``YYYY-MM-DD``, ``YYYYMMDD``, ``DD/MM/YYYY`` y datetimes. Rechaza
    cualquier otra cosa en vez de devolver una cadena de longitud arbitraria
    (antes ``normalizar_fecha("2026-01-31 00:00:00")`` devolvía 14 dígitos y
    corrompía silenciosamente el hash).
    """
    from datetime import date, datetime

    if isinstance(fecha, (datetime, date)):
        return f"{fecha.year:04d}{fecha.month:02d}{fecha.day:02d}"
    texto = str(fecha or "").strip()
    if not texto:
        raise ErrorFiscal("Fecha de emisión vacía")
    if re.fullmatch(r"\d{8}", texto):
        return texto
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", texto)
    if m:
        return f"{m.group(1)}{m.group(2)}{m.group(3)}"
    m = re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})", texto)
    if m:
        return f"{m.group(3)}{m.group(2)}{m.group(1)}"
    raise ErrorFiscal(f"Formato de fecha no reconocido: {fecha!r} (se espera YYYY-MM-DD)")


def normalizar_hora(hora) -> str:
    """Normaliza una hora a ``HHMMSS`` (6 dígitos).

    Acepta ``HH:MM:SS``, ``HH:MM``, ``HHMMSS`` y datetimes. Se rechaza la
    fecha completa: mezclarla con la fecha en un solo campo es justamente el
    defecto que producía QR de 9 campos.
    """
    from datetime import datetime, time

    if isinstance(hora, datetime):
        hora = hora.time()
    if isinstance(hora, time):
        return f"{hora.hour:02d}{hora.minute:02d}{hora.second:02d}"
    texto = str(hora or "").strip()
    if not texto:
        raise ErrorFiscal("Hora de emisión vacía")
    if re.fullmatch(r"\d{6}", texto):
        return texto
    # Se acepta y se descarta el desfase: la DIAN exige la hora de Colombia
    # (UTC-5) en HH:MM:SS. La BD guarda la hora con offset ("14:30:00-05:00").
    m = re.fullmatch(r"(\d{2}):(\d{2})(?::(\d{2}))?(?:[+-]\d{2}:?\d{2})?", texto)
    if m:
        return f"{m.group(1)}{m.group(2)}{m.group(3) or '00'}"
    m = re.fullmatch(r"(\d{2})(\d{2})(\d{2})", texto)
    if m:
        return f"{m.group(1)}{m.group(2)}{m.group(3)}"
    raise ErrorFiscal(f"Formato de hora no reconocido: {hora!r} (se espera HH:MM:SS)")


def numero_factura_8(num_fac) -> str:
    """Normaliza el número de factura al formato de la cadena del CUFE/QR.

    Acepta el número puro (``123``) o ``prefijo+numero`` (``FE123``), que es como
    lo guarda el sistema.

    La guía técnica fija 8 dígitos, pero los rangos que autoriza la DIAN tienen
    9 o más (``990000000``-``999999999``). Truncar a los 8 últimos dígitos
    convertía el número autorizado en otro documento distinto. Aquí se quitan
    los ceros a la izquierda sobrantes y se rellena a 8 como mínimo: los
    números cortos quedan a 8 dígitos y los largos conservan su valor real.
    """
    digitos = normalizar_numero(num_fac)
    if not digitos:
        raise ErrorFiscal("Número de factura vacío")
    if len(digitos) > 8:
        digitos = digitos.lstrip("0") or "0"
    return digitos.zfill(8)


def _validar_clave_tecnica(clave: str) -> str:
    clave = str(clave or "").strip()
    if not re.fullmatch(r"[0-9a-fA-F]{32}", clave):
        raise ErrorFiscal(
            "La clave técnica debe ser un hexadecimal de 32 caracteres "
            f"(recibido: {clave!r})"
        )
    return clave.lower()


def _validar_ambiente(tipo_ambiente) -> str:
    valor = str(tipo_ambiente or "").strip()
    if valor not in ("1", "2"):
        raise ErrorFiscal(
            f"Ambiente de destino inválido: {tipo_ambiente!r}. "
            "Use '1' (producción en habilitación) o '2' (producción en operación)."
        )
    return valor


# --------------------------------------------------------------------------
# Cadena del CUFE / CUDE
# --------------------------------------------------------------------------

def slots_impuestos(categorias: dict) -> list[tuple[str, str]]:
    """Devuelve los slots (código, valor) de T04..T07 en orden de la guía.

    ``categorias`` mapea nombres de tarifa (``IVA_19``, ``IVA_5``, ``IVA_0``,
    ``INGRESOS_EXCLUIDOS``) a importes. Los slots sin valor van con el código en
    blanco, según la especificación.
    """
    categorias = categorias or {}
    # Acumula por código de slot: varias tarifas internas pueden mapear al
    # mismo slot del CUFE.
    por_codigo = {c: Decimal("0") for c in (CODIGO_T04, CODIGO_T05, CODIGO_T06, CODIGO_T07)}
    for tarifa, monto in categorias.items():
        codigo = TARIFA_A_SLOT.get(tarifa)
        if codigo is None:
            continue
        por_codigo[codigo] = por_codigo[codigo] + Decimal(str(monto or 0))
    salida = []
    for codigo in (CODIGO_T04, CODIGO_T05, CODIGO_T06, CODIGO_T07):
        monto = por_codigo[codigo]
        salida.append((CODIGO_VACIO if monto == 0 else codigo, formatear_valor(monto)))
    return salida


def cufe_base(
    num_fac,
    fecha,
    hora,
    valor_factura,
    categorias: dict,
    nit_emisor,
    nit_adquirente,
    clave_tecnica,
    tipo_ambiente,
    valor_transaccion,
    *,
    ingresos_excluidos=None,
    retenciones_ica=None,
    retenciones_fuente=None,
    retenciones_iva=None,
    otros_impuestos=None,
    valor_moneda_extranjera=None,
    valor_moneda_nacional=None,
    total_pagar=None,
) -> str:
    """Construye la cadena canónica de 22 campos del CUFE/CUDE.

    Orden (guía técnica DIAN, sin separadores):

    ===  =====================================================
    1-3  Número de factura (8), fecha AAAAMMDD (8), hora HHMMSS (6)
    4    Formato del valor total de la factura (2 decimales)
    5-12 T04..T07: código y valor de cada impuesto (4 pares)
    13-16 Retenciones (ICA, fuente, IVA, otros) y otros impuestos
    17-19 T14 moneda extranjera, T15 moneda nacional, T16 total a pagar
    20-21 NIT emisor, NIT adquirente
    22    Clave técnica + ambiente de destino (campos 22 y 23 en algunas
         versiones; aquí se concatenan como número de factura y ambiente)
    ===  =====================================================
    """
    slots = slots_impuestos(categorias)
    fecha_n = normalizar_fecha(fecha)
    hora_n = normalizar_hora(hora)
    numero_n = numero_factura_8(num_fac)
    ambiente = _validar_ambiente(tipo_ambiente)
    clave = _validar_clave_tecnica(clave_tecnica)
    emisor = normalizar_numero(nit_emisor)
    adquirente = normalizar_numero(nit_adquirente)
    if not emisor:
        raise ErrorFiscal("NIT del emisor vacío")
    if not adquirente:
        raise ErrorFiscal("NIT del adquirente vacío")

    partes = [
        numero_n,
        fecha_n,
        hora_n,
        formatear_valor(valor_factura),
    ]
    for codigo, valor in slots:
        partes.extend([codigo, valor])
    partes.extend([
        formatear_valor(ingresos_excluidos or 0),
        formatear_valor(retenciones_iva or 0),
        formatear_valor(retenciones_fuente or 0),
        formatear_valor(retenciones_ica or 0),
        formatear_valor(otros_impuestos or 0),
        formatear_valor(valor_moneda_extranjera or 0),
        formatear_valor(valor_moneda_nacional or 0),
        formatear_valor(total_pagar if total_pagar is not None else valor_transaccion),
        emisor,
        adquirente,
        clave,
        ambiente,
    ])
    return "".join(partes)


def calculate_cufe(
    num_fac,
    fecha,
    hora,
    valor_factura,
    categorias: dict,
    nit_emisor,
    nit_adquirente,
    clave_tecnica,
    tipo_ambiente,
    valor_transaccion,
    **kwargs,
) -> str:
    """Calcula el CUFE (SHA-384, 96 hexadecimales) de la factura."""
    base = cufe_base(
        num_fac, fecha, hora, valor_factura, categorias,
        nit_emisor, nit_adquirente, clave_tecnica, tipo_ambiente,
        valor_transaccion, **kwargs,
    )
    return hashlib.sha384(base.encode("utf-8")).hexdigest()


#: Alias histórico usado por notas crédito/débito y documento soporte.
calcular_cufe = calculate_cufe
calcular_cude = calculate_cufe


# --------------------------------------------------------------------------
# Cadena QR
# --------------------------------------------------------------------------

#: Environments válidos para el QR (ambiente de destino).
_TIPOS_OPERACION = {
    "01", "02", "03", "04", "05", "06", "07", "08", "09",
    "10", "11", "20", "21", "22", "30", "31", "32", "33", "34", "35",
    "50", "51", "52", "53", "90", "91", "92", "93",
}


def generar_cadena_qr(
    tipo_ambiente,
    tipo_operacion,
    nit_emisor,
    num_fac,
    fecha,
    hora,
    valor_transaccion,
    clave_tecnica,
    cufe,
) -> str:
    """Construye la cadena QR DIAN de 10 campos separados por ``;``.

    ``DIAN;<ambiente>;<tipo_operacion>;<nit_emisor>;<num_fac>;<fecha>;<hora>;
    <valor>;<clave_tecnica>;<cufe>``

    La fecha (``AAAAMMDD``) y la hora (``HHMMSS``) son campos separados. Antes se
    recibían juntas en un único parámetro, lo que producía 9 campos.
    """
    ambiente = _validar_ambiente(tipo_ambiente)
    operacion = str(tipo_operacion or "").strip()
    if not re.fullmatch(r"\d{2}", operacion):
        raise ErrorFiscal(
            f"Tipo de operación inválido: {tipo_operacion!r} (se esperan 2 dígitos)")
    emisor = normalizar_numero(nit_emisor)
    if not emisor:
        raise ErrorFiscal("NIT del emisor vacío")
    clave = _validar_clave_tecnica(clave_tecnica)
    cufe_txt = str(cufe or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{96}", cufe_txt):
        raise ErrorFiscal(f"CUFE inválido (se esperan 96 hexadecimales): {cufe!r}")

    partes = [
        "DIAN",
        ambiente,
        operacion,
        emisor,
        numero_factura_8(num_fac),
        normalizar_fecha(fecha),
        normalizar_hora(hora),
        formatear_valor(valor_transaccion),
        clave,
        cufe_txt,
    ]
    return ";".join(partes)