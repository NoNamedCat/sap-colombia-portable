"""Borradores y Liquidadores de Formularios Tributarios Oficiales DIAN.

Implementa los algoritmos de agregación fiscal conforme a la normativa tributaria colombiana:
1. Formulario 300: Declaración del Impuesto sobre las Ventas (IVA) — Periodicidad Bimestral/Cuatrimestral.
2. Formulario 350: Declaración de Retenciones en la Fuente — Periodicidad Mensual.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from sap_colombia import dbutil
from sap_colombia import database as db


def _to_decimal(val) -> Decimal:
    try:
        return Decimal(str(val or "0.00").strip())
    except Exception:
        return Decimal("0.00")


def obtener_rango_fechas_bimestre(bimestre: int, anio: int) -> tuple[str, str]:
    """Retorna fecha_inicio y fecha_fin (YYYY-MM-DD) para un bimestre dado."""
    if bimestre < 1 or bimestre > 6:
        raise ValueError("El bimestre debe estar comprendido entre 1 y 6.")

    mes_inicio = (bimestre - 1) * 2 + 1
    mes_fin = mes_inicio + 1

    # Días finales por mes
    dias_mes = {
        2: 29 if (anio % 4 == 0 and (anio % 100 != 0 or anio % 400 == 0)) else 28,
        4: 30,
        6: 30,
        8: 31,
        10: 31,
        12: 31,
    }
    dia_fin = dias_mes[mes_fin]

    fecha_inicio = f"{anio}-{mes_inicio:02d}-01"
    fecha_fin = f"{anio}-{mes_fin:02d}-{dia_fin:02d}"
    return fecha_inicio, fecha_fin


def obtener_rango_fechas_mes(mes: int, anio: int) -> tuple[str, str]:
    """Retorna fecha_inicio y fecha_fin (YYYY-MM-DD) para un mes dado."""
    if mes < 1 or mes > 12:
        raise ValueError("El mes debe estar comprendido entre 1 y 12.")

    dias_mes = {
        1: 31,
        2: 29 if (anio % 4 == 0 and (anio % 100 != 0 or anio % 400 == 0)) else 28,
        3: 31,
        4: 30,
        5: 31,
        6: 30,
        7: 31,
        8: 31,
        9: 30,
        10: 31,
        11: 30,
        12: 31,
    }
    dia_fin = dias_mes[mes]
    return f"{anio}-{mes:02d}-01", f"{anio}-{mes:02d}-{dia_fin:02d}"


def generar_formulario_300(bimestre: int, anio: int, empresa_id: int | None = None) -> dict:
    """Genera el borrador sugerido del Formulario 300 DIAN (IVA)."""
    empresa_id = empresa_id or db.get_current_empresa_id() or 1
    empresa = db.get_empresa(empresa_id) or {}
    fecha_inicio, fecha_fin = obtener_rango_fechas_bimestre(bimestre, anio)

    conn = db.get_connection()
    try:
        # Facturas de Venta emitidas en el periodo
        facturas = dbutil.query(
            conn,
            """SELECT * FROM facturas 
               WHERE empresa_id = ? AND fecha >= ? AND fecha <= ? AND estado_dian != 'RECHAZADA'""",
            (empresa_id, fecha_inicio, fecha_fin),
        ).fetchall()

        # Facturas de Compra causadas en el periodo (IVA Descontable)
        compras = dbutil.query(
            conn,
            """SELECT * FROM facturas_compra 
               WHERE empresa_id = ? AND fecha >= ? AND fecha <= ?""",
            (empresa_id, fecha_inicio, fecha_fin),
        ).fetchall()

        renglon_27_base_19 = Decimal("0.00")
        renglon_28_base_5 = Decimal("0.00")
        renglon_29_base_0 = Decimal("0.00")
        renglon_59_iva_19 = Decimal("0.00")
        renglon_60_iva_5 = Decimal("0.00")

        for f in facturas:
            iva_19 = _to_decimal(f.get("iva_19"))
            iva_5 = _to_decimal(f.get("iva_5"))
            iva_0 = _to_decimal(f.get("iva_0"))
            subtotal = _to_decimal(f.get("subtotal"))

            if iva_19 > 0:
                renglon_27_base_19 += (iva_19 / Decimal("0.19")).quantize(Decimal("0.01"))
                renglon_59_iva_19 += iva_19
            elif iva_5 > 0:
                renglon_28_base_5 += (iva_5 / Decimal("0.05")).quantize(Decimal("0.01"))
                renglon_60_iva_5 += iva_5
            elif iva_0 > 0 or (iva_19 == 0 and iva_5 == 0):
                renglon_29_base_0 += subtotal

        renglon_34_total_ingresos = renglon_27_base_19 + renglon_28_base_5 + renglon_29_base_0
        renglon_41_ingresos_netos = renglon_34_total_ingresos
        renglon_67_total_iva_generado = renglon_59_iva_19 + renglon_60_iva_5

        # IVA Descontable de compras
        renglon_78_iva_descontable = Decimal("0.00")
        for c in compras:
            renglon_78_iva_descontable += _to_decimal(c.get("total_iva"))

        renglon_82_total_descontables = renglon_78_iva_descontable

        if renglon_67_total_iva_generado >= renglon_82_total_descontables:
            renglon_83_saldo_a_pagar = renglon_67_total_iva_generado - renglon_82_total_descontables
            renglon_84_saldo_a_favor = Decimal("0.00")
        else:
            renglon_83_saldo_a_pagar = Decimal("0.00")
            renglon_84_saldo_a_favor = renglon_82_total_descontables - renglon_67_total_iva_generado

        return {
            "formulario": "300",
            "titulo": "Declaración del Impuesto sobre las Ventas - IVA",
            "empresa_nit": empresa.get("nit"),
            "empresa_razon_social": empresa.get("razon_social"),
            "anio": anio,
            "bimestre": bimestre,
            "periodo": f"Bimestre {bimestre} ({fecha_inicio} a {fecha_fin})",
            "renglones": {
                "27_ingresos_gravados_19": str(renglon_27_base_19),
                "28_ingresos_gravados_5": str(renglon_28_base_5),
                "29_ingresos_no_gravados_excluidos": str(renglon_29_base_0),
                "34_total_ingresos_brutos": str(renglon_34_total_ingresos),
                "41_total_ingresos_netos": str(renglon_41_ingresos_netos),
                "59_impuesto_generado_19": str(renglon_59_iva_19),
                "60_impuesto_generado_5": str(renglon_60_iva_5),
                "67_total_impuesto_generado": str(renglon_67_total_iva_generado),
                "78_iva_descontable_compras": str(renglon_78_iva_descontable),
                "82_total_impuestos_descontables": str(renglon_82_total_descontables),
                "83_saldo_a_pagar": str(renglon_83_saldo_a_pagar),
                "84_saldo_a_favor": str(renglon_84_saldo_a_favor),
            },
            "conteo_facturas_venta": len(facturas),
            "conteo_facturas_compra": len(compras),
        }
    finally:
        conn.close()


def generar_formulario_350(mes: int, anio: int, empresa_id: int | None = None) -> dict:
    """Genera el borrador sugerido del Formulario 350 DIAN (Retención en la fuente)."""
    empresa_id = empresa_id or db.get_current_empresa_id() or 1
    empresa = db.get_empresa(empresa_id) or {}
    fecha_inicio, fecha_fin = obtener_rango_fechas_mes(mes, anio)

    conn = db.get_connection()
    try:
        # Movimientos contables de retenciones practicadas en el mes
        # Cuentas 2365 (Retefuente) y 2368 / 2367 (ReteIVA)
        movimientos = dbutil.query(
            conn,
            """SELECT m.*, a.fecha
               FROM movimientos_contables m
               JOIN asientos_contables a ON m.asiento_id = a.id
               WHERE a.fecha >= ? AND a.fecha <= ?
                 AND (m.cuenta_codigo LIKE ? OR m.cuenta_codigo LIKE ? OR m.cuenta_codigo LIKE ?)
                 AND CAST(m.credito AS NUMERIC) > 0""",
            (fecha_inicio, fecha_fin, '2365%', '2368%', '2367%'),
        ).fetchall()

        renglon_50_compras = Decimal("0.00")
        renglon_51_servicios = Decimal("0.00")
        renglon_52_honorarios = Decimal("0.00")
        renglon_53_laboral = Decimal("0.00")
        renglon_84_reteiva = Decimal("0.00")
        otras_retenciones = Decimal("0.00")

        for m in movimientos:
            cta = str(m["cuenta_codigo"])
            credito = _to_decimal(m["credito"])

            if cta == "236540":
                renglon_50_compras += credito
            elif cta in ("236525", "236530"):
                renglon_51_servicios += credito
            elif cta in ("236515", "236520"):
                renglon_52_honorarios += credito
            elif cta == "236505":
                renglon_53_laboral += credito
            elif cta in ("236802", "236701", "240807"):
                renglon_84_reteiva += credito
            else:
                otras_retenciones += credito

        # Si no hubo movimientos contables explícitos, también inspeccionar documentos soporte y facturas de compra
        if len(movimientos) == 0:
            docs_soporte = dbutil.query(
                conn,
                "SELECT retefuente FROM documentos_soporte WHERE fecha >= ? AND fecha <= ?",
                (fecha_inicio, fecha_fin),
            ).fetchall()
            for ds in docs_soporte:
                renglon_50_compras += _to_decimal(ds.get("retefuente"))

            fc_rows = dbutil.query(
                conn,
                "SELECT retefuente, reteiva FROM facturas_compra WHERE fecha >= ? AND fecha <= ?",
                (fecha_inicio, fecha_fin),
            ).fetchall()
            for fc in fc_rows:
                renglon_50_compras += _to_decimal(fc.get("retefuente"))
                renglon_84_reteiva += _to_decimal(fc.get("reteiva"))

        renglon_87_total_retenciones = (
            renglon_50_compras
            + renglon_51_servicios
            + renglon_52_honorarios
            + renglon_53_laboral
            + renglon_84_reteiva
            + otras_retenciones
        )

        return {
            "formulario": "350",
            "titulo": "Declaración de Retención en la Fuente",
            "empresa_nit": empresa.get("nit"),
            "empresa_razon_social": empresa.get("razon_social"),
            "anio": anio,
            "mes": mes,
            "periodo": f"Mes {mes:02d}/{anio} ({fecha_inicio} a {fecha_fin})",
            "renglones": {
                "50_retencion_compras": str(renglon_50_compras),
                "51_retencion_servicios": str(renglon_51_servicios),
                "52_retencion_honorarios": str(renglon_52_honorarios),
                "53_retencion_pagos_laborales": str(renglon_53_laboral),
                "84_retenciones_iva": str(renglon_84_reteiva),
                "otras_retenciones": str(otras_retenciones),
                "87_total_retenciones": str(renglon_87_total_retenciones),
                "saldo_a_pagar": str(renglon_87_total_retenciones),
            },
            "conteo_movimientos": len(movimientos),
        }
    finally:
        conn.close()
