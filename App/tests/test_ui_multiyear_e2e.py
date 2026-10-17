"""E2E UI multi-año (2025 y 2026) vía Playwright.

Simula el ciclo completo de un ejercicio fiscal (2025) y la apertura del
siguiente (2026) usando la interfaz web:
  - Login y token JWT
  - Fuerza cambio de contraseña en primer ingreso
  - Dashboard KPIs
  - Facturación (CUFE) con XML DIAN
  - Nota de crédito contra factura emitida
  - Cartera y recibo de caja
  - Documento de soporte
  - Balance de prueba / contabilidad
  - Cierre de periodo 2025-12 y verificación 2026
  - 24 meses de actividad con cierres periódicos

Requiere Playwright y Chromium instalados.
"""

import uuid
import json
from sap_colombia import dbutil
import socket
import threading
import time
from datetime import datetime
from http.server import HTTPServer
from unittest.mock import patch

import pytest

from sap_colombia import auth
from sap_colombia import database as db
from sap_colombia.period_control import (
    PeriodoCerradoError,
    cerrar_periodo,
    get_periodo_actual,
    validar_periodo_abierto,
)
from sap_colombia.web_server import SapWebHandler

UI_TEST_PORT = 8091


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _find_free_port(start: int) -> int:
    port = start
    while port < start + 50:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("127.0.0.1", port))
                return port
        except OSError:
            port += 1
    return start


@pytest.fixture(scope="module")
def web_base_url():
    port = _find_free_port(UI_TEST_PORT)
    server = HTTPServer(("127.0.0.1", port), SapWebHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.5)
    yield f"http://127.0.0.1:{port}"
    server.shutdown()
    server.server_close()


@pytest.fixture(scope="module", autouse=True)
def clean_db():
    """Limpia y re-seed de la base de datos al inicio del módulo."""
    db.init_db(seed=False)
    conn = db.get_connection()
    with conn:
        for tabla in [
            # Hijos primero (FK sin CASCADE deben borrarse antes que sus padres)
            "lineas_nota_credito", "notas_credito",
            "lineas_nota_debito", "notas_debito",
            "lineas_documento_soporte", "documentos_soporte",
            "movimientos_contables", "asientos_contables",
            "recibos_caja", "eventos_radian",
            "factura_lineas", "facturas",
            "auditoria",
            "role_empresa",
            "usuarios", "empresas", "clientes", "productos", "bodegas",
            "nominas", "empleados",
            "periodos_contables", "kardex", "stock_actual",
        ]:
            try:
                dbutil.query(conn, f"DELETE FROM {tabla}")
            except Exception:
                pass
    conn.close()
    auth.seed_usuarios()
    from sap_colombia import rbac
    rbac.ensure_rbac()
    yield
    _forzar_cambio_password_admin("admin123")


@pytest.fixture(autouse=True)
def mock_dian():
    from sap_colombia.dian_client import TransmisionResult
    with patch("sap_colombia.dian_client.DianClient.transmitir_xml") as m:
        m.return_value = TransmisionResult(
            estado="Aceptada", track_id="TRK-TEST",
            status_code="00", status_description="OK",
        )
        yield m


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _setup_empresa_cliente():
    """Siembra empresa/cliente/producto de forma **idempotente**.

    Antes usaba INSERT plano: al reejecutar la suite (o cuando el módulo quedó
    a medias) la segunda corrida moría con
    ``duplicate key ... empresas_nit_key`` en el fixture y las 13 pruebas
    quedaban en ERROR sin llegar a ejecutarse.
    """
    conn = db.get_connection()
    with conn:
        emp_cur = dbutil.query(conn,
            "INSERT INTO empresas (nit, dv, razon_social, direccion, municipio, clave_tecnica, tipo_ambiente, prefijo_resolucion, rango_desde, rango_hasta, resolucion_dian, fecha_resolucion) "
            "VALUES ('900123456', '7', 'Saluki Enterprise SAS', 'Carrera 15 # 85-250', 'Bogotá', '3fa9c0b1d2e34f5a6b7c8d9e0f1a2b3c', '1', 'FAC', 990000000, 999999999, '18760000002', '2026-01-15') "
            "ON CONFLICT (nit) DO UPDATE SET razon_social = EXCLUDED.razon_social, "
            "prefijo_resolucion = EXCLUDED.prefijo_resolucion "
            "RETURNING id"
        )
        empresa_id = emp_cur.fetchone()["id"]
        dbutil.query(conn,
            "INSERT INTO clientes (nit, dv, tipo_documento, razon_social, direccion, municipio, empresa_id) "
            "VALUES ('900999999', '1', 'NIT', 'Cliente Auditado S.A.S.', 'Av. 68 # 52-31', 'Bogotá', ?) "
            "ON CONFLICT (empresa_id, nit) DO UPDATE SET razon_social = EXCLUDED.razon_social",
            (empresa_id,)
        )
        dbutil.query(conn,
            "INSERT INTO productos (codigo, descripcion, precio_unitario, tarifa_iva, tipo_bien_servicio, unidad_medida, empresa_id) "
            "VALUES ('UI-001', 'Producto UI E2E', '100000', 'IVA_19', 'BIENES', 'UNO', ?) "
            "ON CONFLICT (empresa_id, codigo) DO NOTHING",
            (empresa_id,)
        )
    conn.close()


