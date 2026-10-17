"""Pruebas TDD para Nómina Electrónica DIAN (CUNE) — Res. 000013 de 2021."""

import hashlib
from sap_colombia import dbutil
import os
import sys
from decimal import Decimal

import pytest

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(BASE_DIR)
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from sap_colombia import database as db
from sap_colombia import payroll
from sap_colombia.payroll import (
    PayrollError,
    calcular_nomina,
    generar_cune,
    construir_xml_nomina,
    liquidar_nomina,
    emitir_nomina,
)
from sap_colombia.accounting_engine import contabilizar_nomina


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
def empleado(setup_db):
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
    return emp_id


# ── Pruebas de Cálculo (tasas legales colombianas) ──────────────────────────

AUXILIO_LEGAL = "149095.00"   # valor vigente paramétrico


def test_calculo_basico_sin_extras():
    """Salario 1,2 SMMLV sin extras, con prestaciones provisionadas."""
    calculo = calcular_nomina(
        salario_base=Decimal("1200000.00"),
        auxilio_transporte=Decimal(AUXILIO_LEGAL),
        horas_extras=Decimal("0"),
        valor_hora_extra=Decimal("0"),
        bonificaciones=Decimal("0"),
    )
    # Devengos: salario + auxilio + cesantías + intereses + prima
    assert calculo["cesantias"] == "99960.00"          # 8,33 % del salario
    # Prima de servicios: 30% del salario anual prorrateado al mes
    # (1200000 * 12 * 0.30) / 12 = 360000
    assert Decimal(calculo["prima_servicios"]) > 0
    # Intereses cesantías: 12% sobre acumulado anual de cesantías
    # (99960 * 12 * 0.12) / 12 = 1199.52
    assert Decimal(calculo["intereses_cesantias"]) > 0
    # Deducciones del empleado: 4 % + 4 %
    assert calculo["ded_salud"] == "48000.00"
    assert calculo["ded_pension"] == "48000.00"
    # Con un salario de 1,2 SMMLV no hay retención (umbral: 2 SMMLV)
    assert calculo["ded_retencion"] == "0.00"


def test_tasas_patronales_segun_ley():
    """Pensión 12 %, salud 8,5 %, SENA 2 %, ICBF 3 %, caja 4 %, ARL por riesgo."""
    calculo = calcular_nomina(
        salario_base=Decimal("1200000.00"),
        auxilio_transporte=Decimal("0.00"),
        horas_extras=Decimal("0"), valor_hora_extra=Decimal("0"),
        bonificaciones=Decimal("0"),
    )
    ibc = Decimal("1200000.00")
    assert calculo["empleador_salud"] == str((ibc * Decimal("0.085")).quantize(Decimal("0.01")))
    assert calculo["empleador_pension"] == str((ibc * Decimal("0.12")).quantize(Decimal("0.01")))
    assert calculo["empleador_sena"] == str((ibc * Decimal("0.02")).quantize(Decimal("0.01")))
    assert calculo["empleador_icbf"] == str((ibc * Decimal("0.03")).quantize(Decimal("0.01")))
    assert calculo["empleador_caja"] == str((ibc * Decimal("0.04")).quantize(Decimal("0.01")))
    # ARL depende de la clase de riesgo (Decreto 427/2022)
    arl_iv = calcular_nomina("1200000.00", "0.00", 0, 0, 0, clase_riesgo_arl=4)
    arl_i = calcular_nomina("1200000.00", "0.00", 0, 0, 0, clase_riesgo_arl=1)
    assert arl_iv["empleador_arl"] != arl_i["empleador_arl"]
    assert Decimal(arl_i["empleador_arl"]) < Decimal(arl_iv["empleador_arl"])


def test_no_existen_fossoy_ni_cesacoles():
    """Esos conceptos no existen en la legislación colombiana."""
    calculo = calcular_nomina("1200000.00", "0.00", 0, 0, 0)
    assert "empleador_fossoy" not in calculo
    assert "empleador_cesacoles" not in calculo
    # Y sí están los parafiscales reales
    assert float(calculo["empleador_sena"]) > 0
    assert float(calculo["empleador_icbf"]) > 0
    assert float(calculo["empleador_caja"]) > 0


