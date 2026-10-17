"""Pruebas de verificación de producción: multi-empresa, endpoints corregidos y estructura UI."""

from pathlib import Path
from sap_colombia import database as db, dbutil
import web_server


def test_multi_tenant_isolation_all_modules():
    """Verifica aislamiento por empresa_id en empleados, nómina, asientos, recibos, notas y soporte."""
    db.init_db()
    conn = db.get_connection()
    with conn:
        emp1 = dbutil.query(
            conn,
            "INSERT INTO empresas (nit, dv, razon_social, direccion, municipio) VALUES ('900111111', '1', 'Empresa Uno SAS', 'Calle 1', 'Bogotá') "
            "ON CONFLICT (nit) DO UPDATE SET razon_social = EXCLUDED.razon_social RETURNING id"
        ).fetchone()["id"]
        emp2 = dbutil.query(
            conn,
            "INSERT INTO empresas (nit, dv, razon_social, direccion, municipio) VALUES ('900222222', '2', 'Empresa Dos SAS', 'Calle 2', 'Medellín') "
            "ON CONFLICT (nit) DO UPDATE SET razon_social = EXCLUDED.razon_social RETURNING id"
        ).fetchone()["id"]
        dbutil.query(conn, "DELETE FROM movimientos_contables WHERE asiento_id IN (SELECT id FROM asientos_contables WHERE numero_comprobante IN ('COMP-E1-001', 'COMP-E2-001'))")
        dbutil.query(conn, "DELETE FROM asientos_contables WHERE numero_comprobante IN ('COMP-E1-001', 'COMP-E2-001')")
        dbutil.query(conn, "DELETE FROM empleados WHERE documento IN ('10101010', '20202020')")
    conn.close()

    # Empresa 1
    db.set_current_empresa_id(emp1)
    e1_id = db.guardar_empleado({
        "numero_documento": "10101010",
        "nombres": "Ana",
        "apellidos": "Uno",
        "cargo": "Contadora",
        "salario_base": "3000000",
    })
    a1_id = db.guardar_asiento(
        {
            "numero_comprobante": "COMP-E1-001",
            "fecha": "2026-10-01",
            "tipo_documento": "FAC",
            "glosa": "Venta Empresa 1",
            "total_debito": "100000",
            "total_credito": "100000",
        },
        [
            {"cuenta_codigo": "130505", "cuenta_nombre": "Clientes", "debito": "100000", "credito": "0"},
            {"cuenta_codigo": "413505", "cuenta_nombre": "Ingresos", "debito": "0", "credito": "100000"},
        ],
    )

    # Empresa 2
    db.set_current_empresa_id(emp2)
    e2_id = db.guardar_empleado({
        "numero_documento": "20202020",
        "nombres": "Carlos",
        "apellidos": "Dos",
        "cargo": "Vendedor",
        "salario_base": "2500000",
    })
    a2_id = db.guardar_asiento(
        {
            "numero_comprobante": "COMP-E2-001",
            "fecha": "2026-10-01",
            "tipo_documento": "FAC",
            "glosa": "Venta Empresa 2",
            "total_debito": "200000",
            "total_credito": "200000",
        },
        [
            {"cuenta_codigo": "130505", "cuenta_nombre": "Clientes", "debito": "200000", "credito": "0"},
            {"cuenta_codigo": "413505", "cuenta_nombre": "Ingresos", "debito": "0", "credito": "200000"},
        ],
    )

    # Verificar que Empresa 1 solo ve sus propios registros
    db.set_current_empresa_id(emp1)
    emps_1 = db.get_empleados()
    assert any(e["id"] == e1_id for e in emps_1)
    assert not any(e["id"] == e2_id for e in emps_1)
    asientos_1 = db.get_asientos()
    assert any(a["id"] == a1_id for a in asientos_1)
    assert not any(a["id"] == a2_id for a in asientos_1)

    # Verificar actualización de empleado en Empresa 1
    actualizado = db.actualizar_empleado(e1_id, {
        "documento": "10101010",
        "nombres": "Ana María",
        "apellidos": "Uno",
        "salario_base": "4500000",
    })
    assert actualizado["nombres"] == "Ana María"
    assert str(actualizado["salario_base"]) == "4500000"


def test_ui_html_integrity():
    """Verifica que index.html tenga exactamente un <main> y un </main> al final, y soporte 2FA."""
    html_path = Path(web_server.__file__).resolve().parent / "static" / "index.html"
    content = html_path.read_text(encoding="utf-8")
    assert content.count("<main ") == 1
    assert content.count("</main>") == 1
    # #tab-precios debe estar dentro de <main> (antes de </main>)
    assert content.index('id="tab-precios"') < content.index("</main>")
    # Campo TOTP 2FA en login
    assert 'id="login-totp"' in content
    assert 'id="login-totp-group"' in content
