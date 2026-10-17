"""Pruebas TDD para Recibo de Caja de pago de nómina."""

import os
from sap_colombia import dbutil
import sys
from decimal import Decimal

import pytest

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(BASE_DIR)
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from sap_colombia import database as db
from sap_colombia import payroll
from sap_colombia.payroll_payment import pagar_nomina, PayrollPaymentError


@pytest.fixture
def setup_db():
    db.init_db()
    conn = db.get_connection()
    with conn:
        dbutil.query(conn, "DELETE FROM nominas")
        dbutil.query(conn, "DELETE FROM empleados")
        dbutil.query(conn, "DELETE FROM movimientos_contables")
        dbutil.query(conn, "DELETE FROM asientos_contables")
    conn.close()
    yield
    conn = db.get_connection()
    with conn:
        dbutil.query(conn, "DELETE FROM nominas")
        dbutil.query(conn, "DELETE FROM empleados")
        dbutil.query(conn, "DELETE FROM movimientos_contables")
        dbutil.query(conn, "DELETE FROM asientos_contables")
    conn.close()


@pytest.fixture
def nomina_emitida(setup_db):
    emp_id = db.guardar_empleado({
        "tipo_documento": "CC",
        "documento": "123456789",
        "nombres": "Juan Carlos",
        "apellidos": "Pérez Rodríguez",
        "salario_base": "1200000.00",
        "auxilio_transporte": "149095.00",
        "activo": 1,
        "created_at": "2026-01-01T00:00:00",
    })
    result = payroll.emitir_nomina(
        empleado_id=emp_id,
        periodo_inicio="2026-01-01",
        periodo_fin="2026-01-31",
    )
    return result["nomina"]


def test_pagar_nomina_crea_recibo_caja(nomina_emitida):
    result = pagar_nomina(nomina_id=nomina_emitida["id"], medio_pago="EFECTIVO")
    assert result["recibo"]["monto"] == nomina_emitida["neto_pagar"]
    assert result["estado"] == "PAGADA"
    assert result["asiento"]["total_debito"] == nomina_emitida["neto_pagar"]
    assert result["asiento"]["total_credito"] == nomina_emitida["neto_pagar"]
    stored = db.get_nomina_by_id(nomina_emitida["id"])
    assert stored["estado_pago"] == "PAGADA"


def test_pagar_nomina_excede_neto(nomina_emitida):
    with pytest.raises(PayrollPaymentError):
        pagar_nomina(
            nomina_id=nomina_emitida["id"],
            medio_pago="EFECTIVO",
            monto=Decimal("99999999.00"),
        )


def test_pagar_nomina_doble_pago(nomina_emitida):
    pagar_nomina(nomina_id=nomina_emitida["id"], medio_pago="EFECTIVO")
    with pytest.raises(PayrollPaymentError):
        pagar_nomina(nomina_id=nomina_emitida["id"], medio_pago="EFECTIVO")
