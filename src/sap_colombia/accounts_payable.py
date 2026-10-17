"""Módulo de Cuentas por Pagar (CxP) y Comprobantes de Egreso (CE).

Gestiona:
1. Cartera y saldos pendientes con proveedores.
2. Análisis de vencimiento por edades (Corriente, 1-30, 31-60, 61-90, +90 días).
3. Emisión de Comprobantes de Egreso (Pago en Efectivo, Transferencia o Cheque).
4. Asiento contable automático de pago (Cancelación de pasivo 220505 vs 111005/110505).
"""

from __future__ import annotations

from datetime import datetime, timezone, date
from decimal import Decimal

from sap_colombia import dbutil
from sap_colombia import database as db
from sap_colombia import accounting_engine


def _to_decimal(val) -> Decimal:
    try:
        return Decimal(str(val or "0.00").strip())
    except Exception:
        return Decimal("0.00")


def registrar_comprobante_egreso(
    datos_egreso: dict,
    empresa_id: int | None = None,
    auto_contabilizar: bool = True,
    conn=None,
) -> dict:
    """Registra un comprobante de egreso, amortiza la CxP y causa contablemente."""
    empresa_id = empresa_id or db.get_current_empresa_id() or 1
    monto = _to_decimal(datos_egreso.get("monto", "0.00"))
    if monto <= 0:
        raise ValueError("El monto del comprobante de egreso debe ser superior a cero.")

    propia_conexion = conn is None
    conn = conn or db.get_connection()
    try:
        consecutivo = str(datos_egreso.get("consecutivo") or "").strip()
        if not consecutivo:
            max_row = dbutil.query(
                conn,
                "SELECT MAX(id) AS max_id FROM comprobantes_egreso WHERE empresa_id = ?",
                (empresa_id,),
            ).fetchone()
            next_num = ((max_row["max_id"] or 0) if max_row else 0) + 1
            consecutivo = f"{next_num:06d}"

        fecha = datos_egreso.get("fecha") or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        proveedor_nit = str(datos_egreso.get("proveedor_nit", "")).strip()
        proveedor_nombre = str(datos_egreso.get("proveedor_nombre", "Proveedor")).strip()
        medio_pago = (datos_egreso.get("medio_pago") or "TRANSFERENCIA").upper()
        cuenta_origen = datos_egreso.get("cuenta_origen") or ("110505" if medio_pago == "EFECTIVO" else "111005")
        factura_compra_id = datos_egreso.get("factura_compra_id")
        observaciones = str(datos_egreso.get("observaciones") or "")

        ahora = datetime.now(timezone.utc).isoformat()
        cursor = dbutil.query(
            conn,
            """INSERT INTO comprobantes_egreso (
                empresa_id, consecutivo, fecha, proveedor_nit, proveedor_nombre,
                monto, medio_pago, cuenta_origen, factura_compra_id, observaciones, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING id""",
            (
                empresa_id,
                consecutivo,
                fecha,
                proveedor_nit,
                proveedor_nombre,
                str(monto),
                medio_pago,
                cuenta_origen,
                factura_compra_id,
                observaciones,
                ahora,
            ),
        )
        row = cursor.fetchone()
        egreso_id = row["id"] if row else 1

        # Amortizar saldo en cuentas_por_pagar si aplica
        if factura_compra_id:
            cxp = dbutil.query(
                conn,
                "SELECT * FROM cuentas_por_pagar WHERE factura_compra_id = ? AND empresa_id = ?",
                (factura_compra_id, empresa_id),
            ).fetchone()
            if cxp:
                saldo_actual = _to_decimal(cxp["saldo_pendiente"])
                nuevo_saldo = saldo_actual - monto
                if nuevo_saldo <= 0:
                    nuevo_saldo = Decimal("0.00")
                    nuevo_estado = "PAGADA"
                else:
                    nuevo_estado = "PARCIAL"

                dbutil.query(
                    conn,
                    "UPDATE cuentas_por_pagar SET saldo_pendiente = ?, estado = ? WHERE id = ?",
                    (str(nuevo_saldo), nuevo_estado, cxp["id"]),
                )

        egreso_data = {
            "id": egreso_id,
            "empresa_id": empresa_id,
            "consecutivo": consecutivo,
            "fecha": fecha,
            "proveedor_nit": proveedor_nit,
            "proveedor_nombre": proveedor_nombre,
            "monto": str(monto),
            "medio_pago": medio_pago,
            "cuenta_origen": cuenta_origen,
            "factura_compra_id": factura_compra_id,
            "observaciones": observaciones,
        }

        # Causación contable automática
        if auto_contabilizar:
            accounting_engine.contabilizar_comprobante_egreso(egreso_data, conn=conn)

        if propia_conexion:
            conn.commit()

        return egreso_data
    finally:
        if propia_conexion:
            conn.close()