def test_tope_base_pensional_es_25_smmlv():
    """Ley 2277/2022: el tope es 25 SMMLV, no el 1,5 SMMLV derogado."""
    from sap_colombia import parametros
    calculo = calcular_nomina("100000000.00", "0.00", 0, 0, 0)
    tope_esperado = parametros.smmlv() * 25
    assert Decimal(calculo["tope_pension"]) == Decimal("43772625.00")
    assert Decimal(calculo["base_pension_topeada"]) == tope_esperado


def test_retencion_salarios_tabla_uvt():
    """Art. 383 E.T.: tabla progresiva en UVT sobre la base gravable depurada.

    Base gravable = devengado - aportes de ley (8%) - renta exenta (25 %,
    tope 240 UVT). Por debajo de ~95 UVT de base gravable no hay retención.
    """
    # 1 SMMLV: base gravable 63 UVT -> sin retención
    c = calcular_nomina("1750905.00", "0.00", 0, 0, 0)
    assert c["ded_retencion"] == "0.00"
    # 5,0 M: base ≈ 3,15 M = 60 UVT -> sin retención
    c = calcular_nomina("5000000.00", "0.00", 0, 0, 0)
    assert c["ded_retencion"] == "0.00"
    # 12 M de salario: con prestaciones provisionadas el devengado supera
    # los 12 M; se verifica la fórmula a partir de los valores devueltos.
    c = calcular_nomina("12000000.00", "0.00", 0, 0, 0)
    from sap_colombia import parametros
    uvt = parametros.uvt()
    dev = Decimal(c["total_devengado"])
    base = dev - Decimal(c["ded_salud"]) - Decimal(c["ded_pension"]) - min(
        dev * Decimal("0.25"), uvt * Decimal("240"))
    base_uvt = base / uvt
    tarifa, resta = Decimal("0.28"), Decimal("31.55")
    if base_uvt <= 150:
        tarifa, resta = Decimal("0.19"), Decimal("18.05")
    esperado = (max(Decimal("0"), base_uvt * tarifa - resta) * uvt).quantize(Decimal("0.01"))
    assert Decimal(c["ded_retencion"]) == esperado, (base_uvt, c["ded_retencion"], esperado)
    # Y es creciente con el salario
    c2 = calcular_nomina("15000000.00", "0.00", 0, 0, 0)
    assert Decimal(c2["ded_retencion"]) > Decimal(c["ded_retencion"])


def test_auxilio_transporte_se_rechaza_sobre_2_smmlv():
    with pytest.raises(PayrollError):
        calcular_nomina("5000000.00", "149095.00", 0, 0, 0, strict=True)
    resultado = calcular_nomina("5000000.00", "149095.00", 0, 0, 0)
    assert Decimal(resultado["auxilio_transporte"]) == Decimal("0.00")


def test_auxilio_transporte_se_rechaza_si_supera_el_valor_legal():
    with pytest.raises(PayrollError):
        calcular_nomina("1500000.00", "500000.00", 0, 0, 0, strict=True)
    resultado = calcular_nomina("1500000.00", "500000.00", 0, 0, 0)
    from sap_colombia import parametros
    assert Decimal(resultado["auxilio_transporte"]) == parametros.obtener("auxilio_transporte")

def test_auxilio_transporte_al_valor_legal_se_acepta():
    from sap_colombia import parametros
    calculo = calcular_nomina("1500000.00", parametros.obtener("auxilio_transporte"), 0, 0, 0)
    assert Decimal(calculo["auxilio_transporte"]) == parametros.obtener("auxilio_transporte")


def test_neto_negativo_se_rechaza():
    with pytest.raises(PayrollError):
        calcular_nomina("1200000.00", "0.00", 0, 0, bonificaciones=Decimal("-3000000"))


