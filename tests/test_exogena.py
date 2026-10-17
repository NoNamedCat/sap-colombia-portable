"""Pruebas TDD para Información Exógena DIAN — Formatos 1001, 1007 y Certificados de Retención."""

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
from sap_colombia import exogena


@pytest.fixture
def setup_db():
    db.init_db()
    conn = db.get_connection()
    with conn:
        dbutil.query(conn, "DELETE FROM movimientos_contables")
        dbutil.query(conn, "DELETE FROM asientos_contables")
        dbutil.query(conn, "DELETE FROM clientes")
    conn.close()
    yield
    conn = db.get_connection()
    with conn:
        dbutil.query(conn, "DELETE FROM movimientos_contables")
        dbutil.query(conn, "DELETE FROM asientos_contables")
        dbutil.query(conn, "DELETE FROM clientes")
    conn.close()


def _insertar_asiento(numero: str, fecha: str) -> int:
    conn = db.get_connection()
    with conn:
        cur = dbutil.query(conn,
            """INSERT INTO asientos_contables
               (numero_comprobante, fecha, tipo_documento, glosa, total_debito, total_credito, created_at)
               VALUES (?, ?, 'TEST', 'Prueba', '0', '0', '2026-01-01T00:00:00')
               RETURNING id""",
            (numero, fecha),
        )
        asiento_id = cur.fetchone()["id"]
    conn.close()
    return asiento_id


