"""Pruebas del catálogo PUC expandido (60+ cuentas)."""

import sap_colombia.database as db
from sap_colombia import dbutil
def test_puc_has_minimum_60_accounts():
    """El PUC debe tener al menos 60 cuentas."""
    conn = db.get_connection()
    db.init_db()
    fila = dbutil.query(conn, "SELECT COUNT(*) AS total FROM plan_cuentas").fetchone()
    total = fila["total"]
    conn.close()
    assert total >= 60, f"PUC solo tiene {total} cuentas (mínimo requerido: 60)"


def test_puc_has_all_required_categories():
    """Debe tener cuentas en todas las categorías principales."""
    conn = db.get_connection()
    db.init_db()
    cats = [r["categoria"] for r in dbutil.query(conn, 
        "SELECT DISTINCT categoria FROM plan_cuentas"
    ).fetchall()]
    conn.close()
    for req in ("ACTIVO", "PASIVO", "INGRESOS", "GASTOS"):
        assert req in cats, f"Categoría {req} no encontrada en PUC"


def test_puc_covers_key_business_circles():
    """Debe cubrir las cuentas clave del ciclo contable."""
    conn = db.get_connection()
    db.init_db()
    codigos = {r["codigo"] for r in dbutil.query(conn, "SELECT codigo FROM plan_cuentas").fetchall()}
    conn.close()
    # Cuentas clave que deben existir
    clave = {
        "110505",  # Caja
        "111005",  # Bancos
        "130505",  # Clientes
        "143501",  # Inventario
        "220505",  # Proveedores
        "236540",  # Retefuente por pagar
        "240801",  # IVA por pagar
        "250505",  # Salarios por pagar
        "310501",  # Capital (si existe)
        "413501",  # Ingresos operacionales
        "510506",  # Sueldos
        "513501",  # Gastos operacionales
    }
    for c in clave:
        assert c in codigos, f"Cuenta clave {c} no existe en PUC"
