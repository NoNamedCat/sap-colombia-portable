"""Tests para el módulo de Importación Masiva via Flat File (CSV/Excel)."""

import csv
from sap_colombia import dbutil
import io
import json
import os
import sys
from decimal import Decimal
from datetime import datetime, timezone

import pytest

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(BASE_DIR)
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from sap_colombia import database as db
from sap_colombia import massive_import


@pytest.fixture
def setup_db():
    """Configura la BD de prueba usando la BD principal."""
    db.init_db()
    conn = db.get_connection()
    for tabla in ["kardex", "stock_actual", "movimientos_contables", "asientos_contables",
                  "lineas_nota_credito", "notas_credito", "factura_lineas", "facturas"]:
        try:
            dbutil.query(conn, f"DELETE FROM {tabla}")
        except Exception:
            pass
    conn.commit()
    yield
    conn.close()


class TestPlantillas:
    def test_plantilla_facturas_csv(self, setup_db):
        """La plantilla de facturas genera CSV con cabeceras correctas."""
        data = massive_import.plantilla_facturas(formato="csv")
        reader = csv.reader(io.StringIO(data.decode("utf-8-sig")))
        header = next(reader)
        assert "cliente_nit" in header
        assert "producto_codigo" in header
        assert "cantidad" in header
        assert "valor_unitario" in header

    def test_plantilla_facturas_excel(self, setup_db):
        """La plantilla de facturas genera Excel."""
        data = massive_import.plantilla_facturas(formato="xlsx")
        assert data[:2] == b"PK"  # ZIP magic number

    def test_plantilla_saldos_iniciales(self, setup_db):
        """La plantilla de saldos iniciales incluye cuenta y saldo."""
        data = massive_import.plantilla_saldos_iniciales(formato="csv")
        reader = csv.reader(io.StringIO(data.decode("utf-8-sig")))
        header = next(reader)
        assert "cuenta_codigo" in header
        assert "saldo" in header

    def test_plantilla_toma_inventario(self, setup_db):
        """La plantilla de toma de inventario incluye producto y cantidad."""
        data = massive_import.plantilla_toma_inventario(formato="csv")
        reader = csv.reader(io.StringIO(data.decode("utf-8-sig")))
        header = next(reader)
        assert "producto_codigo" in header
        assert "cantidad" in header


class TestImportacionFacturas:
    def test_importar_facturas_csv_valido(self, setup_db):
        """Importa facturas desde CSV válido."""
        content = (
            "cliente_nit,producto_codigo,cantidad,valor_unitario\n"
            "800197268,PROD-01,10,150000\n"
            "800197268,PROD-01,5,200000\n"
        )
        result = massive_import.importar_facturas(
            content.encode("utf-8"), formato="csv", empresa_id=1
        )
        assert result["procesadas"] == 2
        assert result["errores"] == 0

    def test_importar_facturas_invalidas(self, setup_db):
        """Reporta errores para filas inválidas."""
        content = (
            "cliente_nit,producto_codigo,cantidad,valor_unitario\n"
            "INVALID,PROD-01,abc,def\n"
        )
        result = massive_import.importar_facturas(
            content.encode("utf-8"), formato="csv", empresa_id=1
        )
        assert result["errores"] >= 1

    def test_importar_facturas_crea_registro(self, setup_db):
        """Crea registros en la BD con prefijo IMP."""
        content = (
            "cliente_nit,producto_codigo,cantidad,valor_unitario\n"
            "800197268,PROD-01,1,100000\n"
        )
        massive_import.importar_facturas(
            content.encode("utf-8"), formato="csv", empresa_id=1
        )
        conn = db.get_connection()
        facturas = dbutil.query(conn, 
            "SELECT * FROM facturas WHERE prefijo = 'IMP'"
        ).fetchall()
        conn.close()
        assert len(facturas) >= 1


class TestImportacionSaldos:
    def test_importar_saldos_iniciales(self, setup_db):
        """Importa saldos iniciales a asientos contables."""
        content = (
            "cuenta_codigo,tercero_nit,tercero_nombre,concepto,saldo\n"
            "130505,800197268,Cliente Test,Causación inicial,500000\n"
        )
        result = massive_import.importar_saldos_iniciales(
            content.encode("utf-8"), formato="csv", empresa_id=1
        )
        assert result["procesadas"] == 1

    def test_importar_saldos_invalido(self, setup_db):
        """Rechaza cuentas inválidas (no existieren en PUC)."""
        content = (
            "cuenta_codigo,tercero_nit,tercero_nombre,concepto,saldo\n"
            "000000,800197268,Cliente Test,Causación inicial,500000\n"
        )
        result = massive_import.importar_saldos_iniciales(
            content.encode("utf-8"), formato="csv", empresa_id=1
        )
        assert result["errores"] >= 1


class TestImportacionInventario:
    def test_importar_toma_inventario(self, setup_db):
        """Importa toma de inventario (cargues)."""
        content = (
            "producto_codigo,bodega_codigo,cantidad,costo_unitario\n"
            "PROD-01,BODEGA-01,100,5000\n"
        )
        result = massive_import.importar_toma_inventario(
            content.encode("utf-8"), formato="csv", empresa_id=1
        )
        assert result["procesadas"] == 1

    def test_importar_toma_inventario_stock_existente(self, setup_db):
        """Respete existencias previas."""
        content1 = (
            "producto_codigo,bodega_codigo,cantidad,costo_unitario\n"
            "PROD-01,BODEGA-01,50,5000\n"
        )
        massive_import.importar_toma_inventario(
            content1.encode("utf-8"), formato="csv", empresa_id=1
        )
        content2 = (
            "producto_codigo,bodega_codigo,cantidad,costo_unitario\n"
            "PROD-01,BODEGA-01,30,6000\n"
        )
        result = massive_import.importar_toma_inventario(
            content2.encode("utf-8"), formato="csv", empresa_id=1
        )
        assert result["procesadas"] == 1