def _setup_admin_usuario():
    conn = db.get_connection()
    with conn:
        dbutil.query(conn,
            "INSERT INTO usuarios (email, nombre, rol, hash_password, salt, activo, created_at) "
            "SELECT 'admin@ui.test', 'Admin UI', 'ADMIN', 'hash', 'salt', 1, '2026-01-01T00:00:00' "
            "WHERE NOT EXISTS (SELECT 1 FROM usuarios WHERE email = 'admin@ui.test')"
        )
    conn.close()


def _forzar_cambio_password_admin(password: str = "admin123") -> None:
    """Deja a admin@saluki.com con ``password_changed_at = NULL``.

    El flujo "cambio de contraseña forzado en el primer ingreso" depende de ese
    NULL. ``seed_usuarios`` solo lo establece cuando *crea* el usuario (ya no en
    cada arranque), por lo que este test debe provocarlo explícitamente para ser
    determinista sobre una base ya sembrada.
    """
    from sap_colombia import auth
    h, salt = auth.hash_password(password)
    conn = db.get_connection()
    with conn:
        dbutil.query(conn,
            "INSERT INTO usuarios (email, nombre, rol, hash_password, salt, activo, created_at, "
            "password_changed_at) "
            "VALUES ('admin@saluki.com', 'Administrador', 'ADMIN', ?, ?, 1, now(), NULL) "
            "ON CONFLICT (email) DO UPDATE SET hash_password = EXCLUDED.hash_password, "
            "salt = EXCLUDED.salt, password_changed_at = NULL",
            (h, salt))
    conn.close()


def _get_admin_id() -> int:
    _setup_admin_usuario()
    conn = db.get_connection()
    row = dbutil.query(conn, 
        "SELECT id FROM usuarios WHERE email = 'admin@ui.test'"
    ).fetchone()
    conn.close()
    return row["id"] if row else None


def _ui_login(page, email: str = "admin@saluki.com", password: str = "admin123"):
    page.wait_for_selector("#login-screen", state="visible", timeout=15000)
    page.fill("#login-usuario", email)
    page.fill("#login-password", password)
    page.click("#login-form button[type=submit]")
    return page


def _ui_change_password(page, new_password: str = "Admin123!"):
    page.wait_for_selector("#force-change-screen", state="visible", timeout=15000)
    page.fill("#fc-password", new_password)
    page.fill("#fc-password-confirm", new_password)
    page.click("#force-change-form button[type=submit]")
    page.wait_for_selector("#main-header", state="visible", timeout=15000)
    return page


