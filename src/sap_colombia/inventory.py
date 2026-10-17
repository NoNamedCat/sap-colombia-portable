"""Kárdex de Inventario Permanente Multibodega con Costeo Promedio Ponderado."""

import os
from sap_colombia import dbutil
import sys
from decimal import Decimal
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(BASE_DIR)
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from sap_colombia import database as db


class InventarioError(Exception):
    pass


def _to_decimal(valor) -> Decimal:
    return Decimal(str(valor))


def registrar_entrada(
    producto_codigo: str,
    bodega_codigo: str,
    cantidad: Decimal,
    costo_unitario: Decimal,
    referencia_documento: str = "",
    fecha: str | None = None,
    conn=None,
    contabilizar: bool = False,
    proveedor_nit: str = "",
    lote: str | None = None,
    fecha_vencimiento: str | None = None,
) -> dict:
    if cantidad <= 0:
        raise InventarioError("La cantidad de entrada debe ser mayor a cero.")
    if costo_unitario < 0:
        raise InventarioError("El costo unitario no puede ser negativo.")

    fecha = fecha or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    propia_conexion = conn is None
    conn = conn or db.get_connection()
    try:
        stock = db._fetch_one(
            conn,
            "SELECT * FROM stock_actual WHERE producto_codigo = ? AND bodega_codigo = ?",
            (producto_codigo, bodega_codigo),
        )

        if stock:
            cantidad_anterior = _to_decimal(stock["cantidad"])
            costo_anterior = _to_decimal(stock["costo_promedio"])
            valor_total_anterior = cantidad_anterior * costo_anterior
            valor_total_entrada = cantidad * costo_unitario
            nueva_cantidad = cantidad_anterior + cantidad
            nuevo_costo_promedio = (valor_total_anterior + valor_total_entrada) / nueva_cantidad
        else:
            nueva_cantidad = cantidad
            nuevo_costo_promedio = costo_unitario

        dbutil.query(conn, 
            """INSERT INTO stock_actual (producto_codigo, bodega_codigo, cantidad, costo_promedio, lote, fecha_vencimiento)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT (producto_codigo, bodega_codigo) DO UPDATE SET
                cantidad = EXCLUDED.cantidad, costo_promedio = EXCLUDED.costo_promedio,
                lote = COALESCE(EXCLUDED.lote, stock_actual.lote),
                fecha_vencimiento = COALESCE(EXCLUDED.fecha_vencimiento, stock_actual.fecha_vencimiento)""",
            (producto_codigo, bodega_codigo, str(nueva_cantidad), str(nuevo_costo_promedio), lote, fecha_vencimiento),
        )

        saldo = nueva_cantidad
        dbutil.query(conn, 
            """INSERT INTO kardex
               (fecha, producto_codigo, bodega_codigo, tipo_movimiento, referencia_documento,
                cantidad_entrada, cantidad_salida, saldo_cantidad, costo_unitario, costo_total_saldo, created_at, lote, fecha_vencimiento)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                fecha,
                producto_codigo,
                bodega_codigo,
                "ENTRADA",
                referencia_documento,
                str(cantidad),
                "0",
                str(saldo),
                str(nuevo_costo_promedio),
                str(saldo * nuevo_costo_promedio),
                datetime.now(timezone.utc).isoformat(),
                lote,
                fecha_vencimiento,
            ),
        )

        if contabilizar:
            from sap_colombia import inventory_accounting
            inventory_accounting.contabilizar_entrada_inventario(
                producto_codigo=producto_codigo,
                cantidad=cantidad,
                costo_unitario=costo_unitario,
                referencia_documento=referencia_documento,
                fecha=fecha,
                proveedor_nit=proveedor_nit,
                conn=conn,
            )

        if propia_conexion:
            conn.commit()
        return {
            "producto_codigo": producto_codigo,
            "bodega_codigo": bodega_codigo,
            "cantidad_entrada": str(cantidad),
            "costo_unitario": str(costo_unitario),
            "saldo_nuevo": str(nueva_cantidad),
            "costo_promedio": str(nuevo_costo_promedio),
            "costo_total_saldo": str(nueva_cantidad * nuevo_costo_promedio),
        }
    finally:
        # Solo se cierra si esta función abrió la conexión. Antes el bloque
        # decía "pass": la conexión se filtraba en cada entrada/devolución.
        if propia_conexion:
            conn.close()


def registrar_salida(
    producto_codigo: str,
    bodega_codigo: str,
    cantidad: Decimal,
    referencia_documento: str = "",
    fecha: str | None = None,
    conn=None,
) -> dict:
    if cantidad <= 0:
        raise InventarioError("La cantidad de salida debe ser mayor a cero.")

    fecha = fecha or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    propia_conexion = conn is None
    conn = conn or db.get_connection()
    try:
        stock = db._fetch_one(
            conn,
            "SELECT * FROM stock_actual WHERE producto_codigo = ? AND bodega_codigo = ?",
            (producto_codigo, bodega_codigo),
        )

        if not stock:
            raise InventarioError(
                f"No hay existencias de {producto_codigo} en bodega {bodega_codigo}."
            )

        cantidad_actual = _to_decimal(stock["cantidad"])
        costo_promedio = _to_decimal(stock["costo_promedio"])

        if cantidad > cantidad_actual:
            raise InventarioError(
                f"Saldo insuficiente. Disponible: {cantidad_actual}, solicitado: {cantidad}."
            )

        nueva_cantidad = cantidad_actual - cantidad
        nuevo_costo_total = nueva_cantidad * costo_promedio

        dbutil.query(conn, 
            """UPDATE stock_actual SET cantidad = ?, costo_promedio = ?
               WHERE producto_codigo = ? AND bodega_codigo = ?""",
            (str(nueva_cantidad), str(costo_promedio), producto_codigo, bodega_codigo),
        )

        dbutil.query(conn, 
            """INSERT INTO kardex
               (fecha, producto_codigo, bodega_codigo, tipo_movimiento, referencia_documento,
                cantidad_entrada, cantidad_salida, saldo_cantidad, costo_unitario, costo_total_saldo, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                fecha,
                producto_codigo,
                bodega_codigo,
                "SALIDA",
                referencia_documento,
                "0",
                str(cantidad),
                str(nueva_cantidad),
                str(costo_promedio),
                str(nuevo_costo_total),
                datetime.now(timezone.utc).isoformat(),
            ),
        )

        if propia_conexion:
            conn.commit()
        return {
            "producto_codigo": producto_codigo,
            "bodega_codigo": bodega_codigo,
            "cantidad_salida": str(cantidad),
            "costo_unitario": str(costo_promedio),
            "saldo_nuevo": str(nueva_cantidad),
            "costo_total_saldo": str(nuevo_costo_total),
        }
    finally:
        if propia_conexion:
            conn.close()