def test_prestaciones_sociales_provisionadas():
    calculo = calcular_nomina("1200000.00", "0.00", 0, 0, 0)
    assert Decimal(calculo["cesantias"]) > 0
    assert Decimal(calculo["intereses_cesantias"]) > 0
    assert Decimal(calculo["prima_servicios"]) > 0
    
    # Prima de servicios: 30% del salario ANUAL prorrateado al mes
    # (1200000 * 12 * 0.30) / 12 = 360000
    esperado_prima = (Decimal("1200000.00") * 12 * Decimal("0.30") / 12).quantize(Decimal("0.01"))
    assert Decimal(calculo["prima_servicios"]) == esperado_prima
    
    # Intereses cesantías: 12% sobre el ACUMULADO ANUAL de cesantías prorrateado al mes
    # (99960 * 12 * 0.12) / 12 = 1199.52
    cesantias = Decimal(calculo["cesantias"])
    esperado_intereses = (cesantias * 12 * Decimal("0.12") / 12).quantize(Decimal("0.01"))
    assert Decimal(calculo["intereses_cesantias"]) == esperado_intereses


def test_recargo_nocturno_arc_30():
    calculo = calcular_nomina(
        "1200000.00", "0.00", 0, Decimal("10000.00"), 0,
        horas_nocturnas=Decimal("10"),
    )
    assert calculo["recargo_nocturno"] == "30000.00"   # 10 h × 10.000 × 30 %


def test_total_comprobante_es_devengado_mas_cargas():
    c = calcular_nomina("1200000.00", "0.00", 0, 0, 0)
    assert (Decimal(c["total_devengado"]) + Decimal(c["total_cargas"])) == Decimal(c["total_comprobante"])


# ── Pruebas CUNE SHA-384 ───────────────────────────────────────────────────

def test_cune_es_sha384_96_chars():
    cune = generar_cune(
        numero_nomina="NOM00000001",
        fecha_emision="2026-01-31",
        hora_emision="10:30:00",
        total_devengado="1375405.00",
        total_deducciones="96000.00",
        total_comprobante="1375405.00",
        nit_empleador="900123456",
        doc_empleado="123456789",
        tipo_ambiente="2",
        clave_tecnica="3fa9c0b1d2e34f5a6b7c8d9e0f1a2b3c",
    )
    assert len(cune) == 96
    assert all(c in "0123456789abcdef" for c in cune)


def test_cune_deterministico():
    args = dict(
        numero_nomina="NOM00000001",
        fecha_emision="2026-01-31",
        hora_emision="10:30:00",
        total_devengado="1375405.00",
        total_deducciones="96000.00",
        total_comprobante="1375405.00",
        nit_empleador="900123456",
        doc_empleado="123456789",
        tipo_ambiente="2",
        clave_tecnica="3fa9c0b1d2e34f5a6b7c8d9e0f1a2b3c",
    )
    cune1 = generar_cune(**args)
    cune2 = generar_cune(**args)
    assert cune1 == cune2


def test_cune_cambia_con_parametros():
    base = dict(
        numero_nomina="NOM00000001",
        fecha_emision="2026-01-31",
        hora_emision="10:30:00",
        total_devengado="1375405.00",
        total_deducciones="96000.00",
        total_comprobante="1375405.00",
        nit_empleador="900123456",
        doc_empleado="123456789",
        tipo_ambiente="2",
        clave_tecnica="3fa9c0b1d2e34f5a6b7c8d9e0f1a2b3c",
    )
    cune1 = generar_cune(**base)
    cune2 = generar_cune(**{**base, "total_devengado": "1375406.00"})
    assert cune1 != cune2


# ── Pruebas XML UBL ────────────────────────────────────────────────────────