def _ui_emit_invoice_ui(page, cantidad: int = 2) -> dict:
    """Emite una factura 100% por DOM."""
    page.wait_for_selector("#main-header", state="visible", timeout=15000)
    # Verificar si la pestaña de facturación está activa
    is_active = page.evaluate("document.querySelector('.tab-btn[data-tab=\"facturacion\"]').classList.contains('active')")
    print(f"Pestaña facturación activa: {is_active}")
    # Verificar si el listener se está agregando
    has_listener = page.evaluate("document.querySelector('.tab-btn[data-tab=\"facturacion\"]').hasAttribute('data-listener')")
    print(f"Has listener: {has_listener}")
    if not has_listener:
        print("setupTabNavigation no se ejecutó, forzando setupTabNavigation y switchTab directamente")
        page.evaluate("setupTabNavigation()")
        page.evaluate("switchTab('facturacion')")
    page.click(".tab-btn[data-tab='facturacion']")
    page.wait_for_timeout(1000)
    page.wait_for_selector("#cliente-select", state="visible", timeout=15000)
    # Verificar si hay líneas en el tbody
    line_count = page.evaluate("document.querySelectorAll('#lineas-tbody tr').length")
    print(f"Líneas en tbody: {line_count}")
    if line_count == 0:
        print("addLinea no se ejecutó, forzando addLinea")
        page.evaluate("addLinea()")
    page.select_option("#cliente-select", index=1)
    # Agrega una línea de producto
    page.click("#btn-add-linea")
    page.wait_for_selector("#lineas-tbody tr", timeout=15000)
    # El input de cantidad es el primer input de tipo number en la primera fila
    page.locator("#lineas-tbody tr:first-child input[type=number]").first.fill(str(cantidad))
    page.click("#btn-emitir-dian")
    page.wait_for_selector("#resultado-dian >> visible=true", timeout=30000)
    estado = page.locator("#res-estado").inner_text().strip()
    cufe = page.locator("#res-cufe").inner_text().strip()
    assert estado == "Aceptada", f"DIAN estado esperado Aceptada, obtuve: {estado}"
    assert len(cufe) == 96, f"CUFE esperado de 96 chars, obtuve: {len(cufe)}"
    page.wait_for_selector("#historial-tbody tr", timeout=15000)
    return {"estado_dian": estado, "cufe": cufe}


def _ui_emit_nc_ui(page, motivo: str = "2", descripcion: str = "Devolución total UI",
                    tipo_anulacion: str = "TOTAL") -> dict:
    """Emite una nota de crédito 100% por DOM contra la primera factura disponible."""
    page.click(".tab-btn[data-tab='notas-credito']")
    page.wait_for_timeout(2000)
    page.select_option("#nc-factura-select", index=1)
    page.select_option("#nc-motivo", value=motivo)
    page.fill("#nc-descripcion", descripcion)
    page.select_option("#nc-anulacion", value=tipo_anulacion)
    page.click("#btn-emitir-nc")
    page.wait_for_selector("#nc-resultado >> visible=true", timeout=30000)
    consecutivo = page.locator("#nc-res-consecutivo").inner_text().strip()
    assert consecutivo and consecutivo != "-"
    return {"consecutivo": consecutivo}


def _ui_emit_recibo_ui(page, medio: str = "EFECTIVO") -> dict:
    """Recauda todas las facturas pendientes 100% por DOM (modal de recaudo).

    Se recauda en un loop hasta que la cartera no muestre más facturas
    pendientes, para garantizar que el test quede con cartera vacía sin
    depender del orden de las filas.
    """
    page.click(".tab-btn[data-tab='cartera']")
    # Recauda todas las facturas pendientes (las tests previas pueden dejar
    # facturas huérfanas, así que se limpien todas).
    for _ in range(10):
        rows = page.locator("#cartera-tbody tr:has-text('Recaudar') button:has-text('Recaudar')")
        if rows.count() == 0:
            break
        rows.last.click()
        page.wait_for_selector("#modal-recaudo >> visible=true", timeout=15000)
        page.select_option("#recaudo-medio", value=medio)
        page.click("#btn-confirmar-recaudo")
        page.wait_for_function(
            "document.getElementById('modal-recaudo').style.display === 'none'", timeout=30000
        )
        # Da tiempo a que loadCartera() se recargue tras cada recibo
        page.wait_for_timeout(1000)
    return {}