def _insertar_mov(asiento_id: int, cuenta: str, nit: str, nombre: str,
                  concepto: str, debito: str, credito: str):
    conn = db.get_connection()
    with conn:
        dbutil.query(conn, 
            """INSERT INTO movimientos_contables
               (asiento_id, cuenta_codigo, tercero_nit, tercero_nombre, concepto, debito, credito)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (asiento_id, cuenta, nit, nombre, concepto, debito, credito),
        )
    conn.close()


def _insertar_cliente(nit: str, razon: str, direccion: str, municipio: str):
    conn = db.get_connection()
    empresa = dbutil.query(conn, "SELECT id FROM empresas LIMIT 1").fetchone()
    empresa_id = empresa["id"] if empresa else 1
    with conn:
        dbutil.query(conn, 
            """INSERT INTO clientes (nit, dv, tipo_documento, razon_social, direccion, municipio, empresa_id)
               VALUES (?, ?, 'NIT', ?, ?, ?, ?)""",
            (nit, "1", razon, direccion, municipio, empresa_id),
        )
    conn.close()


# ── FORMATO 1001 — Pagos a Terceros ─────────────────────────────────────────

def test_formato_1001_extraccion_basica(setup_db):
    """Valida extracción de gastos (51xx) agrupados por tercero."""
    as_id = _insertar_asiento("F1001-A", "2026-03-15")
    _insertar_mov(as_id, "510506", "900111111", "Proveedor Uno", "Sueldos", "500000.00", "0.00")
    _insertar_mov(as_id, "513501", "900111111", "Proveedor Uno", "Servicios", "300000.00", "0.00")

    registros = exogena.extraer_formato_1001(2026)
    assert len(registros) == 1
    assert registros[0]["tercero_nit"] == "900111111"
    assert registros[0]["pago_abono_deducible"] == Decimal("800000.00")
    assert registros[0]["retencion_fuente_practicada"] == Decimal("0.00")
    assert registros[0]["retencion_iva_practicada"] == Decimal("0.00")


def test_formato_1001_cxp_credito(setup_db):
    """Valida extracción de cuentas por pagar (22xx, 23xx) — créditos."""
    as_id = _insertar_asiento("F1001-B", "2026-04-01")
    _insertar_mov(as_id, "220505", "900222222", "Proveedor Dos", "Pago proveedor", "0.00", "2000000.00")
    _insertar_mov(as_id, "239001", "900222222", "Proveedor Dos", "Aplicación", "0.00", "500000.00")

    registros = exogena.extraer_formato_1001(2026)
    assert len(registros) == 1
    assert registros[0]["pago_abono_deducible"] == Decimal("2500000.00")


def test_formato_1001_retenciones(setup_db):
    """Valida extracción separada de retenciones (2365xx = Retefuente, 2368xx = ReteIVA)."""
    as_id = _insertar_asiento("F1001-C", "2026-02-10")
    _insertar_mov(as_id, "236540", "900333333", "Tercero Ret", "Retefuente", "0.00", "75000.00")
    _insertar_mov(as_id, "236801", "900333333", "Tercero Ret", "ReteIVA", "0.00", "50000.00")

    registros = exogena.extraer_formato_1001(2026)
    assert len(registros) == 1
    # Separados según normativa DIAN
    assert registros[0]["retencion_fuente_practicada"] == Decimal("75000.00")
    assert registros[0]["retencion_iva_practicada"] == Decimal("50000.00")
    assert registros[0]["pago_abono_deducible"] == Decimal("0.00")


def test_formato_1001_agrupacion_por_tercero(setup_db):
    """Valida que terceros distintos quedan agrupados por NIT."""
    as_id = _insertar_asiento("F1001-D", "2026-01-20")
    _insertar_mov(as_id, "513501", "900444444", "Cliente A", "Compra", "100000.00", "0.00")
    _insertar_mov(as_id, "513501", "900555555", "Cliente B", "Compra", "200000.00", "0.00")

    registros = exogena.extraer_formato_1001(2026)
    assert len(registros) == 2
    nits = [r["tercero_nit"] for r in registros]
    assert "900444444" in nits
    assert "900555555" in nits


def test_formato_1001_solo_ano_correspondiente(setup_db):
    """Valida que solo se incluyen movimientos del año especificado."""
    as_id = _insertar_asiento("F1001-E", "2025-12-31")
    _insertar_mov(as_id, "513501", "900666666", "Anterior", "Año anterior", "999999.00", "0.00")

    as_id2 = _insertar_asiento("F1001-F", "2026-01-05")
    _insertar_mov(as_id2, "513501", "900777777", "Actual", "Año actual", "50000.00", "0.00")

    registros = exogena.extraer_formato_1001(2026)
    assert len(registros) == 1
    assert registros[0]["tercero_nit"] == "900777777"


def test_formato_1001_xml_estructura(setup_db):
    """Valida estructura XML del Formato 1001 con encabezados DIAN."""
    as_id = _insertar_asiento("F1001-G", "2026-06-01")
    _insertar_mov(as_id, "513501", "900888888", "Cliente XML", "Servicio", "150000.00", "0.00")

    xml = exogena.construir_xml_formato_1001(2026)

    assert "<ExogenaFormato1001" in xml
    assert "<Encabezado>" in xml
    assert "<NIT>" in xml
    assert "<Periodo>" in xml
    assert "2026" in xml
    assert "<Registros>" in xml
    assert "<Registro>" in xml
    assert "900888888" in xml
    assert "<Concepto>" in xml
    assert "<Tipo_Doc>" in xml
    assert "<Numero_Doc>" in xml
    assert "<Primer_Apellido>" in xml
    assert "<Primer_Nombre>" in xml
    assert "<Razon_Social>" in xml
    assert "Direccion" in xml
    assert "<Pago_Abono_Deducible>" in xml
    assert "<Pago_Abono_No_Deducible>" in xml
    assert "<Retencion_Fuente_Practicada>" in xml
    assert "<Retencion_IVA_Practicada>" in xml


def test_formato_1001_xml_valores(setup_db):
    """Valida valores numéricos correctos en el XML."""
    as_id = _insertar_asiento("F1001-H", "2026-07-01")
    _insertar_mov(as_id, "513501", "900999999", "Valores", "Gasto", "1000000.00", "0.00")
    _insertar_mov(as_id, "236540", "900999999", "Valores", "Retefuente", "0.00", "25000.00")
    _insertar_mov(as_id, "236801", "900999999", "Valores", "ReteIVA", "0.00", "15000.00")

    xml = exogena.construir_xml_formato_1001(2026)
    assert "1000000.00" in xml
    assert "25000.00" in xml
    assert "15000.00" in xml


# ── FORMATO 1007 — Ingresos Propios Recibidos ───────────────────────────────

def test_formato_1007_extraccion_basica(setup_db):
    """Valida extracción de ingresos (4135xx) por cliente."""
    as_id = _insertar_asiento("F1007-A", "2026-03-10")
    _insertar_mov(as_id, "413501", "800111111", "Cliente Ing", "Venta", "0.00", "500000.00")

    registros = exogena.extraer_formato_1007(2026)
    assert len(registros) == 1
    assert registros[0]["tercero_nit"] == "800111111"
    assert registros[0]["ingresos_recibidos"] == Decimal("500000.00")
    assert registros[0]["devoluciones"] == Decimal("0.00")
    assert registros[0]["ingresos_netos"] == Decimal("500000.00")


def test_formato_1007_con_devoluciones(setup_db):
    """Valida que las devoluciones (4175xx) se restan del ingreso neto."""
    as_id = _insertar_asiento("F1007-B", "2026-04-15")
    _insertar_mov(as_id, "413501", "800222222", "Cliente Dev", "Venta", "0.00", "300000.00")
    _insertar_mov(as_id, "417505", "800222222", "Cliente Dev", "Devolución", "50000.00", "0.00")

    registros = exogena.extraer_formato_1007(2026)
    assert len(registros) == 1
    assert registros[0]["ingresos_recibidos"] == Decimal("300000.00")
    assert registros[0]["devoluciones"] == Decimal("50000.00")
    assert registros[0]["ingresos_netos"] == Decimal("250000.00")


def test_formato_1007_agrupacion_por_cliente(setup_db):
    """Valida agrupación por cliente NIT."""
    as_id = _insertar_asiento("F1007-C", "2026-05-01")
    _insertar_mov(as_id, "413501", "800333333", "Cli A", "Venta", "0.00", "100000.00")
    _insertar_mov(as_id, "413501", "800444444", "Cli B", "Venta", "0.00", "200000.00")

    registros = exogena.extraer_formato_1007(2026)
    assert len(registros) == 2
    nits = [r["tercero_nit"] for r in registros]
    assert "800333333" in nits
    assert "800444444" in nits


def test_formato_1007_solo_ano_correspondiente(setup_db):
    """Valida filtro por año."""
    as_id = _insertar_asiento("F1007-D", "2025-11-11")
    _insertar_mov(as_id, "413501", "800555555", "Cli 2025", "Venta", "0.00", "999999.00")

    registros = exogena.extraer_formato_1007(2026)
    assert len(registros) == 0


def test_formato_1007_xml_estructura(setup_db):
    """Valida estructura XML del Formato 1007."""
    as_id = _insertar_asiento("F1007-E", "2026-08-01")
    _insertar_mov(as_id, "413501", "800666666", "Cli XML", "Venta", "0.00", "250000.00")

    xml = exogena.construir_xml_formato_1007(2026)

    assert "<ExogenaFormato1007" in xml
    assert "<Encabezado>" in xml
    assert "<NIT>" in xml
    assert "<Periodo>" in xml
    assert "2026" in xml
    assert "<Registros>" in xml
    assert "<Registro>" in xml
    assert "800666666" in xml
    assert "<Razon_Social>" in xml
    assert "<Ingresos_Recibidos>" in xml
    assert "<Devoluciones>" in xml
    assert "<Ingresos_Netos>" in xml


def test_formato_1007_xml_valores(setup_db):
    """Valida valores numéricos correctos en el XML 1007."""
    as_id = _insertar_asiento("F1007-F", "2026-09-01")
    _insertar_mov(as_id, "413501", "800777777", "Cli Val", "Venta", "0.00", "750000.00")
    _insertar_mov(as_id, "417505", "800777777", "Cli Val", "Devolución", "25000.00", "0.00")

    xml = exogena.construir_xml_formato_1007(2026)
    assert "750000.00" in xml
    assert "25000.00" in xml
    assert "725000.00" in xml


# ── CERTIFICADOS DE RETENCIÓN ───────────────────────────────────────────────

def test_certificado_retefuente(setup_db):
    """Valida generación de certificado con Retefuente."""
    as_id = _insertar_asiento("CRT-A", "2026-02-15")
    _insertar_mov(as_id, "135515", "700111111", "Tercero RF", "Anticipo Retefuente", "45000.00", "0.00")
    _insertar_mov(as_id, "135515", "700111111", "Tercero RF", "Anticipo Retefuente", "35000.00", "0.00")

    cert = exogena.generar_certificado_retencion("700111111", 2026)

    assert cert["total_retefuente"] == "80000.00"
    assert cert["total_reteica"] == "0.00"
    assert cert["total_general"] == "80000.00"
    assert cert["periodo"] == "2026"
    assert len(cert["detalles"]) == 2
    assert cert["tercero"]["nit"] == "700111111"


def test_certificado_reteica(setup_db):
    """Valida generación de certificado con ReteICA."""
    as_id = _insertar_asiento("CRT-B", "2026-03-20")
    _insertar_mov(as_id, "135518", "700222222", "Tercero ICA", "Anticipo ReteICA", "60000.00", "0.00")

    cert = exogena.generar_certificado_retencion("700222222", 2026)

    assert cert["total_retefuente"] == "0.00"
    assert cert["total_reteica"] == "60000.00"
    assert cert["total_general"] == "60000.00"
    assert len(cert["detalles"]) == 1
    assert cert["detalles"][0]["tipo"] == "RETEICA"


def test_certificado_mixto(setup_db):
    """Valida certificado con Retefuente y ReteICA simultáneos."""
    as_id = _insertar_asiento("CRT-C", "2026-04-05")
    _insertar_mov(as_id, "135515", "700333333", "Tercero Mix", "ReteFuente", "20000.00", "0.00")
    _insertar_mov(as_id, "135518", "700333333", "Tercero Mix", "ReteICA", "10000.00", "0.00")

    cert = exogena.generar_certificado_retencion("700333333", 2026)

    assert cert["total_retefuente"] == "20000.00"
    assert cert["total_reteica"] == "10000.00"
    assert cert["total_general"] == "30000.00"
    assert len(cert["detalles"]) == 2


def test_certificado_solo_ano_correspondiente(setup_db):
    """Valida filtro por año en certificados."""
    as_id = _insertar_asiento("CRT-D", "2025-06-01")
    _insertar_mov(as_id, "135515", "700444444", "Tercero Ant", "ReteFuente", "50000.00", "0.00")

    cert = exogena.generar_certificado_retencion("700444444", 2026)
    assert cert["total_retefuente"] == "0.00"
    assert cert["total_general"] == "0.00"
    assert len(cert["detalles"]) == 0


def test_certificado_tercero_inexistente(setup_db):
    """Valida que un tercero sin movimientos retorna ceros."""
    cert = exogena.generar_certificado_retencion("000000000", 2026)
    assert cert["total_retefuente"] == "0.00"
    assert cert["total_reteica"] == "0.00"
    assert len(cert["detalles"]) == 0


def test_certificado_xml_estructura(setup_db):
    """Valida estructura XML del certificado de retención."""
    as_id = _insertar_asiento("CRT-E", "2026-05-10")
    _insertar_mov(as_id, "135515", "700555555", "Tercero XML", "ReteFuente", "30000.00", "0.00")

    cert = exogena.generar_certificado_retencion("700555555", 2026)
    xml = exogena.construir_xml_certificado(cert)

    assert "<CertificadoRetencion" in xml
    assert "<Emisor>" in xml
    assert "<NIT>" in xml
    assert "<Tercero>" in xml
    assert "700555555" in xml
    assert "<Periodo>" in xml
    assert "2026" in xml
    assert "<Totales>" in xml
    assert "<RetencionFuente>" in xml
    assert "<RetencionICA>" in xml
    assert "<TotalGeneral>" in xml
    assert "<Detalles>" in xml
    assert "<Detalle>" in xml
    assert "30000.00" in xml


def test_certificado_con_info_tercero(setup_db):
    """Valida que el certificado incluye datos del tercero de la BD."""
    _insertar_cliente("700666666", "SACOLMBIA S.A.S.", "Cra 15 #123-45", "Bogotá")

    as_id = _insertar_asiento("CRT-F", "2026-06-15")
    _insertar_mov(as_id, "135515", "700666666", "", "ReteFuente", "15000.00", "0.00")

    cert = exogena.generar_certificado_retencion("700666666", 2026)
    assert cert["tercero"]["razon_social"] == "SACOLMBIA S.A.S."
    assert cert["tercero"]["direccion"] == "Cra 15 #123-45"


def test_certificado_multiples_periodos(setup_db):
    """Valida acumulación de retenciones de múltiples meses."""
    as_id1 = _insertar_asiento("CRT-G1", "2026-01-15")
    _insertar_mov(as_id1, "135515", "700777777", "Tercero Multi", "ReteF Ene", "10000.00", "0.00")

    as_id2 = _insertar_asiento("CRT-G2", "2026-02-15")
    _insertar_mov(as_id2, "135515", "700777777", "Tercero Multi", "ReteF Feb", "20000.00", "0.00")

    as_id3 = _insertar_asiento("CRT-G3", "2026-03-15")
    _insertar_mov(as_id3, "135518", "700777777", "Tercero Multi", "ReteICA Mar", "5000.00", "0.00")

    cert = exogena.generar_certificado_retencion("700777777", 2026)
    assert cert["total_retefuente"] == "30000.00"
    assert cert["total_reteica"] == "5000.00"
    assert cert["total_general"] == "35000.00"
    assert len(cert["detalles"]) == 3
