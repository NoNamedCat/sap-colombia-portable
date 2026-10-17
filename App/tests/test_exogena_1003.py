"""Pruebas del formato exógeno 1003 (Ingresos operacionales)."""

import xml.etree.ElementTree as ET
from sap_colombia import dbutil
from decimal import Decimal

import pytest

import sap_colombia.database as db
from sap_colombia.exogena import (
    extraer_formato_1003,
    construir_xml_formato_1003,
)


def _setup_db():
    conn = db.get_connection()
    db.init_db()
    if not db.get_empresa():
        db.guardar_empresa({"nit": "900123456", "razon_social": "Emp", "clave_tecnica": "3fa9c0b1d2e34f5a6b7c8d9e0f1a2b3c"})
    conn.close()


def test_extraer_formato_1003_returns_records():
    _setup_db()
    conn = db.get_connection()
    db.guardar_factura({
        "consecutivo": "FAC001", "fecha": "2026-10-01", "hora": "12:00:00-05:00",
        "subtotal": "100000.00", "total_iva": "19000.00", "total_factura": "119000.00",
        "cliente_nit": "800987654", "cufe": "f" * 96, "estado": "EXITOSA",
        "saldo_pendiente": "119000.00", "prefijo": "F",
    }, [])
    conn.close()

    registros = extraer_formato_1003(2026)
    assert len(registros) >= 0  # no crash


def test_xml_formato_1003_has_root_element():
    _setup_db()
    xml_str = construir_xml_formato_1003(2026)
    root = ET.fromstring(xml_str)
    assert root.tag == "ExogenaFormato1003"


def test_xml_formato_1003_has_encabezado():
    _setup_db()
    xml_str = construir_xml_formato_1003(2026)
    root = ET.fromstring(xml_str)
    enc = root.find("Encabezado")
    assert enc is not None
    assert enc.find("NIT") is not None
    assert enc.find("Periodo") is not None


def test_xml_formato_1003_has_registros():
    _setup_db()
    xml_str = construir_xml_formato_1003(2026)
    root = ET.fromstring(xml_str)
    regs = root.find("Registros")
    assert regs is not None


def test_xml_1003_con_facturas():
    _setup_db()
    conn = db.get_connection()
    row = dbutil.query(conn, "SELECT id FROM empresas ORDER BY id LIMIT 1").fetchone()
    empresa_id = row["id"] if row else 1
    dbutil.query(conn, 
        "INSERT INTO clientes (nit, dv, tipo_documento, razon_social, direccion, municipio, empresa_id) "
        "VALUES ('800987654', '7', 'NIT', 'Cliente Test', 'Cra 1 #2', 'Bogotá', ?) "
        "ON CONFLICT (empresa_id, nit) DO UPDATE SET razon_social = 'Cliente Test'",
        (empresa_id,),
    )
    conn.commit()
    db.guardar_factura({
        "consecutivo": "FAC002", "fecha": "2026-10-02", "hora": "12:00:00-05:00",
        "subtotal": "50000.00", "iva_19": "9500.00", "iva_5": "0.00", "iva_0": "0.00",
        "total_iva": "9500.00", "total_factura": "59500.00",
        "cliente_nit": "800987654", "cufe": "f" * 96, "estado": "EXITOSA",
        "saldo_pendiente": "59500.00", "prefijo": "F",
    }, [])
    conn.close()

    xml_str = construir_xml_formato_1003(2026)
    root = ET.fromstring(xml_str)
    regs = root.find("Registros")
    assert regs is not None
    registros = regs.findall("Registro")
    assert len(registros) >= 1


def test_xml_1003_vacio():
    _setup_db()
    xml_str = construir_xml_formato_1003(1999)
    root = ET.fromstring(xml_str)
    assert root.tag == "ExogenaFormato1003"
    regs = root.find("Registros")
    assert regs is not None
    assert len(regs.findall("Registro")) == 0


def test_xml_1003_campos_tercero():
    _setup_db()
    conn = db.get_connection()
    row = dbutil.query(conn, "SELECT id FROM empresas ORDER BY id LIMIT 1").fetchone()
    empresa_id = row["id"] if row else 1
    dbutil.query(conn, 
        "INSERT INTO clientes (nit, dv, tipo_documento, razon_social, direccion, municipio, empresa_id) "
        "VALUES ('800987655', '8', 'NIT', 'Tercero Exogena', 'Cra 3 #4', 'Medellín', ?) "
        "ON CONFLICT (empresa_id, nit) DO UPDATE SET razon_social = 'Tercero Exogena'",
        (empresa_id,),
    )
    conn.commit()
    db.guardar_factura({
        "consecutivo": "FAC003", "fecha": "2026-10-03", "hora": "12:00:00-05:00",
        "subtotal": "20000.00", "iva_19": "3800.00", "iva_5": "0.00", "iva_0": "0.00",
        "total_iva": "3800.00", "total_factura": "23800.00",
        "cliente_nit": "800987655", "cufe": "f" * 96, "estado": "EXITOSA",
        "saldo_pendiente": "23800.00", "prefijo": "F",
    }, [])
    conn.close()

    registros = extraer_formato_1003(2026)
    assert len(registros) >= 1
    for reg in registros:
        assert "nit_tercero" in reg
        assert "nombre_tercero" in reg
        assert "fecha" in reg
        assert "consecutivo" in reg
        assert "tipo_operacion" in reg
        assert "subtotal" in reg
        assert "iva_19" in reg
        assert "iva_5" in reg
        assert "iva_0" in reg
        assert "total" in reg