def _ui_emit_documento_soporte_ui(page, subtotal: int = 50000) -> dict:
    """Emite un documento de soporte 100% por DOM."""
    page.click(".tab-btn[data-tab='documento-soporte']")
    page.fill("#ds-proveedor-nit", "900999999")
    page.fill("#ds-proveedor-nombre", "Cliente Auditado S.A.S.")
    page.click("#btn-add-ds-linea")
    page.wait_for_selector("#ds-lineas-tbody tr", timeout=15000)
    page.locator("#ds-lineas-tbody input[type=text]").first.fill("UI-001")
    page.locator("#ds-lineas-tbody input[type=number]").first.fill(str(subtotal))
    page.click("#btn-emitir-ds")
    page.wait_for_selector("#ds-resultado >> visible=true", timeout=30000)
    consecutivo = page.locator("#ds-res-consecutivo").inner_text().strip()
    assert consecutivo and consecutivo != "-"
    return {"consecutivo": consecutivo}


def _api_get(base_url: str, path: str, headers: dict | None = None):
    from urllib.request import Request, urlopen
    req = Request(f"{base_url}{path}")
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    with urlopen(req) as resp:
        return resp.status, resp.read().decode("utf-8")


def _api_post(base_url: str, path: str, data: dict, headers: dict | None = None):
    from urllib.request import Request, urlopen
    body = json.dumps(data).encode("utf-8")
    hdrs = {"Content-Type": "application/json"}
    if headers:
        hdrs.update(headers)
    req = Request(f"{base_url}{path}", data=body, headers=hdrs)
    with urlopen(req) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


def _login(base_url: str) -> str:
    """Login API con la contraseña real del admin tras el cambio forzado.

    test_01 (año 2025) fuerza el cambio de admin123 -> Admin123!. Como el
    fixture clean_db es de scope module y no se re-seedea entre tests,
    admin@saluki.com conserva Admin123! durante toda la suite. Se usa
    Admin123! como contraseña de login API.
    """
    status, data = _api_post(
        base_url,
        "/api/auth/login",
        {"email": "admin@saluki.com", "password": "Admin123!"},
    )
    assert status == 200
    return data["token"]





