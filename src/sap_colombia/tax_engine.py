"""Motor fiscal colombiano: IVA, Retención en la fuente, ReteIVA y ReteICA.

Fórmulas por línea (Estatuto Tributario):

- Base        = cantidad × valor_unitario
- IVA         = Base × tarifa (19%, 5%, 0%, y las exclusiones de los arts. 424,
               430 y 431 E.T.: EXCLUIDA, VG, EXC)
- Retención en la fuente = según el concepto del art. 437 y el procedimiento del
               art. 592, con la exoneración del art. 592-2
- ReteIVA     = 15% del IVA de la línea (art. 437-1 E.T.)
- ReteICA     = Base × tarifa distrital, **restando** las exclusiones del
               art. 462 E.T. (renta de trabajo, dividendos, intereses de
               crédito, reintegros no constitutivos de ingreso)
- Total línea = Base + IVA − Retención en la fuente − ReteIVA − ReteICA

El redondeo es comercial (ROUND_HALF_UP) a 2 decimales, aplicado por concepto
y por línea; los totales de la factura son la suma de los valores ya redondeados
de cada línea, de modo que ``PayableAmount`` siempre reconcilia con las líneas.

Las tasas provienen de :mod:`sap_colombia.parametros` (tabla
``parametros_tributarios``), no de constantes escritas a mano.
"""

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from sap_colombia import parametros

# ---------------------------------------------------------------------------
# IVA
# ---------------------------------------------------------------------------

#: Categorías de IVA soportadas. Las tres primeras son tarifas; el resto son
#: operaciones excluidas/no gravadas de los arts. 424, 430 y 431 E.T. Antes solo
#: existían 0/5/19, lo que impedía facturar legalmente líneas excluidas.
TARIFAS_IVA: dict[str, Decimal] = {
    "IVA_19": Decimal("0.19"),
    "IVA_5": Decimal("0.05"),
    "IVA_0": Decimal("0.00"),
    "EXCLUIDA": Decimal("0.00"),   # Art. 424 E.T.
    "VG": Decimal("0.00"),         # Bienes de capital /Activos fijo
    "EXC": Decimal("0.00"),        # Art. 430/431 E.T. (bienes excluidos)
    "NO_GRAVADO": Decimal("0.00"), # Art. 367 E.T.
}

#: Porcentaje que se informa al cliente en el XML.
PORCENTAJE_IVA: dict[str, str] = {
    "IVA_19": "19",
    "IVA_5": "5",
    "IVA_0": "0",
    "EXCLUIDA": "0",
    "VG": "0",
    "EXC": "0",
    "NO_GRAVADO": "0",
}

#: Códigos del catálogo DIAN para cada categoría de IVA en el bloque de
#: LineExtension (tax extension).
CODIGO_IVA_DIAN: dict[str, str] = {
    "IVA_19": "01",
    "IVA_5": "02",
    "IVA_0": "03",
    "EXCLUIDA": "04",
    "VG": "05",
    "EXC": "06",
    "NO_GRAVADO": "07",
}

# ---------------------------------------------------------------------------
# Retención en la fuente (art. 437 E.T.)
# ---------------------------------------------------------------------------

TOLERANCIA_EXENTA = "EXENTO"

#: Conceptos con tasa fija (art. 437 E.T.).
TARIFAS_RETEN_FUENTE: dict[str, Decimal] = {
    "BIENES": Decimal("0.025"),
    "SERVICIOS": Decimal("0.04"),
    "ARRENDAMIENTO": Decimal("0.035"),
    "COMISIONES": Decimal("0.10"),
    "COMPRAS_BIENES_PJ": Decimal("0.005"),
    "COMPRAS_BIENES_PN": Decimal("0.015"),
    "TRANSPORTE_TIERRA_CARGA": Decimal("0.01"),
    "SERVICIOS_PUBLICOS": Decimal("0.02"),
}

#: Conceptos con tabla progresiva por múltiplo de SMMLV (art. 437 num. 3 y 4).
TARIFAS_PROGRESIVAS: dict[str, list[tuple[float, float]]] = {
    "SERVICIOS_PJ": parametros.TARIFAS_SERVICIOS_PJ,
    "SERVICIOS_PN": parametros.TARIFAS_SERVICIOS_PN,
    "HONORARIOS": parametros.TARIFAS_SERVICIOS_PJ,
    "RENTA_TRABAJO": parametros.TARIFAS_RETENCION_RENTA,
}

