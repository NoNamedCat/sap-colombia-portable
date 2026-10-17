"""Módulo de Listas de Precios Múltiples (Detal, Mayorista, Distribuidor).

Permite:
1. Crear y administrar diversas listas de precios vinculadas a la empresa.
2. Asignar precios diferenciados por producto en cada lista.
3. Consultar rápidamente el precio de un producto según la lista seleccionada.
"""

from __future__ import annotations

from decimal import Decimal
from sap_colombia import dbutil
from sap_colombia import database as db


def _to_decimal(val) -> Decimal:
    try:
        return Decimal(str(val or "0.00").strip())
    except Exception:
        return Decimal("0.00")


def crear_lista_precios(nombre: str, descripcion: str = "", empresa_id: int | None = None) -> dict:
    empresa_id = empresa_id or db.get_current_empresa_id() or 1
    conn = db.get_connection()
    try:
        cursor = dbutil.query(
            conn,
            """INSERT INTO listas_precios (empresa_id, nombre, descripcion, activa)
               VALUES (?, ?, ?, 1) RETURNING id""",
            (empresa_id, nombre.strip(), descripcion.strip()),
        )
        row = cursor.fetchone()
        lista_id = row["id"] if row else 1
        conn.commit()
        return {
            "id": lista_id,
            "empresa_id": empresa_id,
            "nombre": nombre.strip(),
            "descripcion": descripcion.strip(),
            "activa": 1,
        }
    finally:
        conn.close()


def listar_listas_precios(empresa_id: int | None = None) -> list[dict]:
    empresa_id = empresa_id or db.get_current_empresa_id() or 1
    conn = db.get_connection()
    try:
        rows = dbutil.query(
            conn,
            "SELECT * FROM listas_precios WHERE empresa_id = ? ORDER BY id ASC",
            (empresa_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def asignar_precio_producto(
    lista_id: int,
    producto_codigo: str,
    precio: Decimal | str,
) -> dict:
    precio_dec = _to_decimal(precio)
    conn = db.get_connection()
    try:
        dbutil.query(
            conn,
            """INSERT INTO precios_productos (lista_id, producto_codigo, precio)
               VALUES (?, ?, ?)
               ON CONFLICT (lista_id, producto_codigo) DO UPDATE SET precio = EXCLUDED.precio""",
            (lista_id, producto_codigo.strip(), str(precio_dec)),
        )
        conn.commit()
        return {
            "lista_id": lista_id,
            "producto_codigo": producto_codigo.strip(),
            "precio": str(precio_dec),
        }
    finally:
        conn.close()


def obtener_precio_producto(lista_id: int, producto_codigo: str) -> Decimal | None:
    conn = db.get_connection()
    try:
        row = dbutil.query(
            conn,
            "SELECT precio FROM precios_productos WHERE lista_id = ? AND producto_codigo = ?",
            (lista_id, producto_codigo.strip()),
        ).fetchone()
        if row and row["precio"] is not None:
            return _to_decimal(row["precio"])
        return None
    finally:
        conn.close()


def listar_precios_lista(lista_id: int) -> list[dict]:
    conn = db.get_connection()
    try:
        rows = dbutil.query(
            conn,
            """SELECT pp.*, p.descripcion, p.tarifa_iva
               FROM precios_productos pp
               LEFT JOIN productos p ON pp.producto_codigo = p.codigo
               WHERE pp.lista_id = ? ORDER BY pp.producto_codigo ASC""",
            (lista_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