def obtener_edades_cxp(empresa_id: int | None = None) -> dict:
    """Calcula el análisis de vencimiento de cuentas por pagar en tramos estándar."""
    empresa_id = empresa_id or db.get_current_empresa_id() or 1
    conn = db.get_connection()
    try:
        rows = dbutil.query(
            conn,
            """SELECT c.*, f.prefijo, f.consecutivo, f.cufe
               FROM cuentas_por_pagar c
               LEFT JOIN facturas_compra f ON c.factura_compra_id = f.id
               WHERE c.empresa_id = ? AND c.estado IN ('PENDIENTE', 'PARCIAL')
               ORDER BY c.fecha_vencimiento ASC""",
            (empresa_id,),
        ).fetchall()

        hoy = date.today()
        corriente = Decimal("0.00")
        rango_1_30 = Decimal("0.00")
        rango_31_60 = Decimal("0.00")
        rango_61_90 = Decimal("0.00")
        mas_90 = Decimal("0.00")
        total_general = Decimal("0.00")

        detalle_facturas = []

        for r in rows:
            factura = dict(r)
            saldo = _to_decimal(factura.get("saldo_pendiente"))
            if saldo <= Decimal("0.00"):
                continue

            venc_str = factura.get("fecha_vencimiento") or factura.get("fecha_emision")
            try:
                venc_date = datetime.strptime(venc_str[:10], "%Y-%m-%d").date()
            except Exception:
                venc_date = hoy

            dias_mora = (hoy - venc_date).days
            factura["dias_vencido"] = max(0, dias_mora)
            factura["es_vencida"] = dias_mora > 0

            if dias_mora <= 0:
                corriente += saldo
                factura["rango_vencimiento"] = "CORRIENTE"
            elif 1 <= dias_mora <= 30:
                rango_1_30 += saldo
                factura["rango_vencimiento"] = "1-30"
            elif 31 <= dias_mora <= 60:
                rango_31_60 += saldo
                factura["rango_vencimiento"] = "31-60"
            elif 61 <= dias_mora <= 90:
                rango_61_90 += saldo
                factura["rango_vencimiento"] = "61-90"
            else:
                mas_90 += saldo
                factura["rango_vencimiento"] = "+90"

            total_general += saldo
            detalle_facturas.append(factura)

        return {
            "corriente": str(corriente),
            "1_30": str(rango_1_30),
            "31_60": str(rango_31_60),
            "61_90": str(rango_61_90),
            "mas_90": str(mas_90),
            "total_deuda": str(total_general),
            "facturas": detalle_facturas,
        }
    finally:
        conn.close()


def listar_comprobantes_egreso(empresa_id: int | None = None) -> list[dict]:
    empresa_id = empresa_id or db.get_current_empresa_id() or 1
    conn = db.get_connection()
    try:
        rows = dbutil.query(
            conn,
            "SELECT * FROM comprobantes_egreso WHERE empresa_id = ? ORDER BY id DESC",
            (empresa_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def listar_cuentas_por_pagar(empresa_id: int | None = None, solo_pendientes: bool = False) -> list[dict]:
    empresa_id = empresa_id or db.get_current_empresa_id() or 1
    conn = db.get_connection()
    try:
        sql = """SELECT c.*, f.prefijo, f.consecutivo, f.proveedor_nombre
                 FROM cuentas_por_pagar c
                 LEFT JOIN facturas_compra f ON c.factura_compra_id = f.id
                 WHERE c.empresa_id = ?"""
        params = [empresa_id]
        if solo_pendientes:
            sql += " AND c.estado IN ('PENDIENTE', 'PARCIAL')"
        sql += " ORDER BY c.id DESC"
        rows = dbutil.query(conn, sql, tuple(params)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