#: Tipos de documento del adquirente que activan la exoneración del art. 592-2
#: (no se practica retención al primer tramo de la tabla progresiva).
TASA_RETEIVA = Decimal("0.15")

CENTAVOS = Decimal("0.01")

#: Tarifa de ReteICA por defecto (Bogotá D.C. actividad comercial 6,9 × 1000).
TARIFA_RETEICA_POR_DEFECTO = Decimal("0.0069")

#: Topes máximos de ReteICA por Industrial Cedula 6.9x1000 (Ley 2277/2022).
TOPE_RETEICA_UVT_ANUAL = Decimal("24000")

CLASIFICACIONES_VALIDAS = (
    tuple(TARIFAS_RETEN_FUENTE)
    + tuple(TARIFAS_PROGRESIVAS)
    + (TOLERANCIA_EXENTA,)
)

#: Clasificaciones que identifican ingresos **no constitutivos de renta** para
#: efectos de ReteICA (art. 462 E.T., Ley 2277 de 2022): no forman parte de la
#: base del impuesto de industria y comercio.
EXCLUSIONES_RETEICA = {
    "RENTA_TRABAJO",
    "DIVIDENDOS",
    "INTERESES_CREDITO",
    "REINTEGROS_NO_INGRESO",
    "APORTES_SOCIALES",
}


class ErrorFiscal(Exception):
    """Error de validación o liquidación fiscal."""


def _redondear(valor: Decimal) -> Decimal:
    return valor.quantize(CENTAVOS, rounding=ROUND_HALF_UP)


def _a_decimal(valor, nombre: str) -> Decimal:
    if isinstance(valor, Decimal):
        return valor
    try:
        return Decimal(str(valor).strip())
    except (InvalidOperation, ValueError, AttributeError):
        raise ErrorFiscal(f"Valor no numérico para {nombre}: {valor!r}")


def _tasa_progresiva(base: Decimal, anio: int | None = None) -> Decimal:
    """Tasa de retención en la fuente a la renta (tabla UVT, art. 386 E.T.).

    La tabla ``TARIFAS_RETENCION_RENTA`` está expresada en UVT; el impuesto
    por tramo es ``base_UVT × tarifa − resta_UVT``. Se devuelve la tarifa
    marginal del tramo que contiene a la base.
    """
    uvt_valor = parametros.uvt(anio)
    if uvt_valor <= 0:
        raise ErrorFiscal("UVT no configurado; no se puede calcular la retención progresiva")
    base_uvt = base / uvt_valor
    for techo_uvt, tarifa, _resta_uvt in parametros.TARIFAS_RETENCION_RENTA:
        if base_uvt <= techo_uvt:
            return Decimal(str(tarifa))
    return Decimal("0.39")


@dataclass
class LineaFactura:
    """Línea de factura con clasificación fiscal y tarifa de IVA."""

    codigo: str
    descripcion: str
    cantidad: Decimal
    valor_unitario: Decimal
    clasificacion: str = "BIENES"
    tarifa_iva: str = "IVA_19"
    #: Marca la línea como ingreso no constitutivo de renta / excluido de ICA.
    excluido_de_ica: bool = False
    #: Base ya exonerada de retención (art. 592-2 E.T.).
    base_exonerada_retencion: Decimal | None = None
    anio: int | None = None

    def __post_init__(self):
        self.cantidad = _a_decimal(self.cantidad, "cantidad")
        self.valor_unitario = _a_decimal(self.valor_unitario, "valor_unitario")
        if self.cantidad < 0:
            raise ErrorFiscal(f"Cantidad negativa en línea {self.codigo}")
        if self.valor_unitario < 0:
            raise ErrorFiscal(f"Valor unitario negativo en línea {self.codigo}")
        if self.tarifa_iva not in TARIFAS_IVA:
            raise ErrorFiscal(
                f"Tarifa de IVA inválida: {self.tarifa_iva}. "
                f"Válidas: {', '.join(TARIFAS_IVA)}"
            )
        if self.clasificacion not in CLASIFICACIONES_VALIDAS:
            raise ErrorFiscal(
                f"Clasificación inválida: {self.clasificacion}. "
                f"Válidas: {', '.join(CLASIFICACIONES_VALIDAS)}"
            )
        if self.base_exonerada_retencion is not None:
            self.base_exonerada_retencion = _a_decimal(
                self.base_exonerada_retencion, "base_exonerada_retencion"
            )
            if self.base_exonerada_retencion < 0:
                raise ErrorFiscal("base_exonerada_retencion no puede ser negativa")

    @property
    def es_exenta_ica(self) -> bool:
        return self.excluido_de_ica or self.clasificacion in EXCLUSIONES_RETEICA