def test_xml_contiene_cune(setup_db, empleado):
    empresa = db.get_empresa()
    emp = db.get_empleado_by_id(empleado)
    calculo = calcular_nomina(
        salario_base=Decimal(emp["salario_base"]),
        auxilio_transporte=Decimal(emp["auxilio_transporte"]),
        horas_extras=Decimal("0"),
        valor_hora_extra=Decimal("0"),
        bonificaciones=Decimal("0"),
    )
    cune = generar_cune(
        numero_nomina="NOM00000001",
        fecha_emision="2026-01-31",
        hora_emision="10:30:00",
        total_devengado=calculo["total_devengado"],
        total_deducciones=calculo["total_deducciones"],
        total_comprobante=calculo["total_comprobante"],
        nit_empleador=str(empresa["nit"]),
        doc_empleado=str(emp["documento"]),
        tipo_ambiente="2",
        clave_tecnica=str(empresa["clave_tecnica"]),
    )
    xml = construir_xml_nomina(
        empresa=empresa,
        empleado=emp,
        calculo=calculo,
        cune=cune,
        fecha_emision="2026-01-31",
        hora_emision="10:30:00",
        consecutivo="00000001",
        prefijo="NOM",
        periodo_inicio="2026-01-01",
        periodo_fin="2026-01-31",
    )
    assert "cct:NominaIndividual" in xml
    assert cune in xml
    assert calculo["total_devengado"] in xml
    assert calculo["total_deducciones"] in xml


# ── Pruebas Partida Doble ──────────────────────────────────────────────────

def test_partida_doble_nomina(setup_db, empleado):
    empresa = db.get_empresa()
    emp = db.get_empleado_by_id(empleado)
    calculo = calcular_nomina(
        salario_base=Decimal(emp["salario_base"]),
        auxilio_transporte=Decimal(emp["auxilio_transporte"]),
        horas_extras=Decimal("0"),
        valor_hora_extra=Decimal("0"),
        bonificaciones=Decimal("0"),
    )
    nomina = {
        "consecutivo": "00000001",
        "prefijo": "NOM",
        "fecha_emision": "2026-01-31",
        "empleado_id": empleado,
        "total_devengado": calculo["total_devengado"],
        "total_deducciones": calculo["total_deducciones"],
        "neto_pagar": calculo["neto_pagar"],
        "total_cargas": calculo["total_cargas"],
        "total_comprobante": calculo["total_comprobante"],
        "salario_base": calculo["salario_base"],
        "auxilio_transporte": calculo["auxilio_transporte"],
        "total_horas_extras": calculo["total_horas_extras"],
        "bonificaciones": calculo["bonificaciones"],
        "ded_salud": calculo["ded_salud"],
        "ded_pension": calculo["ded_pension"],
    }
    asiento = contabilizar_nomina(nomina)
    assert Decimal(asiento["total_debito"]) == Decimal(asiento["total_credito"])
    assert Decimal(asiento["total_debito"]) > 0


# ── Pruebas Integración BD ─────────────────────────────────────────────────

def test_liquidar_nomina(setup_db, empleado):
    result = liquidar_nomina(
        empleado_id=empleado,
        periodo_inicio="2026-01-01",
        periodo_fin="2026-01-31",
    )
    calc = result["calculacion"]
    # El devengado incluye las prestaciones provisionadas del mes
    assert (Decimal(calc["salario_base"]) + Decimal(calc["auxilio_transporte"])
            + Decimal(calc["cesantias"]) + Decimal(calc["intereses_cesantias"])
            + Decimal(calc["prima_servicios"])) == Decimal(calc["total_devengado"])
    assert Decimal(calc["total_deducciones"]) == (
        Decimal(calc["ded_salud"]) + Decimal(calc["ded_pension"])
        + Decimal(calc["ded_retencion"]))


