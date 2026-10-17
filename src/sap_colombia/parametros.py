"""Parámetros tributarios y legales colombianos por vigencia.

Sustituye a los literales "mágicos" dispersos por el código (SMMLV, UVT, tasas
de retención, topes). Antes, valores como el SMMLV vivían como constantes de
módulo o como números escritos a mano dentro de las funciones, con años en el
nombre (``SMMLV_2026``) que nadie actualizaba al cambiar de vigencia.

Modelo:
- ``parametros_tributarios`` persiste los valores por ``(anio, clave)``.
- Si no hay fila para el año pedido, se usa el catálogo estático de
  :data:`VALORES_POR_DEFECTO` (última vigencia conocida).
- Las tarifas **progresivas y por UVT/salario** viven en
  :data:`TARIFAS_SERVICIOS_PJ`, :data:`TARIFAS_SERVICIOS_PN` y
  :data:`TARIFAS_RETENCION_RENTA`.

Normativa de referencia:
- Estatuto Tributario (arts. 424, 430, 431, 437, 437E, 460, 462, 475, 579, 592).
- Decreto 2271 de 2022 / Ley 2277 de 2022 (ReteICA, ReteFuente, retención a
  no residentes).
- Resoluciones de la DIAN que fijan UVT y SMMLV cada año.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from sap_colombia import dbutil
from sap_colombia import database as db

# --------------------------------------------------------------------------
# Catálogo por defecto (última vigencia conocida)
# --------------------------------------------------------------------------

VALORES_POR_DEFECTO: dict[str, str] = {
    # Salario mínimo legal mensual
    "smmlv": "1750905.00",
    # Unidad de valor tributario
    "uvt": "52374.00",
    # Tope máximo de base para aportes a pension (Ley 2277/2022: 25 SMMLV)
    "tope_base_pension_smlv": "25",
    # Auxilio de transporte (Decreto 1072/2015: 2 SMMLV tope; monto fijo legal)
    "auxilio_transporte": "249095.00",
    # Auxilio de transporte máximo (2 SMMLV)
    "auxilio_transporte_tope_smlv": "2",
    # Intereses sobre cesantías (Ley 1779/2016 art. 6)
    "tasa_intereses_cesantias": "0.12",
    # Cesantías (CST art. 177 + Ley 2251/2021: 8.33% sobre salario <= 2 SMMLV)
    "tasa_cesantias": "0.0833",
    # Prima de servicios (Ley 2251/2021: 1 SMMLV al año para <= 2 SMMLV)
    "prima_servicios_salarios_anuales": "1",
    "prima_servicios_tope_smlv": "2",
    # Cotizaciones
    "tasa_salud_empleado": "0.04",
    "tasa_pension_empleado": "0.04",
    "tasa_salud_empleador": "0.085",
    "tasa_pension_empleador": "0.12",
    # Parafiscales (Ley 136/1961, Ley 1066/1996, Ley 2300/2023)
    "tasa_sena": "0.02",
    "tasa_icbf": "0.03",
    "tasa_caja_compensacion": "0.04",
    # ARL por clase de riesgo (Decreto 427/2022)
    "tasa_arl_riesgo_i": "0.00522",
    "tasa_arl_riesgo_ii": "0.01044",
    "tasa_arl_riesgo_iii": "0.01836",
    "tasa_arl_riesgo_iv": "0.02660",
    "tasa_arl_riesgo_v": "0.06960",
    # Retenciones comerciales
    "tasa_reteica": "0.0069",
    "tasa_reteiva": "0.15",
    "tasa_retefuente_bienes": "0.025",
    "tasa_retefuente_servicios": "0.04",
    "tasa_retefuente_arrendamiento": "0.035",
    "tasa_retefuente_compras_persona_juridica": "0.005",
    "tasa_retefuente_compras_persona_natural": "0.015",
    "tasa_retefuente_transporte_carga": "0.01",
    "tasa_retefuente_servicios_publicos": "0.02",
    "tasa_retefuente_no_residente": "0.15",
    "tasa_retefuente_no_residente_servicios": "0.15",
    # Autorretención al propio ReteICA (Art. 455-4 ET / Ley 6 de 1992, Ley 2277)
    "tasa_reteica_propio": "0.0069",
    "tope_reteica_propio_uvt": "24000",
    # Salario mínimo que dispara retención en la fuente a salarios
    "umbral_retencion_salarios_smlv": "2",
    # Exoneración de retención a servicios deuguados (Art. 592-2)
    "exoneracion_retencion_honorarios_uvt": "80",
}

# --------------------------------------------------------------------------
# Tablas de retención
# --------------------------------------------------------------------------

# Retención en la fuente a la renta (art. 383 E.T., art. 386/388, tables en UVT).
# Cada tramo: (tope_UVT, tarifa_marginal, resta_UVT) — el impuesto en UVT es
# base_UVT × tarifa − resta. Los valores de "resta" derivan de las tarifas
# marginales del art. 386, garantizando la continuidad de la tabla.
TARIFAS_RETENCION_RENTA: list[tuple[float, float, float]] = [
    (95, 0.00, 0.0),
    (150, 0.19, 18.05),
    (360, 0.28, 31.55),
    (640, 0.33, 49.55),
    (945, 0.35, 62.35),
    (2300, 0.37, 81.25),
    (float("inf"), 0.39, 127.25),
]

#: Renta exenta por rentas de trabajo: 25% del pago, tope 240 UVT/mes
#: (art. 388 E.T. mod. Ley 2277/2022).
RENTA_EXENTA_PORCENTAJE = "0.25"
RENTA_EXENTA_TOPE_UVT = "240"

#: Servicios de personas jurídicas (Art. 437 num. 3 literal a) - progressive.
TARIFAS_SERVICIOS_PJ: list[tuple[float, float]] = [
    (95, 0.02),
    (150, 0.04),
    (360, 0.06),
    (640, 0.08),
    (float("inf"), 0.10),
]

#: Servicios de personas naturales - progressive (Art. 437 num. 3 literal b).
TARIFAS_SERVICIOS_PN: list[tuple[float, float]] = [
    (95, 0.02),
    (150, 0.04),
    (360, 0.06),
    (640, 0.08),
    (float("inf"), 0.10),
]

#: Mínimo legal de honorarios (Res. DIAN 031 de 2024): 80 UVT/mes.
MINIMO_HONORARIOS_UVT = 80


def _q2(valor) -> Decimal:
    return Decimal(str(valor)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# --------------------------------------------------------------------------
# Persistencia
# --------------------------------------------------------------------------

def _crear_tabla(conn) -> None:
    dbutil.exec_script(conn, """
        CREATE TABLE IF NOT EXISTS parametros_tributarios (
            clave TEXT NOT NULL,
            anio INTEGER NOT NULL,
            valor TEXT NOT NULL,
            descripcion TEXT,
            PRIMARY KEY (clave, anio)
        );
    """)


def sembrar_parametros(anio: int | None = None) -> int:
    """Carga el catálogo por defecto en ``parametros_tributarios``.

    Idempotente: no sobrescribe valores que ya existan para ese año.

    Returns:
        Número de filas insertadas.
    """
    anio = anio or date.today().year
    conn = db.get_connection()
    insertadas = 0
    try:
        _crear_tabla(conn)
        for clave, valor in VALORES_POR_DEFECTO.items():
            cur = dbutil.query(
                conn,
                "INSERT INTO parametros_tributarios (clave, anio, valor) VALUES (?, ?, ?) "
                "ON CONFLICT (clave, anio) DO NOTHING",
                (clave, anio, valor),
            )
            insertadas += cur.rowcount or 0
        conn.commit()
    finally:
        conn.close()
    return insertadas


def obtener(clave: str, anio: int | None = None, defecto=None):
    """Devuelve el valor del parámetro como ``Decimal`` para el año pedido.

    Falls back to :data:`VALORES_POR_DEFECTO` y luego al defecto explícito.
    """
    anio = anio or date.today().year
    conn = db.get_connection()
    try:
        _crear_tabla(conn)
        row = dbutil.query(
            conn,
            "SELECT valor FROM parametros_tributarios WHERE clave = ? AND anio <= ? "
            "ORDER BY anio DESC LIMIT 1",
            (clave, anio),
        ).fetchone()
    finally:
        conn.close()
    if row is not None:
        return Decimal(str(row["valor"]))
    if clave in VALORES_POR_DEFECTO:
        return Decimal(VALORES_POR_DEFECTO[clave])
    if defecto is not None:
        return Decimal(str(defecto))
    raise KeyError(f"Parámetro tributario no definido: {clave}")


def obtener_decimal(clave: str, anio: int | None = None, defecto=None) -> Decimal:
    return obtener(clave, anio, defecto)


def smmlv(anio: int | None = None) -> Decimal:
    """Salario mínimo legal mensual vigente."""
    return obtener("smmlv", anio)


def uvt(anio: int | None = None) -> Decimal:
    """Unidad de valor tributario vigente."""
    return obtener("uvt", anio)


def anio_de(fecha: str | date | datetime | None = None) -> int:
    """Extrae el año de una fecha en cualquiera de los formatos aceptados."""
    if fecha is None:
        return date.today().year
    if isinstance(fecha, datetime):
        return fecha.year
    if isinstance(fecha, date):
        return fecha.year
    texto = str(fecha).strip()
    try:
        return int(texto[:4])
    except ValueError:
        return date.today().year


def ahora_utc() -> datetime:
    return datetime.now(timezone.utc)


def listar(anio: int | None = None) -> dict[str, Decimal]:
    """Devuelve todos los parámetros aplicables a un año, como ``Decimal``."""
    anio = anio or date.today().year
    conn = db.get_connection()
    try:
        _crear_tabla(conn)
        rows = dbutil.query(
            conn,
            "SELECT DISTINCT ON (clave) clave, valor FROM parametros_tributarios "
            "WHERE anio <= ? ORDER BY clave, anio DESC",
            (anio,),
        ).fetchall()
    finally:
        conn.close()
    resultado = {c: Decimal(str(v)) for c, v in VALORES_POR_DEFECTO.items()}
    for r in rows:
        resultado[r["clave"]] = Decimal(str(r["valor"]))
    return resultado