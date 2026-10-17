"""Cálculo de KPIs gerenciales para el Dashboard del ERP SAP Colombia."""

from datetime import date, datetime, timezone
from sap_colombia import dbutil
from decimal import Decimal

import sap_colombia.database as db
from sap_colombia.accounting_engine import to_decimal


def _mes_actual() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _saldo_total() -> Decimal:
    conn = db.get_connection()
    try:
        row = dbutil.query(conn, 
            "SELECT COALESCE(SUM(saldo_pendiente::numeric), 0) AS saldo FROM facturas"
        ).fetchone()
        return to_decimal(row["saldo"])
    finally:
        conn.close()


def _vencidas_total(fecha_corte: str) -> Decimal:
    conn = db.get_connection()
    try:
        row = dbutil.query(conn, 
            """SELECT COALESCE(SUM(saldo_pendiente::numeric), 0) AS saldo FROM facturas
                WHERE fecha_vencimiento < ? AND saldo_pendiente::numeric > 0""",
            (fecha_corte,),
        ).fetchone()
        return to_decimal(row["saldo"])
    finally:
        conn.close()


def _ventas_mes(mes: str) -> Decimal:
    conn = db.get_connection()
    try:
        row = dbutil.query(conn, 
            "SELECT COALESCE(SUM(total_factura::numeric), 0) AS total FROM facturas WHERE to_char(fecha::date, 'YYYY-MM') = ?",
            (mes,),
        ).fetchone()
        return to_decimal(row["total"])
    finally:
        conn.close()


def _ticket_promedio(mes: str) -> Decimal:
    conn = db.get_connection()
    try:
        row = dbutil.query(conn, 
            "SELECT COUNT(*) AS cnt, COALESCE(AVG(total_factura::numeric), 0) AS avg FROM facturas WHERE to_char(fecha::date, 'YYYY-MM') = ?",
            (mes,),
        ).fetchone()
        return to_decimal(row["avg"]) if row["cnt"] else Decimal("0.00")
    finally:
        conn.close()


def _alertas_stock() -> list[dict]:
    conn = db.get_connection()
    try:
        rows = dbutil.query(conn, 
            """SELECT p.codigo AS producto_codigo, p.descripcion AS descripcion,
                      p.stock_minimo, s.bodega_codigo, s.cantidad
               FROM productos p
               LEFT JOIN stock_actual s ON p.codigo = s.producto_codigo
               WHERE p.stock_minimo > 0
               ORDER BY p.codigo"""
        ).fetchall()
        alertas = []
        for row in rows:
            stock = to_decimal(row["cantidad"]) if row["cantidad"] else Decimal("0")
            minimo = int(row["stock_minimo"] or 0)
            if stock <= minimo:
                alertas.append(
                    {
                        "producto_codigo": row["producto_codigo"],
                        "descripcion": row["descripcion"],
                        "bodega_codigo": row["bodega_codigo"],
                        "cantidad": str(stock),
                        "stock_minimo": minimo,
                    }
                )
        return alertas
    finally:
        conn.close()


def _asientos_mes(mes: str) -> int:
    conn = db.get_connection()
    try:
        row = dbutil.query(conn, 
            "SELECT COUNT(*) AS cnt FROM asientos_contables WHERE to_char(fecha::date, 'YYYY-MM') = ?",
            (mes,),
        ).fetchone()
        return row["cnt"]
    finally:
        conn.close()


def calcular_kpis(fecha_corte: str | None = None) -> dict:
    fecha_corte = fecha_corte or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    mes = _mes_actual()

    ventas = _ventas_mes(mes)
    ticket = _ticket_promedio(mes)
    cartera = _saldo_total()
    vencidas = _vencidas_total(fecha_corte)

    conn = db.get_connection()
    try:
        stock_total_valor = to_decimal(
            dbutil.query(conn, 
                "SELECT COALESCE(SUM(cantidad::numeric * costo_promedio::numeric), 0) AS total FROM stock_actual"
            ).fetchone()["total"]
        )
        stock_total_cantidad = to_decimal(
            dbutil.query(conn, 
                "SELECT COALESCE(SUM(cantidad::numeric), 0) AS total FROM stock_actual"
            ).fetchone()["total"]
        )
    finally:
        conn.close()

    return {
        "fecha_corte": str(fecha_corte),
        "ventas_mes": str(ventas),
        "cartera_pendiente": str(cartera),
        "cartera_vencida": str(vencidas),
        "ticket_promedio": str(ticket),
        "stock": {
            "total_cantidad": str(stock_total_cantidad),
            "total_valor": str(stock_total_valor),
            "stock_alertas": _alertas_stock(),
        },
        "contabilidad": {
            "asientos_mes": _asientos_mes(mes),
        },
    }
