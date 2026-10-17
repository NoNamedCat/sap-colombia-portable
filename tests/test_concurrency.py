"""Pruebas TDD para FASE 4: Concurrency ACID y transaccionales atómicas."""

import os
from sap_colombia import dbutil
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(BASE_DIR)
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from sap_colombia import database as db
from sap_colombia import auth


def _limpiar_tablas():
    conn = db.get_connection()
    with conn:
        for tabla in ["lineas_nota_credito", "notas_credito", "recibos_caja",
                      "movimientos_contables", "asientos_contables", "factura_lineas",
                      "facturas", "stock_actual", "kardex"]:
            try:
                dbutil.query(conn, f"DELETE FROM {tabla}")
            except Exception:
                pass
        try:
            dbutil.query(conn, "DELETE FROM empresas WHERE nit LIKE '999%'")
        except Exception:
            pass
    conn.close()


@pytest.fixture(autouse=True)
def setup_db():
    db.init_db()
    _limpiar_tablas()
    yield
    _limpiar_tablas()
    conn = db.get_connection()
    with conn:
        dbutil.query(conn, "UPDATE usuarios SET password_changed_at = NULL")
        h, salt = auth.hash_password("admin123")
        dbutil.query(conn, 
            "UPDATE usuarios SET hash_password = ?, salt = ? WHERE email = 'admin@saluki.com'",
            (h, salt),
        )
    conn.close()


class TestTransactionalScope:
    """transactional_scope() debe garantizar atomicidad."""

    def test_scope_exists(self):
        assert hasattr(db, "transactional_scope"), "db.transactional_scope no existe"

    def test_scope_commits_on_success(self):
        with db.transactional_scope() as conn:
            dbutil.query(conn, 
                "INSERT INTO empresas (nit, razon_social) VALUES (?, ?)",
                ("99900000001", "Empresa TX Scope"),
            )
        conn = db.get_connection()
        row = dbutil.query(conn, 
            "SELECT * FROM empresas WHERE nit = '99900000001'"
        ).fetchone()
        conn.close()
        assert row is not None, "Transacción no se commitó"

    def test_scope_rolls_back_on_exception(self):
        try:
            with db.transactional_scope() as tx_conn:
                dbutil.query(tx_conn,
                    "INSERT INTO empresas (nit, razon_social) VALUES (?, ?)",
                    ("99900000003", "Empresa Deberia Rollback"),
                )
                raise RuntimeError("Simulación de fallo")
        except RuntimeError:
            pass
        conn = db.get_connection()
        row = dbutil.query(conn, 
            "SELECT * FROM empresas WHERE nit = '99900000003'"
        ).fetchone()
        conn.close()
        assert row is None, "Transacción no hizo rollback"

    def test_scope_allows_reads(self):
        # Verificar que la empresa seed existe
        conn = db.get_connection()
        emp = dbutil.query(conn, "SELECT nit FROM empresas LIMIT 1").fetchone()
        conn.close()
        assert emp is not None, "La empresa seed no existe en la base de datos"
        nit = emp["nit"]

        # Verificar que se puede leer dentro de un scope transaccional
        with db.transactional_scope() as tx_conn:
            row = dbutil.query(tx_conn,
                "SELECT * FROM empresas WHERE nit = ?", (nit,)
            ).fetchone()
            assert row is not None, "No se pudo leer la empresa seed dentro del scope"


class TestConcurrentWrites:
    """Escrituras concurrentes no deben perder datos ni dañar la integridad."""

    def test_concurrent_kardex_entries(self):
        """10 hilos escriben entradas de kárdex simultáneamente."""
        errors = []

        def worker(idx: int):
            try:
                with db.transactional_scope() as conn:
                    dbutil.query(conn, 
                        """INSERT INTO kardex (fecha, producto_codigo, bodega_codigo,
                           tipo_movimiento, referencia_documento, cantidad_entrada,
                           saldo_cantidad, created_at)
                           VALUES (?, ?, ?, 'ENTRADA', ?, ?, '10', '2026-01-01')""",
                        ("2026-01-01", "P001", "BODEGA-01", f"COMPRA-{idx}", "10"),
                    )
            except Exception as e:
                errors.append(str(e))

        with ThreadPoolExecutor(max_workers=10) as pool:
            futures = [pool.submit(worker, i) for i in range(10)]
            for f in as_completed(futures):
                f.result()

        assert not errors, f"Errores en hilos: {errors}"
        conn = db.get_connection()
        count = dbutil.query(conn,
            "SELECT COUNT(*) AS n FROM kardex WHERE producto_codigo = 'P001' AND bodega_codigo = 'BODEGA-01'"
        ).fetchone()["n"]
        conn.close()
        assert count == 10, f"Se esperaba 10 entradas, se encontraron {count}"

    def test_concurrent_invoice_inserts(self):
        """5 hilos insertan facturas simultáneamente sin pérdida de datos."""
        errors = []
        lock = threading.Lock()
        counter = {"n": 0}
        conn_setup = db.get_connection()
        emp_row = dbutil.query(conn_setup, "SELECT id FROM empresas LIMIT 1").fetchone()
        empresa_id = emp_row["id"] if emp_row else 1
        conn_setup.close()

        def worker(idx: int):
            try:
                with lock:
                    counter["n"] += 1
                    seq = counter["n"]
                with db.transactional_scope() as conn:
                    dbutil.query(conn, 
                        """INSERT INTO facturas (consecutivo, fecha, cliente_nit, subtotal,
                           total_factura, created_at, saldo_pendiente, estado_cartera, empresa_id)
                           VALUES (?, ?, ?, '100.00', '119.00', '2026-01-01', '119.00', 'PENDIENTE', ?)""",
                        (f"CONC-{seq}", "2026-01-01", "800197268", empresa_id),
                    )
            except Exception as e:
                errors.append(str(e))

        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = [pool.submit(worker, i) for i in range(5)]
            for f in as_completed(futures):
                f.result()

        assert not errors, f"Errores en hilos: {errors}"
        conn = db.get_connection()
        count = dbutil.query(conn,
            "SELECT COUNT(*) AS n FROM facturas WHERE consecutivo LIKE 'CONC-%'"
        ).fetchone()["n"]
        conn.close()
        assert count == 5, f"Se esperaba 5 facturas, se encontraron {count}"