def test_emitir_nomina_guarda_bd(setup_db, empleado):
    resultado = emitir_nomina(
        empleado_id=empleado,
        periodo_inicio="2026-01-01",
        periodo_fin="2026-01-31",
    )
    nomina = resultado["nomina"]
    assert nomina["id"] > 0
    assert len(nomina["cune"]) == 96
    # Sin cliente DIAN la nómina se generó pero no se transmitió: no puede
    # reportarse como emitida.
    assert nomina["estado_dian"] == "SIN_TRANSMITIR"
    assert nomina["xml_ubl"] and "NominaIndividual" in nomina["xml_ubl"]

    stored = db.get_nominas()[0]
    assert stored["consecutivo"] == nomina["consecutivo"]
    assert stored["cune"] == nomina["cune"]


def test_emitir_nomina_asiento(setup_db, empleado):
    resultado = emitir_nomina(
        empleado_id=empleado,
        periodo_inicio="2026-01-01",
        periodo_fin="2026-01-31",
    )
    asiento = resultado["asiento_contable"]
    assert Decimal(asiento["total_debito"]) == Decimal(asiento["total_credito"])
    assert asiento["tipo_documento"] == "NOMINA"


# ── Pruebas DIAN Mock ──────────────────────────────────────────────────────

def test_emitir_nomina_usa_dian_client(setup_db, empleado):
    """Sin cliente DIAN la nómina no puede reportarse como emitida."""
    resultado = emitir_nomina(
        empleado_id=empleado,
        periodo_inicio="2026-01-01",
        periodo_fin="2026-01-31",
    )
    nomina = resultado["nomina"]
    assert nomina["estado_dian"] == "SIN_TRANSMITIR"
    assert nomina["track_id"] == ""
    assert nomina["mensaje_dian"]


def test_emitir_nomina_rechazada_por_dianqueda_marcada(setup_db, empleado):
    """Si la DIAN rechaza, el estado debe reflejarlo."""
    from unittest.mock import MagicMock

    cliente = MagicMock()
    cliente.transmitir_xml.return_value = MagicMock(
        status_code="1001", track_id="", status_description="Documento inválido",
    )
    resultado = emitir_nomina(
        empleado_id=empleado,
        periodo_inicio="2026-01-01",
        periodo_fin="2026-01-31",
        dian_client=cliente,
    )
    assert resultado["nomina"]["estado_dian"] == "RECHAZADA"
    assert resultado["nomina"]["mensaje_dian"] == "Documento inválido"


def test_cune_rechaza_ambiente_invalido():
    with pytest.raises(PayrollError):
        generar_cune(
            numero_nomina="NOM00000001", fecha_emision="2026-01-31",
            hora_emision="10:30:00", total_devengado="1375405.00",
            total_deducciones="96000.00", total_comprobante="1375405.00",
            nit_empleador="900123456", doc_empleado="123456789",
            tipo_ambiente="9", clave_tecnica="3fa9c0b1d2e34f5a6b7c8d9e0f1a2b3c",
        )


def test_cune_rechaza_clave_tecnica_invalida():
    with pytest.raises(PayrollError):
        generar_cune(
            numero_nomina="NOM00000001", fecha_emision="2026-01-31",
            hora_emision="10:30:00", total_devengado="1375405.00",
            total_deducciones="96000.00", total_comprobante="1375405.00",
            nit_empleador="900123456", doc_empleado="123456789",
            tipo_ambiente="1", clave_tecnica="ABC123",
        )


def test_cune_normaliza_fecha_y_hora():
    """La cadena debe abrirse con AAAAMMDD + HHMMSS normalizados."""
    args = dict(
        numero_nomina="1", total_devengado="1000000.00", total_deducciones="80000.00",
        total_comprobante="1000000.00", nit_empleador="900123456",
        doc_empleado="123456789", tipo_ambiente="1",
        clave_tecnica="3fa9c0b1d2e34f5a6b7c8d9e0f1a2b3c",
    )
    a = generar_cune(fecha_emision="2026-01-31", hora_emision="10:30:00", **args)
    b = generar_cune(fecha_emision="2026-01-31", hora_emision="10:30:00-05:00", **args)
    c = generar_cune(fecha_emision="20260131", hora_emision="103000", **args)
    assert a == b == c
