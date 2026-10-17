"""Pago de nómina mediante recibo de caja al empleado."""

from datetime import datetime
from decimal import Decimal

import sap_colombia.database as db
from sap_colombia.accounting_engine import contabilizar_pago_nomina, to_decimal


class PayrollPaymentError(ValueError):
    pass


def pagar_nomina(nomina_id: int, medio_pago: str = "EFECTIVO", monto: Decimal | None = None) -> dict:
    """Crea el recibo de caja de pago al empleado por el neto_pagar."""
    nomina = db.get_nomina_by_id(nomina_id)
    if not nomina:
        raise PayrollPaymentError(f"Nómina {nomina_id} no encontrada.")
    if nomina.get("estado_pago") == "PAGADA":
        raise PayrollPaymentError(f"Nómina {nomina_id} ya fue pagada.")

    neto = to_decimal(nomina["neto_pagar"])
    if monto is None:
        monto = neto
    else:
        monto = to_decimal(monto)

    if monto <= 0:
        raise PayrollPaymentError("El monto de pago debe ser mayor que cero.")
    if monto > neto:
        raise PayrollPaymentError(f"Monto {monto} excede el neto_pagar {neto}.")

    now = datetime.now()
    datos_recibo = {
        "nomina_id": nomina_id,
        "consecutivo": nomina["consecutivo"],
        "prefijo": nomina.get("prefijo", "NOM"),
        "empleado_id": nomina["empleado_id"],
        "monto": str(monto),
        "medio_pago": medio_pago.upper(),
        "neto_pagar": str(neto),
        "fecha": now.strftime("%Y-%m-%d"),
        "created_at": now.isoformat(),
    }

    asiento = contabilizar_pago_nomina(datos_recibo)
    db.actualizar_estado_pago_nomina(nomina_id, "PAGADA")

    return {
        "recibo": datos_recibo,
        "asiento": asiento,
        "estado": "PAGADA",
    }
