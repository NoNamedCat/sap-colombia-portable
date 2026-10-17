"""Módulo de cartera y recaudos de SAP Colombia."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import sap_colombia.database as db
from sap_colombia.accounting_engine import contabilizar_recibo_caja, to_decimal

CATEGORIAS_CARTERA = ("corriente", "1_a_30", "31_a_60", "61_a_90", "mas_90")


def _parse_fecha(valor: str | None) -> date | None:
    if not valor:
        return None
    try:
        return datetime.strptime(str(valor), "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _clasificar(dias_vencimiento: int) -> str:
    if dias_vencimiento <= 0:
        return "corriente"
    if dias_vencimiento <= 30:
        return "1_a_30"
    if dias_vencimiento <= 60:
        return "31_a_60"
    if dias_vencimiento <= 90:
        return "61_a_90"
    return "mas_90"


def calcular_edades_cartera(fecha_corte: str | None = None) -> dict:
    fecha_corte = fecha_corte or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    corte = _parse_fecha(fecha_corte)
    if corte is None:
        corte = date.today()

    resumen = {categoria: Decimal("0.00") for categoria in CATEGORIAS_CARTERA}
    detalle: list[dict] = []
    total_saldo = Decimal("0.00")

    for factura in db.get_facturas():
        saldo = to_decimal(factura.get("saldo_pendiente"))
        if saldo <= 0:
            continue

        fecha_vencimiento = _parse_fecha(factura.get("fecha_vencimiento"))
        if fecha_vencimiento is None:
            fecha_emision = _parse_fecha(factura.get("fecha"))
            plazo_dias = int(factura.get("plazo_dias") or 30)
            if fecha_emision is not None:
                fecha_vencimiento = fecha_emision + timedelta(days=plazo_dias)

        if fecha_vencimiento is None:
            dias_vencimiento = 0
        else:
            dias_vencimiento = (corte - fecha_vencimiento).days

        categoria = _clasificar(dias_vencimiento)
        resumen[categoria] += saldo
        total_saldo += saldo

        detalle.append(
            {
                "id": factura.get("id"),
                "consecutivo": factura.get("consecutivo"),
                "prefijo": factura.get("prefijo"),
                "cliente_nit": factura.get("cliente_nit"),
                "saldo_pendiente": str(saldo),
                "fecha_vencimiento": factura.get("fecha_vencimiento"),
                "dias_vencimiento": dias_vencimiento,
                "categoria": categoria,
            }
        )

    return {
        "fecha_corte": str(corte),
        "resumen": {categoria: str(monto) for categoria, monto in resumen.items()},
        "detalle": detalle,
        "total_saldo": str(total_saldo),
    }


def registrar_recibo_caja(
    factura_id: int,
    monto,
    medio_pago: str = "EFECTIVO",
    referencia: str = "",
    observaciones: str = "",
    conn=None,
) -> dict:
    factura = db.get_factura_by_id(factura_id)
    if factura is None:
        raise ValueError(f"Factura {factura_id} no encontrada")

    monto_decimal = to_decimal(monto)
    if monto_decimal <= 0:
        raise ValueError("El monto del recibo debe ser mayor a 0")

    saldo_pendiente = to_decimal(factura.get("saldo_pendiente"))
    if monto_decimal > saldo_pendiente:
        raise ValueError(
            f"El monto {monto_decimal} no puede ser superior al saldo pendiente {saldo_pendiente}"
        )

    ultimo_numero = 0
    for recibo in db.get_recibos_caja():
        numero = str(recibo.get("numero") or "")
        if numero.startswith("RC-"):
            try:
                ultimo_numero = max(ultimo_numero, int(numero.split("-")[-1]))
            except ValueError:
                continue
    numero = f"RC-{ultimo_numero + 1:04d}"
    fecha = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    datos_recibo = {
        "numero": numero,
        "fecha": fecha,
        "cliente_nit": str(factura.get("cliente_nit", "")),
        "factura_id": factura_id,
        "monto": str(monto_decimal),
        "medio_pago": str(medio_pago).upper(),
        "referencia": referencia,
        "observaciones": observaciones,
    }
    recibo_id = db.guardar_recibo_caja(datos_recibo, conn=conn)

    nuevo_saldo = saldo_pendiente - monto_decimal
    nuevo_estado = "PAGADA_TOTAL" if nuevo_saldo == 0 else "PAGADA_PARCIAL"
    db.actualizar_saldo_factura(factura_id, str(nuevo_saldo), nuevo_estado, conn=conn)

    recibo = {
        "id": recibo_id,
        **datos_recibo,
    }
    asiento = contabilizar_recibo_caja(recibo, conn=conn)

    return {
        "recibo": recibo,
        "nuevo_saldo": str(nuevo_saldo),
        "estado_cartera": nuevo_estado,
        "asiento": asiento,
    }