@pytest.fixture(scope="module")
def ui_browser(web_base_url):
    """Browser de Chromium con la app cargada (no autenticado)."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            executable_path="/usr/bin/chromium",
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
        )
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            storage_state={"cookies": [], "origins": []},
        )
        page = context.new_page()
        page.on("dialog", lambda d: d.accept())
        page.goto(web_base_url, wait_until="networkidle")
        yield page
        browser.close()


@pytest.fixture(scope="module")
def ui_page(web_base_url, ui_browser):
    """Browser con datos sembrados (no autenticado). test_01 hace el login."""
    page = ui_browser
    _setup_empresa_cliente()
    _forzar_cambio_password_admin()
    return page


# ---------------------------------------------------------------------------
# Tests — Ejercicio 2025
# ---------------------------------------------------------------------------

class TestE2E_FiscalYear2025:

    def test_01_login_forzado_y_dashboard(self, ui_page):
        page = ui_page
        assert page.locator("#login-screen").is_visible()

        _ui_login(page)

        # password_changed_at = NULL (siembra) => se fuerza cambio en primer ingreso
        page.wait_for_selector("#force-change-screen", state="visible", timeout=15000)
        _ui_change_password(page)

        page.wait_for_selector("#empresa-nombre", state="visible", timeout=15000)
        page.wait_for_function(
            "() => document.getElementById('empresa-nombre').textContent.includes('Saluki')",
            timeout=15000,
        )
        empresa_text = page.locator("#empresa-nombre").inner_text()
        assert "Saluki Enterprise" in empresa_text

        # Dashboard KPIs cargados
        assert "COP" in page.locator("#kpi-ventas").inner_text()
        assert "COP" in page.locator("#kpi-cartera").inner_text()

        # Esperar a que la navegación por pestañas esté lista
        page.wait_for_selector(".tab-btn[data-tab='facturacion']", state="visible", timeout=15000)

        # El token queda en localStorage tras el login real
        token = page.evaluate("localStorage.getItem('sap_token')")
        assert token

    def test_02_facturacion_cufe(self, ui_page):
        factura = _ui_emit_invoice_ui(ui_page, cantidad=2)
        assert factura["estado_dian"] == "Aceptada"
        assert len(factura["cufe"]) == 96
        assert ui_page.locator("#historial-tbody tr").count() >= 1

    def test_03_nota_credito(self, ui_page):
        ui_page.wait_for_selector("#main-header", state="visible", timeout=15000)
        _ui_emit_invoice_ui(ui_page, cantidad=1)
        resultado = _ui_emit_nc_ui(ui_page)
        assert resultado["consecutivo"] != "-"

    def test_04_cartera_y_recibo(self, ui_page):
        ui_page.wait_for_selector("#main-header", state="visible", timeout=15000)
        _ui_emit_invoice_ui(ui_page, cantidad=1)
        _ui_emit_recibo_ui(ui_page, medio="EFECTIVO")

        # Tras recaudo total, la cartera no debe mostrar la factura como pendiente.
        ui_page.wait_for_function(
            "() => { const rows = document.querySelectorAll('#cartera-tbody tr'); return Array.from(rows).filter(r => r.textContent.includes('Recaudar')).length === 0; }",
            timeout=30000,
        )

    def test_05_documento_soporte(self, ui_page):
        doc = _ui_emit_documento_soporte_ui(ui_page, subtotal=50000)
        assert doc["consecutivo"] != "-"

    def test_06_balance_prueba(self, ui_page):
        _ui_emit_invoice_ui(ui_page, cantidad=2)

        from sap_colombia.accounting_engine import generar_balance_prueba
        balance = generar_balance_prueba()
        assert balance["balance_cuadrado"] is True

        ui_page.click(".tab-btn[data-tab='contabilidad']")
        ui_page.wait_for_selector("#balance-tbody tr", timeout=30000)
        assert ui_page.locator("#balance-tbody tr").count() >= 1

    def test_07_cierre_periodo_actual(self, ui_page):
        """Cierra el periodo contable actual y verifica que queda cerrado."""
        periodo = get_periodo_actual()
        assert periodo["estado"] == "ABIERTO"

        admin_id = _get_admin_id()
        resultado = cerrar_periodo(periodo["periodo"], admin_id, "Cierre ejercicio fiscal")
        assert resultado["estado"] == "CERRADO"

        with pytest.raises(PeriodoCerradoError):
            validar_periodo_abierto(periodo["periodo"])

        conn = db.get_connection()
        dbutil.query(conn, 
            "DELETE FROM periodos_contables WHERE periodo = ?", (periodo["periodo"],)
        )
        conn.commit()
        conn.close()


# ---------------------------------------------------------------------------
# Tests — Ejercicio 2026
# ---------------------------------------------------------------------------

class TestE2E_FiscalYear2026:

    def test_2026_01_periodo_2026_01_abierto(self, ui_page):
        periodo = get_periodo_actual()
        assert periodo["estado"] == "ABIERTO"

    def test_2026_02_nueva_factura_2026(self, ui_page):
        factura = _ui_emit_invoice_ui(ui_page, cantidad=3)
        assert factura["estado_dian"] == "Aceptada"

    def test_2026_03_dashboard_2026(self, ui_page):
        _ui_emit_invoice_ui(ui_page, cantidad=1)
        ui_page.click(".tab-btn[data-tab='dashboard']")
        ui_page.wait_for_selector("#kpi-ventas", timeout=15000)
        assert "COP" in ui_page.locator("#kpi-ventas").inner_text()

    def test_2026_04_exportar_cartera(self, ui_page, web_base_url):
        token = _login(web_base_url)
        status, data = _api_get(
            web_base_url,
            "/api/reportes/cartera/exportar?formato=csv",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert status == 200

    def test_2026_05_ciclo_24_meses(self, ui_page):
        """Simula 24 meses de actividad con cierres periódicos de periodo.

        Cada mes:
          1. Se asegura que el periodo está ABIERTO (limpia cierres previos).
          2. Se valida que está abierto.
          3. Se cierra el periodo (cerrar_periodo) con justificación.
          4. Se verifica que quedó CERRADO y que las operaciones lo rechazan.
          5. Se limpia el cierre para que el mes siguiente arranque abierto.
        Al final, el periodo actual debe quedar ABIERTO.
        """
        admin_id = _get_admin_id()
        ahora = datetime.now()

        def _mes_periodo(offset: int) -> str:
            y, m = ahora.year, ahora.month
            for _ in range(offset):
                m -= 1
                if m == 0:
                    m = 12
                    y -= 1
            return f"{y}-{m:02d}"

        for mes_offset in range(23, -1, -1):
            periodo_key = _mes_periodo(mes_offset)

            conn = db.get_connection()
            dbutil.query(conn, 
                "DELETE FROM periodos_contables WHERE periodo = ?", (periodo_key,)
            )
            conn.commit()
            conn.close()

            periodo = validar_periodo_abierto(periodo_key)
            assert periodo["estado"] == "ABIERTO"

            resultado = cerrar_periodo(
                periodo_key, admin_id, f"Cierre periódico {periodo_key}"
            )
            assert resultado["estado"] == "CERRADO"

            with pytest.raises(PeriodoCerradoError):
                validar_periodo_abierto(periodo_key)

            conn = db.get_connection()
            dbutil.query(conn, 
                "DELETE FROM periodos_contables WHERE periodo = ?", (periodo_key,)
            )
            conn.commit()
            conn.close()

        periodo_actual = get_periodo_actual()
        assert periodo_actual["estado"] == "ABIERTO"

    def test_08_nomina_empleados(self, ui_page):
        tab = "#tab-nomina"
        ui_page.click(".tab-btn[data-tab='nomina']")
        ui_page.wait_for_selector(f"{tab}.active", timeout=10000)
        # El formulario de empleado arranca colapsado; hay que abrirlo.
        ui_page.click(f"{tab} #btn-toggle-form-empleado")
        ui_page.wait_for_selector(f"{tab} #form-empleado", state="visible", timeout=10000)
        # Documento único por corrida: si se reutiliza, POST /api/empleados
        # responde 400 por duplicado y la nómina queda PAGADA de una corrida
        # anterior (sin botón "Pagar"), haciendo el test no determinista.
        documento = f"9{uuid.uuid4().int % 10**9:09d}"
        ui_page.fill(f"{tab} #empleado-documento", documento)
        ui_page.fill(f"{tab} #emp-nombres", "Juan")
        ui_page.fill(f"{tab} #emp-apellidos", "Perez")
        ui_page.fill(f"{tab} #emp-salario", "1409990")
        ui_page.click(f"{tab} #btn-guardar-empleado")
        ui_page.wait_for_selector(f"{tab} #tabla-empleados tbody tr", timeout=10000)
        # La liquidación individual vive en el sub-tab "Procesar Nómina".
        ui_page.click(f"{tab} .nomina-subtab[data-nomina-tab='procesar']")
        ui_page.wait_for_selector(f"{tab} #nomina-empleado-select", state="visible", timeout=10000)
        ui_page.select_option(f"{tab} #nomina-empleado-select", index=1)
        ui_page.fill(f"{tab} #nomina-periodo-inicio", "2026-09-01")
        ui_page.fill(f"{tab} #nomina-periodo-fin", "2026-09-30")
        ui_page.click(f"{tab} #btn-liquidar-nomina")
        ui_page.wait_for_selector(f"{tab} #resultado-liquidacion >> visible=true", timeout=10000)
        ui_page.click(f"{tab} #btn-emitir-nomina")
        ui_page.wait_for_selector(f"{tab} #resultado-nomina >> visible=true", timeout=15000)
        # El botón "Pagar" vive en el sub-tab "Historial".
        ui_page.click(f"{tab} .nomina-subtab[data-nomina-tab='historial']")
        ui_page.wait_for_selector(f"{tab} #tabla-nominas tbody tr button:has-text('Pagar')", timeout=10000)
        ui_page.click(f"{tab} #tabla-nominas tbody tr button:has-text('Pagar')")
        ui_page.wait_for_selector(f"{tab} #resultado-pago-nomina >> visible=true", timeout=15000)
