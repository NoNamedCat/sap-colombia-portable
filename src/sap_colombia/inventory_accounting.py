"""Contabilización del inventario: del kárdex a la partida doble.

El kárdex llevaba existencias correctamente pero **no generaba ningún asiento
contable**: el balance mostraba inventario 0 mientras el kárdex mostraba stock,
y el costo de ventas nunca se reconocía, sobreestimando la utilidad.

Este módulo enlaza los movimientos de inventario con el libro contable:

- Entrada de mercancía (compra):  D 1435 Inventario / C 2205 Proveedores
- Salida por venta:               D 5305 Costo de ventas / C 1435 Inventario
- Devolución de venta:            D 1435 Inventario / C 5305 Costo de ventas
- Ajuste de inventario físico:    D/C según el signo de la diferencia

Gestión de conexiones: si el llamador entrega una ``conn`` se reutiliza y **no**
se cierra (para que el conjunto}kárdex + asiento sea atómico); si no, se delega
en :func:`sap_colombia.database.guardar_asiento`, que abre, confirma y cierra.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from sap_colombia import database as db
from sap_colombia import dbutil

CUENTA_INVENTARIO = "143501"        # Mercancías no fabricadas por la empresa
CUENTA_COSTO_VENTAS = "530501"      # Costo de ventas
CUENTA_PROVEEDORES = "220505"       # Proveedores
CUENTA_AJUSTE_SOBRANTE = "413595"   # Ingreso no operacional (ajuste favorable)
CUENTA_AJUSTE_FALTANTE = "511595"   # Gasto no operacional (ajuste desfavorable)

CENTAVOS = Decimal("0.01")


class ErrorInventarioContable(Exception):
    """Error al contabilizar un movimiento de inventario."""


def _q2(valor) -> Decimal:
    return Decimal(str(valor)).quantize(CENTAVOS, rounding=ROUND_HALF_UP)


def hoy() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _movimiento(cuenta: str, concepto: str, debito, credito, tercero_nit: str = "") -> dict:
    return {
        "cuenta_codigo": cuenta,
        "concepto": concepto,
        "debito": str(_q2(debito)),
        "credito": str(_q2(credito)),
        "tercero_nit": tercero_nit or None,
    }


def _guardar(tipo_documento: str, numero: str, fecha: str, glosa: str,
             movimientos: list[dict], documento_id=None, conn=None) -> int:
    """Valida la partida doble y persiste el asiento.

    La validación es obligatoria: un asiento descuadrado nunca llega al libro.
    """
    from sap_colombia.accounting_engine import validar_partida_doble
    cuadrado, td, tc = validar_partida_doble(movimientos)
    if not cuadrado:
        raise ErrorInventarioContable(
            f"Asiento descuadrado en '{glosa}': débitos {td} vs créditos {tc}"
        )
    return db.guardar_asiento(
        {
            "numero_comprobante": numero,
            "fecha": fecha,
            "tipo_documento": tipo_documento,
            "documento_id": documento_id,
            "glosa": glosa,
            "total_debito": str(td),
            "total_credito": str(tc),
        },
        movimientos,
        conn=conn,
    )


def contabilizar_entrada_inventario(
    producto_codigo: str,
    cantidad: Decimal,
    costo_unitario: Decimal,
    referencia_documento: str = "",
    fecha: str | None = None,
    proveedor_nit: str = "",
    conn=None,
) -> int | None:
    """Asiento por la compra de mercancía.

    D 1435 Inventario | C 2205 Proveedores
    """
    total = _q2(cantidad * costo_unitario)
    if total <= 0:
        return None
    concepto = f"Compra de inventario {producto_codigo} ({referencia_documento})"
    movimientos = [
        _movimiento(CUENTA_INVENTARIO, concepto, total, 0),
        _movimiento(CUENTA_PROVEEDORES, concepto, 0, total, proveedor_nit),
    ]
    return _guardar(
        "COMPRA_INVENTARIO",
        f"INV-ENTRADA-{referencia_documento or 'S/N'}-{producto_codigo}",
        fecha or hoy(), concepto, movimientos, conn=conn,
    )


def contabilizar_salida_venta(
    producto_codigo: str,
    cantidad: Decimal,
    costo_unitario: Decimal,
    referencia_documento: str = "",
    fecha: str | None = None,
    conn=None,
) -> int | None:
    """Asiento por el costo de una venta.

    D 5305 Costo de ventas | C 1435 Inventario
    """
    total = _q2(cantidad * costo_unitario)
    if total <= 0:
        return None
    concepto = f"Costo de venta {producto_codigo} ({referencia_documento})"
    movimientos = [
        _movimiento(CUENTA_COSTO_VENTAS, concepto, total, 0),
        _movimiento(CUENTA_INVENTARIO, concepto, 0, total),
    ]
    return _guardar(
        "COSTO_VENTA",
        f"INV-SALIDA-{referencia_documento or 'S/N'}-{producto_codigo}",
        fecha or hoy(), concepto, movimientos, conn=conn,
    )


def contabilizar_devolucion_venta(
    producto_codigo: str,
    cantidad: Decimal,
    costo_unitario: Decimal,
    referencia_documento: str = "",
    fecha: str | None = None,
    conn=None,
) -> int | None:
    """Asiento por la devolución de una venta.

    D 1435 Inventario | C 5305 Costo de ventas
    """
    total = _q2(cantidad * costo_unitario)
    if total <= 0:
        return None
    concepto = f"Devolución de venta {producto_codigo} ({referencia_documento})"
    movimientos = [
        _movimiento(CUENTA_INVENTARIO, concepto, total, 0),
        _movimiento(CUENTA_COSTO_VENTAS, concepto, 0, total),
    ]
    return _guardar(
        "DEVOLUCION_VENTA",
        f"INV-DEV-{referencia_documento or 'S/N'}-{producto_codigo}",
        fecha or hoy(), concepto, movimientos, conn=conn,
    )


def contabilizar_ajuste_inventario(
    producto_codigo: str,
    diferencia_cantidad: Decimal,
    costo_unitario: Decimal,
    referencia_documento: str = "TOMA-INVENTARIO",
    fecha: str | None = None,
    conn=None,
) -> int | None:
    """Asiento por el ajuste resultante de un inventario físico.

    Diferencia positiva (sobrante):  D 1435 / C 413595
    Diferencia negativa (faltante):  D 511595 / C 1435
    """
    total = _q2(diferencia_cantidad * costo_unitario)
    if total == 0:
        return None
    concepto = f"Ajuste de inventario {producto_codigo} ({referencia_documento})"
    if diferencia_cantidad > 0:
        movimientos = [
            _movimiento(CUENTA_INVENTARIO, concepto, total, 0),
            _movimiento(CUENTA_AJUSTE_SOBRANTE, concepto, 0, total),
        ]
    else:
        movimientos = [
            _movimiento(CUENTA_AJUSTE_FALTANTE, concepto, -total, 0),
            _movimiento(CUENTA_INVENTARIO, concepto, 0, -total),
        ]
    return _guardar(
        "AJUSTE_INVENTARIO",
        f"INV-AJUSTE-{referencia_documento or 'TOMA'}-{producto_codigo}",
        fecha or hoy(), concepto, movimientos, conn=conn,
    )


# ---------------------------------------------------------------------------
# Consultas de conciliación
# ---------------------------------------------------------------------------

def saldo_inventario() -> Decimal:
    """Valor total del inventario según el costo promedio ponderado móvil."""
    conn = db.get_connection()
    try:
        row = dbutil.query(
            conn,
            "SELECT COALESCE(SUM(CAST(cantidad AS NUMERIC) * CAST(costo_promedio AS NUMERIC)), 0) AS v "
            "FROM stock_actual",
        ).fetchone()
    finally:
        conn.close()
    return _q2(row["v"] if row else 0)


def saldo_contable_inventario() -> Decimal:
    """Saldo de la cuenta 1435 según los movimientos del libro."""
    conn = db.get_connection()
    try:
        row = dbutil.query(
            conn,
            "SELECT COALESCE(SUM(CAST(debito AS NUMERIC) - CAST(credito AS NUMERIC)), 0) AS v "
            "FROM movimientos_contables WHERE cuenta_codigo = ?",
            (CUENTA_INVENTARIO,),
        ).fetchone()
    finally:
        conn.close()
    return _q2(row["v"] if row else 0)


def costo_ventas_periodo(fecha_desde: str, fecha_hasta: str) -> Decimal:
    """Costo de ventas reconocido en un periodo."""
    conn = db.get_connection()
    try:
        row = dbutil.query(
            conn,
            "SELECT COALESCE(SUM(CAST(m.debito AS NUMERIC)), 0) - "
            "       COALESCE(SUM(CAST(m.credito AS NUMERIC)), 0) AS v "
            "FROM movimientos_contables m "
            "JOIN asientos_contables a ON a.id = m.asiento_id "
            "WHERE m.cuenta_codigo = ? AND a.fecha BETWEEN ? AND ?",
            (CUENTA_COSTO_VENTAS, fecha_desde, fecha_hasta),
        ).fetchone()
    finally:
        conn.close()
    return _q2(row["v"] if row else 0)


def conciliar_inventario() -> list[dict]:
    """Compara el valor del kárdex con el saldo de la cuenta 1435.

    Un inventario con diferencia entre el valor físico y el libro es un
    hallazgo de auditoría; la diferencia debe estar explicada por ajustes.
    """
    contable = saldo_contable_inventario()
    fisico = saldo_inventario()
    return [{
        "cuenta": CUENTA_INVENTARIO,
        "saldo_contable": str(contable),
        "saldo_kardex": str(fisico),
        "diferencia": str(_q2(fisico - contable)),
        "conciliado": fisico == contable,
    }]