def registrar_devolucion(
    producto_codigo: str,
    bodega_codigo: str,
    cantidad: Decimal,
    referencia_documento: str = "",
    fecha: str | None = None,
    conn=None,
) -> dict:
    if cantidad <= 0:
        raise InventarioError("La cantidad de devolución debe ser mayor a cero.")

    fecha = fecha or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    propia_conexion = conn is None
    conn = conn or db.get_connection()
    try:
        stock = db._fetch_one(
            conn,
            "SELECT * FROM stock_actual WHERE producto_codigo = ? AND bodega_codigo = ?",
            (producto_codigo, bodega_codigo),
        )

        costo_promedio = _to_decimal(stock["costo_promedio"]) if stock else Decimal("0")
        if stock:
            cantidad_anterior = _to_decimal(stock["cantidad"])
            nueva_cantidad = cantidad_anterior + cantidad
        else:
            nueva_cantidad = cantidad

        dbutil.query(conn, 
            """INSERT INTO stock_actual (producto_codigo, bodega_codigo, cantidad, costo_promedio)
                VALUES (?, ?, ?, ?)
                ON CONFLICT (producto_codigo, bodega_codigo) DO UPDATE SET
                cantidad = EXCLUDED.cantidad, costo_promedio = EXCLUDED.costo_promedio""",
            (producto_codigo, bodega_codigo, str(nueva_cantidad), str(costo_promedio)),
        )

        dbutil.query(conn, 
            """INSERT INTO kardex
               (fecha, producto_codigo, bodega_codigo, tipo_movimiento, referencia_documento,
                cantidad_entrada, cantidad_salida, saldo_cantidad, costo_unitario, costo_total_saldo, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                fecha,
                producto_codigo,
                bodega_codigo,
                "DEVOLUCION",
                referencia_documento,
                "0",
                str(cantidad),
                str(nueva_cantidad),
                str(costo_promedio),
                str(nueva_cantidad * costo_promedio),
                datetime.now(timezone.utc).isoformat(),
            ),
        )

        if propia_conexion:
            conn.commit()
        return {
            "producto_codigo": producto_codigo,
            "bodega_codigo": bodega_codigo,
            "cantidad_salida": str(cantidad),
            "costo_unitario": str(costo_promedio),
            "saldo_nuevo": str(nueva_cantidad),
            "costo_total_saldo": str(nueva_cantidad * costo_promedio),
        }
    finally:
        # Solo se cierra si esta función abrió la conexión. Antes el bloque
        # decía "pass": la conexión se filtraba en cada entrada/devolución.
        if propia_conexion:
            conn.close()


def registrar_factura(
    factura_id: int,
    lineas: list[dict],
    bodega_codigo: str = "BODEGA-01",
    fecha: str | None = None,
    conn=None,
    contabilizar: bool = True,
) -> dict:
    """Descuenta el inventario de las líneas vendidas.

    Antes de este cambio el kárdex se movía pero **no se generaba asiento**: el
    balance mostraba inventario 0 y la utilidad no recognía el costo de venta.
    """
    from sap_colombia import inventory_accounting

    costo_total = Decimal("0")
    detalle = []
    for linea in lineas:
        producto_codigo = linea.get("producto_codigo")
        cantidad = Decimal(str(linea.get("cantidad", 0)))
        if cantidad > 0:
            movimiento = registrar_salida(
                producto_codigo=producto_codigo,
                bodega_codigo=bodega_codigo,
                cantidad=cantidad,
                referencia_documento=f"FACT-{factura_id}",
                fecha=fecha,
                conn=conn,
            )
            costo_linea = cantidad * _to_decimal(movimiento["costo_unitario"])
            costo_total += costo_linea
            detalle.append({"producto_codigo": producto_codigo, "costo": str(costo_linea)})
            if contabilizar and costo_linea > 0:
                inventory_accounting.contabilizar_salida_venta(
                    producto_codigo=producto_codigo,
                    cantidad=cantidad,
                    costo_unitario=_to_decimal(movimiento["costo_unitario"]),
                    referencia_documento=f"FACT-{factura_id}",
                    fecha=fecha,
                    conn=conn,
                )
    return {"status": "ok", "factura_id": factura_id,
            "costo_ventas": str(costo_total.quantize(Decimal("0.01"))),
            "detalle": detalle}


def registrar_nota_credito(
    nc_id: int,
    lineas: list[dict],
    bodega_codigo: str = "BODEGA-01",
    fecha: str | None = None,
    conn=None,
    contabilizar: bool = True,
) -> dict:
    """Reingresa al inventario lo devuelto por nota crédito, con su asiento."""
    from sap_colombia import inventory_accounting

    costo_total = Decimal("0")
    for linea in lineas:
        producto_codigo = linea.get("producto_codigo")
        cantidad = Decimal(str(linea.get("cantidad", 0)))
        if cantidad > 0:
            movimiento = registrar_devolucion(
                producto_codigo=producto_codigo,
                bodega_codigo=bodega_codigo,
                cantidad=cantidad,
                referencia_documento=f"NC-{nc_id}",
                fecha=fecha,
                conn=conn,
            )
            costo_linea = cantidad * _to_decimal(movimiento["costo_unitario"])
            costo_total += costo_linea
            if contabilizar and costo_linea > 0:
                inventory_accounting.contabilizar_devolucion_venta(
                    producto_codigo=producto_codigo,
                    cantidad=cantidad,
                    costo_unitario=_to_decimal(movimiento["costo_unitario"]),
                    referencia_documento=f"NC-{nc_id}",
                    fecha=fecha,
                    conn=conn,
                )
    return {"status": "ok", "nc_id": nc_id,
            "costo_reingreso": str(costo_total.quantize(Decimal("0.01")))}


def trasladar_bodega(
    producto_codigo: str,
    bodega_origen: str,
    bodega_destino: str,
    cantidad: Decimal,
    lote: str | None = None,
    fecha: str | None = None,
    conn=None,
) -> dict:
    """Traslada existencias entre dos bodegas de forma atómica."""
    if bodega_origen == bodega_destino:
        raise InventarioError("La bodega de origen y destino deben ser diferentes.")
    if cantidad <= 0:
        raise InventarioError("La cantidad a trasladar debe ser mayor a cero.")

    fecha = fecha or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    ref = f"TRASLADO {bodega_origen} -> {bodega_destino}"

    propia_conexion = conn is None
    conn = conn or db.get_connection()
    try:
        salida = registrar_salida(
            producto_codigo=producto_codigo,
            bodega_codigo=bodega_origen,
            cantidad=cantidad,
            referencia_documento=ref,
            fecha=fecha,
            conn=conn,
        )
        costo_unitario = _to_decimal(salida["costo_unitario"])
        entrada = registrar_entrada(
            producto_codigo=producto_codigo,
            bodega_codigo=bodega_destino,
            cantidad=cantidad,
            costo_unitario=costo_unitario,
            referencia_documento=ref,
            fecha=fecha,
            conn=conn,
            lote=lote,
        )
        if propia_conexion:
            conn.commit()

        return {
            "producto_codigo": producto_codigo,
            "bodega_origen": bodega_origen,
            "bodega_destino": bodega_destino,
            "cantidad": str(cantidad),
            "costo_unitario": str(costo_unitario),
            "lote": lote,
            "fecha": fecha,
        }
    except Exception:
        if propia_conexion:
            conn.rollback()
        raise
    finally:
        if propia_conexion:
            conn.close()
