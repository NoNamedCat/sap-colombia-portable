"""Numeración autorizada por la DIAN: rango, contigüidad y prefijo.

La DIAN asigna a cada emisor una resolución con un **rango de numeración**
autorizado. Toda factura, nota crédito y nota débito debe usar un número de ese
rango, y los documentos barring Strip no se pueden reutilizar. El código
anterior generaba el consecutivo con ``len(facturas) + 1`` y ``zfill(6)``:

- No verificaba el rango autorizado (una empresa con rango 990000000–995000000
  emitía ``SETP000001``, fuera del rango → rechazo).
- ``len() + 1`` no es contiguo: al borrar o al emitir en paralelo reutiliza
  números ya usados.
- ``zfill(6)`` producía 6 dígitos cuando la DIAN autoriza rangos de 9.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from sap_colombia import dbutil
from sap_colombia import database as db
from sap_colombia.cufe_calculator import normalizar_numero


class ErrorNumeracion(ValueError):
    """El número a asignar no cumple la autorización de la DIAN."""


@dataclass
class Consecutivo:
    prefijo: str
    numero: int
    completo: str
    numero_str: str

    @property
    def numero_8(self) -> str:
        """Número sin prefijo, en 8 dígitos (formato del CUFE/QR)."""
        return str(self.numero).zfill(8)


def _ancho_rango(desde, hasta) -> int:
    """Ancho en dígitos del rango autorizado."""
    return max(len(str(int(desde))), len(str(int(hasta))))


def siguiente_consecutivo(
    empresa: dict,
    tabla: str = "facturas",
    *,
    usar_maximo: bool = True,
    conn=None,
) -> Consecutivo:
    """Calcula el siguiente consecutivo válido dentro del rango autorizado.

    Args:
        empresa: Fila de ``empresas`` con ``prefijo_resolucion``,
            ``rango_desde`` y ``rango_hasta``.
        tabla: Tabla donde se cuentan los documentos del mismo prefijo
            (``facturas``, ``notas_credito``, ``notas_debito``,
            ``documentos_soporte``, ``nominas``).
        usar_maximo: Si es ``True`` parte del ``MAX`` histórico en vez del
            conteo de filas (evita reutilizar números tras borrados).

    Raises:
        ErrorNumeracion: si falta la autorización o el rango se agotó.
    """
    prefijo = (empresa.get("prefijo_resolucion") or "").strip()
    if not prefijo:
        raise ErrorNumeracion(
            "La empresa no tiene prefijo de resolución DIAN configurado "
            "(empresas.prefijo_resolucion).")

    desde_raw = empresa.get("rango_desde")
    hasta_raw = empresa.get("rango_hasta")
    if desde_raw in (None, "") or hasta_raw in (None, ""):
        raise ErrorNumeracion(
            "La empresa no tiene rango de numeración autorizado por la DIAN "
            "(empresas.rango_desde / rango_hasta). No se puede emitir.")
    try:
        desde = int(normalizar_numero(desde_raw))
        hasta = int(normalizar_numero(hasta_raw))
    except (InvalidOperation, ValueError):
        raise ErrorNumeracion(f"Rango de numeración inválido: {desde_raw}–{hasta_raw}")
    if desde <= 0 or hasta < desde:
        raise ErrorNumeracion(f"Rango de numeración incoherente: {desde}–{hasta}")

    propio = conn is not None
    c = conn or db.get_connection()
    try:
        if usar_maximo:
            row = dbutil.query(
                c,
                f"SELECT MAX(CAST(SUBSTRING(consecutivo FROM '[0-9]+$') AS INTEGER)) AS mx "
                f"FROM {tabla} WHERE consecutivo LIKE ?",
                (f"{prefijo}%",),
            ).fetchone()
        else:
            row = dbutil.query(
                c,
                f"SELECT COUNT(*) AS n FROM {tabla} WHERE consecutivo LIKE ?",
                (f"{prefijo}%",),
            ).fetchone()
        if row is None:
            siguiente = desde
        elif usar_maximo:
            mx = row["mx"]
            siguiente = desde if mx is None else max(desde, int(mx) + 1)
        else:
            siguiente = desde + int(row["n"])
    finally:
        if not propio:
            c.close()

    if siguiente > hasta:
        raise ErrorNumeracion(
            f"Se agotó el rango de numeración autorizado ({prefijo} "
            f"{desde}–{hasta}). Solicite una nueva resolución a la DIAN.")

    ancho = _ancho_rango(desde, hasta)
    numero_str = str(siguiente).zfill(ancho)
    return Consecutivo(
        prefijo=prefijo,
        numero=siguiente,
        completo=f"{prefijo}{numero_str}",
        numero_str=numero_str,
    )


def validar_consecutivo(consecutivo: str, empresa: dict) -> None:
    """Verifica que un consecutivo ya asignado cae en el rango autorizado."""
    prefijo = (empresa.get("prefijo_resolucion") or "").strip()
    if not consecutivo.startswith(prefijo):
        raise ErrorNumeracion(
            f"El consecutivo {consecutivo!r} no usa el prefijo autorizado {prefijo!r}")
    digitos = normalizar_numero(consecutivo[len(prefijo):])
    if not digitos:
        raise ErrorNumeracion(f"El consecutivo {consecutivo!r} no tiene número")
    numero = int(digitos)
    desde = int(normalizar_numero(empresa.get("rango_desde") or 0))
    hasta = int(normalizar_numero(empresa.get("rango_hasta") or 0))
    if desde and numero < desde:
        raise ErrorNumeracion(
            f"El consecutivo {consecutivo!r} está por debajo del rango autorizado "
            f"({desde}–{hasta})")
    if hasta and numero > hasta:
        raise ErrorNumeracion(
            f"El consecutivo {consecutivo!r} excede el rango autorizado "
            f"({desde}–{hasta})")


def puede_emitir_sin_certificado(empresa: dict) -> bool:
    """¿Se permite emitir sin certificado digital?

    En ambiente de producción (2) **no**: toda factura electrónica de venta
    debe ir firmada digitalmente. En habilitación (1) la DIAN también exige
    firma, pero se permite operar sin certificado solo si el documento es de
    prueba; aquí se es estricto en producción y permisivo en habilitación.
    """
    return str(empresa.get("tipo_ambiente") or "2").strip() != "2"


def exigir_certificado_para_emitir(empresa: dict) -> None:
    """Lanza si la emisión en producción no tiene certificado configurado."""
    if puede_emitir_sin_certificado(empresa):
        return
    if not empresa.get("ruta_certificado"):
        raise ErrorNumeracion(
            "No se puede emitir en ambiente de producción sin certificado digital. "
            "Configure empresas.ruta_certificado y empresas.password_certificado."
        )