@dataclass
class ResultadoLinea:
    """Liquidación fiscal de una línea."""

    linea: LineaFactura
    base: Decimal
    valor_iva: Decimal
    valor_con_iva: Decimal
    reteica: Decimal
    reteiva: Decimal
    retencion_fuente: Decimal
    total_linea: Decimal
    base_retencion: Decimal = Decimal("0.00")
    base_ica: Decimal = Decimal("0.00")


@dataclass
class ResultadoFactura:
    """Liquidación fiscal agregada de la factura."""

    lineas: list[ResultadoLinea] = field(default_factory=list)
    base_total: Decimal = Decimal("0.00")
    iva_total: Decimal = Decimal("0.00")
    total_con_iva: Decimal = Decimal("0.00")
    reteica_total: Decimal = Decimal("0.00")
    reteiva_total: Decimal = Decimal("0.00")
    retencion_fuente_total: Decimal = Decimal("0.00")
    valor_transaccion: Decimal = Decimal("0.00")
    iva_19: Decimal = Decimal("0.00")
    iva_5: Decimal = Decimal("0.00")
    iva_0: Decimal = Decimal("0.00")
    base_excluida_ica: Decimal = Decimal("0.00")


class TaxEngine:
    """Motor de liquidación fiscal colombiano."""

    def __init__(
        self,
        tarifa_reteica: Decimal | None = None,
        *,
        aplicar_reteica: bool = True,
        aplicar_reteiva: bool = True,
        aplicar_retencion_fuente: bool = True,
        anio: int | None = None,
    ):
        if tarifa_reteica is None:
            tarifa_reteica = parametros.obtener("tasa_reteica", anio)
        self.tarifa_reteica = _a_decimal(tarifa_reteica, "tarifa_reteica")
        if self.tarifa_reteica < 0:
            raise ErrorFiscal("La tarifa de ReteICA no puede ser negativa")
        if self.tarifa_reteica > 1:
            raise ErrorFiscal(
                f"La tarifa de ReteICA no puede superar el 100% (recibido: {self.tarifa_reteica})"
            )
        self.aplicar_reteica = aplicar_reteica
        self.aplicar_reteiva = aplicar_reteiva
        self.aplicar_retencion_fuente = aplicar_retencion_fuente
        self.anio = anio

    # -- Retención en la fuente ------------------------------------------

    def _retencion_fuente(self, linea: LineaFactura, base: Decimal) -> tuple[Decimal, Decimal]:
        """Devuelve (retención, base de retención) según el concepto."""
        if not self.aplicar_retencion_fuente:
            return Decimal("0.00"), base
        if linea.clasificacion == TOLERANCIA_EXENTA:
            return Decimal("0.00"), Decimal("0.00")

        base_retencion = base
        exonerada = linea.base_exonerada_retencion
        if exonerada is not None and exonerada > 0:
            # Art. 592-2 E.T.: el primer tranche de honorarios / servicios no se
            # retiene. La exoneración nunca puede superar la base.
            base_retencion = max(Decimal("0.00"), base - exonerada)

        if base_retencion <= 0:
            return Decimal("0.00"), Decimal("0.00")

        concepto = linea.clasificacion
        if concepto in TARIFAS_RETEN_FUENTE:
            tasa = parametros.obtener(
                {
                    "BIENES": "tasa_retefuente_bienes",
                    "SERVICIOS": "tasa_retefuente_servicios",
                    "ARRENDAMIENTO": "tasa_retefuente_arrendamiento",
                    "COMISIONES": "tasa_retefuente_servicios",
                    "COMPRAS_BIENES_PJ": "tasa_retefuente_compras_persona_juridica",
                    "COMPRAS_BIENES_PN": "tasa_retefuente_compras_persona_natural",
                    "TRANSPORTE_TIERRA_CARGA": "tasa_retefuente_transporte_carga",
                    "SERVICIOS_PUBLICOS": "tasa_retefuente_servicios_publicos",
                }[concepto],
                linea.anio or self.anio,
            )
            return _redondear(base_retencion * tasa), base_retencion

        if concepto in TARIFAS_PROGRESIVAS:
            if concepto == "RENTA_TRABAJO":
                tasa = _tasa_progresiva(base_retencion, linea.anio or self.anio)
            else:
                smmlv_valor = parametros.smmlv(linea.anio or self.anio)
                base_smlv = base_retencion / smmlv_valor if smmlv_valor > 0 else base_retencion
                tasa = Decimal("0.02")
                for techo, t in TARIFAS_PROGRESIVAS[concepto]:
                    if base_smlv <= techo:
                        tasa = Decimal(str(t))
                        break
                else:
                    tasa = Decimal(str(TARIFAS_PROGRESIVAS[concepto][-1][1]))
            return _redondear(base_retencion * tasa), base_retencion

        return Decimal("0.00"), Decimal("0.00")

    # -- Línea ------------------------------------------------------------

    def liquidar_linea(self, linea: LineaFactura) -> ResultadoLinea:
        base = _redondear(linea.cantidad * linea.valor_unitario)
        tarifa_iva = TARIFAS_IVA[linea.tarifa_iva]
        valor_iva = _redondear(base * tarifa_iva)
        valor_con_iva = base + valor_iva

        retencion_fuente, base_retencion = self._retencion_fuente(linea, base)

        # ReteIVA: 15% del IVA de la línea (art. 437-1 E.T.). Si la línea no
        # factura IVA, la retención es cero.
        if self.aplicar_reteiva:
            reteiva = _redondear(valor_iva * parametros.obtener("tasa_reteiva", linea.anio or self.anio))
        else:
            reteiva = Decimal("0.00")

        # ReteICA: sobre la base **menos** las exclusiones del art. 462 E.T.
        if linea.es_exenta_ica or not self.aplicar_reteica:
            base_ica = Decimal("0.00")
            reteica = Decimal("0.00")
        else:
            base_ica = base
            reteica = _redondear(base_ica * self.tarifa_reteica)

        total_linea = valor_con_iva - retencion_fuente - reteiva - reteica
        if total_linea < 0:
            raise ErrorFiscal(
                f"El total de la línea {linea.codigo} es negativo "
                f"({total_linea}): las retenciones superan el valor facturado. "
                "Revise la tasa de ReteICA o la clasificación de la línea."
            )

        return ResultadoLinea(
            linea=linea,
            base=base,
            valor_iva=valor_iva,
            valor_con_iva=valor_con_iva,
            reteica=reteica,
            reteiva=reteiva,
            retencion_fuente=retencion_fuente,
            total_linea=total_linea,
            base_retencion=base_retencion,
            base_ica=base_ica,
        )

    # -- Factura ----------------------------------------------------------

    def liquidar_factura(self, lineas: list[LineaFactura]) -> ResultadoFactura:
        if not lineas:
            raise ErrorFiscal("La factura debe contener al menos una línea")

        resultados = [self.liquidar_linea(linea) for linea in lineas]

        base_total = _redondear(sum((r.base for r in resultados), Decimal("0.00")))
        iva_total = _redondear(sum((r.valor_iva for r in resultados), Decimal("0.00")))
        reteica_total = _redondear(sum((r.reteica for r in resultados), Decimal("0.00")))
        reteiva_total = _redondear(sum((r.reteiva for r in resultados), Decimal("0.00")))
        retencion_total = _redondear(
            sum((r.retencion_fuente for r in resultados), Decimal("0.00"))
        )
        base_excluida = _redondear(
            sum((r.base for r in resultados if r.linea.es_exenta_ica), Decimal("0.00"))
        )
        total_con_iva = base_total + iva_total

        # El total a pagar es la suma de los totales de línea ya redondeados:
        # así PayableAmount siempre reconcilia con InvoiceLine/TotalLineAmount.
        valor_transaccion = _redondear(
            sum((r.total_linea for r in resultados), Decimal("0.00"))
        )

        iva_19 = _redondear(sum((r.valor_iva for r in resultados
                                  if r.linea.tarifa_iva == "IVA_19"), Decimal("0.00")))
        iva_5 = _redondear(sum((r.valor_iva for r in resultados
                                 if r.linea.tarifa_iva == "IVA_5"), Decimal("0.00")))
        iva_0 = _redondear(sum((r.base for r in resultados
                                if r.linea.tarifa_iva in ("IVA_0", "EXCLUIDA", "VG", "EXC", "NO_GRAVADO")),
                               Decimal("0.00")))

        return ResultadoFactura(
            lineas=resultados,
            base_total=base_total,
            iva_total=iva_total,
            total_con_iva=total_con_iva,
            reteica_total=reteica_total,
            reteiva_total=reteiva_total,
            retencion_fuente_total=retencion_total,
            valor_transaccion=valor_transaccion,
            iva_19=iva_19,
            iva_5=iva_5,
            iva_0=iva_0,
            base_excluida_ica=base_excluida,
        )