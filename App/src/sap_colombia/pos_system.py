"""Sistema POS Electrónico y Arqueo de Caja (Resolución DIAN 000165 de 2023).

Implementa:
1. Gestión de cajas registradoras y terminales de venta.
2. Apertura de turno con fondo inicial (base de caja).
3. Cierre de turno y arqueo ciego/cuadrado con cálculo de descuadre (sobrante/faltante).
4. Generación de tirilla térmica ESC/POS de 80mm y 58mm con QR, CUFE y resolución DIAN.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sap_colombia import dbutil
from sap_colombia import database as db


def _to_decimal(val) -> Decimal:
    try:
        return Decimal(str(val or "0.00").strip())
    except Exception:
        return Decimal("0.00")


def crear_caja(nombre: str, ubicacion: str = "", empresa_id: int | None = None) -> dict:
    """Crea una nueva caja POS."""
    empresa_id = empresa_id or db.get_current_empresa_id() or 1
    conn = db.get_connection()
    try:
        ahora = datetime.now(timezone.utc).isoformat()
        cursor = dbutil.query(
            conn,
            """INSERT INTO pos_cajas (empresa_id, nombre, ubicacion, activa, created_at)
               VALUES (?, ?, ?, 1, ?) RETURNING id""",
            (empresa_id, nombre.strip(), ubicacion.strip(), ahora),
        )
        row = cursor.fetchone()
        caja_id = row["id"] if row else 1
        conn.commit()
        return {
            "id": caja_id,
            "empresa_id": empresa_id,
            "nombre": nombre.strip(),
            "ubicacion": ubicacion.strip(),
            "activa": 1,
        }
    finally:
        conn.close()


def listar_cajas(empresa_id: int | None = None) -> list[dict]:
    empresa_id = empresa_id or db.get_current_empresa_id() or 1
    conn = db.get_connection()
    try:
        rows = dbutil.query(
            conn,
            "SELECT * FROM pos_cajas WHERE empresa_id = ? ORDER BY id ASC",
            (empresa_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def abrir_caja(caja_id: int, usuario_id: int | None = None, monto_inicial: Decimal | str = "0.00") -> dict:
    """Abre un nuevo turno de caja con una base en efectivo."""
    conn = db.get_connection()
    try:
        # Validar si hay sesión abierta
        abierta = dbutil.query(
            conn,
            "SELECT * FROM pos_sesiones WHERE caja_id = ? AND estado = 'ABIERTA'",
            (caja_id,),
        ).fetchone()
        if abierta:
            raise ValueError(f"La caja #{caja_id} ya tiene un turno abierto (#{abierta['id']}).")

        monto_ini_dec = _to_decimal(monto_inicial)
        ahora = datetime.now(timezone.utc).isoformat()
        cursor = dbutil.query(
            conn,
            """INSERT INTO pos_sesiones (
                caja_id, usuario_id, fecha_apertura, monto_inicial,
                total_ventas_efectivo, total_ventas_tarjeta, total_ventas_transferencia,
                total_esperado, total_real, diferencia, estado
            ) VALUES (?, ?, ?, ?, '0.00', '0.00', '0.00', ?, '0.00', '0.00', 'ABIERTA')
            RETURNING id""",
            (caja_id, usuario_id, ahora, str(monto_ini_dec), str(monto_ini_dec)),
        )
        row = cursor.fetchone()
        sesion_id = row["id"] if row else 1
        conn.commit()

        return {
            "id": sesion_id,
            "caja_id": caja_id,
            "usuario_id": usuario_id,
            "fecha_apertura": ahora,
            "monto_inicial": str(monto_ini_dec),
            "estado": "ABIERTA",
        }
    finally:
        conn.close()


def registrar_venta_pos(
    sesion_id: int,
    monto: Decimal | str,
    medio_pago: str = "EFECTIVO",
) -> None:
    """Acumula la venta realizada dentro de la sesión activa de caja."""
    monto_dec = _to_decimal(monto)
    medio = (medio_pago or "EFECTIVO").upper()
    conn = db.get_connection()
    try:
        sesion = dbutil.query(conn, "SELECT * FROM pos_sesiones WHERE id = ?", (sesion_id,)).fetchone()
        if not sesion or sesion["estado"] != "ABIERTA":
            return

        col_venta = "total_ventas_efectivo"
        if medio in ("TARJETA", "CREDITO", "DEBITO"):
            col_venta = "total_ventas_tarjeta"
        elif medio in ("TRANSFERENCIA", "CONSIGNACION", "NEQUI", "DAVIPLATA"):
            col_venta = "total_ventas_transferencia"

        total_previo = _to_decimal(sesion[col_venta])
        nuevo_total = total_previo + monto_dec
        total_esperado = _to_decimal(sesion["monto_inicial"]) + (
            (nuevo_total if col_venta == "total_ventas_efectivo" else _to_decimal(sesion["total_ventas_efectivo"]))
        )

        dbutil.query(
            conn,
            f"UPDATE pos_sesiones SET {col_venta} = ?, total_esperado = ? WHERE id = ?",
            (str(nuevo_total), str(total_esperado), sesion_id),
        )
        conn.commit()
    finally:
        conn.close()


def cerrar_caja(
    sesion_id: int,
    total_real: Decimal | str,
    observaciones: str = "",
) -> dict:
    """Cierra la sesión y genera el arqueo de caja calculando diferencias."""
    conn = db.get_connection()
    try:
        sesion = dbutil.query(conn, "SELECT * FROM pos_sesiones WHERE id = ?", (sesion_id,)).fetchone()
        if not sesion:
            raise ValueError(f"Sesión #{sesion_id} no encontrada.")
        if sesion["estado"] == "CERRADA":
            raise ValueError(f"La sesión #{sesion_id} ya fue cerrada previamente.")

        real_dec = _to_decimal(total_real)
        esperado_dec = _to_decimal(sesion["total_esperado"])
        diferencia = real_dec - esperado_dec

        ahora = datetime.now(timezone.utc).isoformat()
        dbutil.query(
            conn,
            """UPDATE pos_sesiones SET
                fecha_cierre = ?, total_real = ?, diferencia = ?,
                observaciones = ?, estado = 'CERRADA'
               WHERE id = ?""",
            (ahora, str(real_dec), str(diferencia), observaciones.strip(), sesion_id),
        )
        conn.commit()

        return {
            "id": sesion_id,
            "caja_id": sesion["caja_id"],
            "monto_inicial": sesion["monto_inicial"],
            "total_ventas_efectivo": sesion["total_ventas_efectivo"],
            "total_ventas_tarjeta": sesion["total_ventas_tarjeta"],
            "total_ventas_transferencia": sesion["total_ventas_transferencia"],
            "total_esperado": str(esperado_dec),
            "total_real": str(real_dec),
            "diferencia": str(diferencia),
            "estado": "CERRADA",
            "descuadre_tipo": "EXACTO" if diferencia == 0 else ("SOBRANTE" if diferencia > 0 else "FALTANTE"),
            "fecha_cierre": ahora,
            "observaciones": observaciones.strip(),
        }
    finally:
        conn.close()


def listar_sesiones_caja(caja_id: int | None = None) -> list[dict]:
    conn = db.get_connection()
    try:
        sql = "SELECT s.*, c.nombre as caja_nombre FROM pos_sesiones s JOIN pos_cajas c ON s.caja_id = c.id"
        params = []
        if caja_id:
            sql += " WHERE s.caja_id = ?"
            params.append(caja_id)
        sql += " ORDER BY s.id DESC"
        rows = dbutil.query(conn, sql, tuple(params)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def generar_ticket_pos(factura_id: int, ancho_mm: int = 80) -> dict:
    """Genera la estructura de tirilla térmica POS según Resolución DIAN 000165/2023."""
    factura = db.get_factura_by_id(factura_id)
    if not factura:
        raise ValueError(f"Factura #{factura_id} no encontrada.")

    lineas = db.get_lineas_factura(factura_id)
    empresa = db.get_empresa(factura.get("empresa_id", 1)) or {}
    cliente = db.get_cliente_by_nit(factura.get("cliente_nit", "")) or {}

    ancho_caracteres = 48 if ancho_mm == 80 else 32
    sep_line = "=" * ancho_caracteres
    sep_dash = "-" * ancho_caracteres

    # Armar texto plano estándar para impresora térmica ESC/POS
    lineas_ticket = [
        sep_line,
        empresa.get("razon_social", "EMPRESA SAS").center(ancho_caracteres),
        f"NIT: {empresa.get('nit', '')}-{empresa.get('dv', '1')}".center(ancho_caracteres),
        empresa.get("direccion", "").center(ancho_caracteres),
        f"{empresa.get('municipio', '')} - {empresa.get('departamento', '')}".center(ancho_caracteres),
        sep_dash,
        "DOCUMENTO EQUIVALENTE ELECTRONICO POS".center(ancho_caracteres),
        f"Resolución DIAN No. {empresa.get('resolucion_dian', '18760000001')}".center(ancho_caracteres),
        f"Prefijo {factura.get('prefijo', 'POS')} del {empresa.get('rango_desde', 1)} al {empresa.get('rango_hasta', 999999)}".center(ancho_caracteres),
        sep_dash,
        f"Ticket No: {factura.get('prefijo', '')}-{factura.get('consecutivo', '')}",
        f"Fecha: {factura.get('fecha', '')} {factura.get('hora', '')}",
        f"Cliente: {cliente.get('razon_social', 'CONSUMIDOR FINAL')}",
        f"NIT/CC: {factura.get('cliente_nit', '222222222222')}",
        sep_dash,
        f"{'CANT':<5} {'DESCRIPCION':<22} {'TOTAL':>10}",
        sep_dash,
    ]

    for item in lineas:
        desc = (item.get("descripcion") or "Item")[:22]
        cant = item.get("cantidad", "1")
        sub = item.get("subtotal", "0.00")
        lineas_ticket.append(f"{str(cant):<5} {desc:<22} {str(sub):>10}")

    lineas_ticket.extend([
        sep_dash,
        f"{'SUBTOTAL:':<25} ${factura.get('subtotal', '0.00'):>15}",
        f"{'IVA 19%:':<25} ${factura.get('iva_19', '0.00'):>15}",
        f"{'IVA 5%:':<25} ${factura.get('iva_5', '0.00'):>15}",
        sep_line,
        f"{'TOTAL A PAGAR:':<25} ${factura.get('total_factura', '0.00'):>15}",
        sep_line,
        "CUFE / CUDE:",
        factura.get("cufe", "")[:ancho_caracteres],
        factura.get("cufe", "")[ancho_caracteres:ancho_caracteres*2],
        "",
        "Gracias por su compra!".center(ancho_caracteres),
        sep_line,
    ])

    texto_ticket = "\n".join(lineas_ticket)

    return {
        "factura_id": factura_id,
        "ancho_mm": ancho_mm,
        "ancho_caracteres": ancho_caracteres,
        "texto_ticket": texto_ticket,
        "qr": factura.get("qr", ""),
        "cufe": factura.get("cufe", ""),
        "empresa": empresa,
        "total": factura.get("total_factura", "0.00"),
    }
