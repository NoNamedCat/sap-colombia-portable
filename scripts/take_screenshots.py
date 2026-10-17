import os
import time
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from sap_colombia import database as db, dbutil, auth

OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "src", "static", "tutorial", "screenshots")
os.makedirs(OUT_DIR, exist_ok=True)


def prepare_demo_data():
    """Prepara las empresas, usuarios de prueba y logos de demostración para las capturas."""
    conn = db.get_connection()
    now_iso = datetime.now(timezone.utc).isoformat(sep=" ")
    # Logo SVG corporativo en Base64 para mostrar la funcionalidad de Logo propio
    svg_corp = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="140" height="44" viewBox="0 0 140 44">'
        '<rect width="40" height="40" x="2" y="2" rx="8" fill="#0070f2"/>'
        '<path d="M12 22 L20 30 L32 14" stroke="#ffffff" stroke-width="4" fill="none" stroke-linecap="round" stroke-linejoin="round"/>'
        '<text x="50" y="27" font-family="Inter, Arial, sans-serif" font-weight="800" font-size="18" fill="#0f172a">CORP</text>'
        '<text x="103" y="27" font-family="Inter, Arial, sans-serif" font-weight="700" font-size="14" fill="#0070f2">ERP</text>'
        '</svg>'
    )
    import base64
    logo_corp_b64 = "data:image/svg+xml;base64," + base64.b64encode(svg_corp.encode("utf-8")).decode("ascii")

    svg_andina = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="150" height="44" viewBox="0 0 150 44">'
        '<rect width="40" height="40" x="2" y="2" rx="8" fill="#059669"/>'
        '<polygon points="22,8 34,32 10,32" fill="#ffffff"/>'
        '<text x="48" y="27" font-family="Montserrat, Arial, sans-serif" font-weight="800" font-size="16" fill="#064e3b">ANDINA</text>'
        '</svg>'
    )
    logo_andina_b64 = "data:image/svg+xml;base64," + base64.b64encode(svg_andina.encode("utf-8")).decode("ascii")

    with conn:
        # Asegurar que la primera empresa tenga nombre limpio y tema Horizon Blue
        emp1 = dbutil.query(conn, "SELECT id FROM empresas ORDER BY id ASC LIMIT 1").fetchone()
        if emp1:
            emp1_id = emp1["id"]
            dbutil.query(
                conn,
                "UPDATE empresas SET razon_social = ?, nombre_marca = ?, logo_data = ?, "
                "color_primario = ?, color_secundario = ?, color_sidebar = ?, color_fondo = ?, fuente_nombre = ? "
                "WHERE id = ?",
                (
                    "Empresa Corporativa S.A.S.",
                    "CORP",
                    logo_corp_b64,
                    "#0070f2",
                    "#1b90ff",
                    "#0f172a",
                    "#f4f6f9",
                    "Inter",
                    emp1_id,
                ),
            )

        # Asegurar una segunda empresa con tema Esmeralda para demostrar el branding multi-empresa
        emp2 = dbutil.query(conn, "SELECT id FROM empresas WHERE nit = ?", ("901987654",)).fetchone()
        if not emp2:
            dbutil.query(
                conn,
                "INSERT INTO empresas (nit, dv, razon_social, direccion, municipio, departamento, "
                "prefijo_resolucion, resolucion_dian, fecha_resolucion, clave_tecnica, tipo_ambiente, "
                "nombre_marca, logo_data, color_primario, color_secundario, color_sidebar, color_fondo, fuente_nombre) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "901987654",
                    "3",
                    "Inversiones Andinas S.A.S.",
                    "Av. El Dorado # 68B-85",
                    "Bogotá",
                    "Bogotá D.C.",
                    "AND",
                    "18764099887766",
                    "2026-01-15",
                    "fc8eac422eba16e22ffd8c6f94b3f40a6e38162c",
                    "2",
                    "ANDINA",
                    logo_andina_b64,
                    "#059669",
                    "#10b981",
                    "#064e3b",
                    "#f0fdf4",
                    "Montserrat",
                ),
            )
        else:
            dbutil.query(
                conn,
                "UPDATE empresas SET razon_social = ?, nombre_marca = ?, logo_data = ?, "
                "color_primario = ?, color_secundario = ?, color_sidebar = ?, color_fondo = ?, fuente_nombre = ? "
                "WHERE id = ?",
                (
                    "Inversiones Andinas S.A.S.",
                    "ANDINA",
                    logo_andina_b64,
                    "#059669",
                    "#10b981",
                    "#064e3b",
                    "#f0fdf4",
                    "Montserrat",
                    emp2["id"],
                ),
            )

        # Restablecer contraseñas conocidas para las cuentas de demostración
        demo_creds = [
            ("admin@sistema.com", "admin123", "Superadministrador de Plataforma"),
            ("admin@saluki.com", "admin123", "Superadministrador de Plataforma"),
            ("gerente@empresa.com", "Gerente123!", "Gerente General"),
            ("contador@empresa.com", "Contador123!", "Ana Contadora"),
            ("vendedor@empresa.com", "Vendedor123!", "Pedro Vendedor"),
            ("tesorero@empresa.com", "Tesorero123!", "Lucía Tesorera"),
            ("cajero@empresa.com", "Cajero123!", "Juan Cajero POS"),
            ("rrhh@empresa.com", "Nomina123!", "Elena Recursos Humanos"),
            ("almacen@empresa.com", "Almacen123!", "Marcos Almacenista"),
        ]
        for email, pwd, nombre in demo_creds:
            h, salt = auth.hash_password(pwd)
            dbutil.query(
                conn,
                "UPDATE usuarios SET hash_password = ?, salt = ?, nombre = ?, activo = 1, "
                "password_changed_at = ? WHERE email = ?",
                (h, salt, nombre, now_iso, email),
            )
    conn.close()


OVERLAY_JS = """
window.__clearTutorialOverlays = function() {
  document.querySelectorAll('.__tut-overlay-el').forEach(el => el.remove());
};

window.__drawTutorialOverlays = function(steps) {
  window.__clearTutorialOverlays();
  if (!Array.isArray(steps)) return;

  const container = document.createElement('div');
  container.className = '__tut-overlay-el';
  container.style.cssText = 'position:fixed;inset:0;pointer-events:none;z-index:999999;overflow:hidden;';
  document.body.appendChild(container);

  steps.forEach(step => {
    const el = document.querySelector(step.selector);
    if (!el) return;
    const rect = el.getBoundingClientRect();
    if (rect.width === 0 && rect.height === 0) return;

    const color = step.color || '#ef4444';
    const pad = step.pad !== undefined ? step.pad : 4;

    // 1. Highlight box around the element
    const box = document.createElement('div');
    box.style.cssText = `
      position: fixed;
      left: ${rect.left - pad}px;
      top: ${rect.top - pad}px;
      width: ${rect.width + pad * 2}px;
      height: ${rect.height + pad * 2}px;
      border: 3px solid ${color};
      border-radius: 8px;
      box-shadow: 0 0 0 5px rgba(239, 68, 68, 0.25), 0 8px 20px rgba(0, 0, 0, 0.22);
      background: rgba(239, 68, 68, 0.04);
      pointer-events: none;
    `;
    container.appendChild(box);

    // 2. Callout Pill (Numbered badge + instruction text)
    if (step.label) {
      const pill = document.createElement('div');
      pill.style.cssText = `
        position: fixed;
        display: inline-flex;
        align-items: center;
        gap: 8px;
        background: #0f172a;
        color: #ffffff;
        border: 2px solid ${color};
        border-radius: 999px;
        padding: 5px 14px 5px 6px;
        font-family: 'Inter', -apple-system, sans-serif;
        font-size: 13px;
        font-weight: 700;
        box-shadow: 0 10px 25px rgba(0,0,0,0.45);
        white-space: nowrap;
        z-index: 1000001;
      `;
      const numBadge = document.createElement('span');
      numBadge.textContent = step.num || '1';
      numBadge.style.cssText = `
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 24px;
        height: 24px;
        border-radius: 50%;
        background: ${color};
        color: #ffffff;
        font-size: 13px;
        font-weight: 800;
        flex-shrink: 0;
      `;
      const txt = document.createElement('span');
      txt.textContent = step.label;
      pill.appendChild(numBadge);
      pill.appendChild(txt);
      container.appendChild(pill);

      const pRect = pill.getBoundingClientRect();
      const pos = step.pos || 'top';
      let left = rect.left;
      let top = rect.top - pRect.height - 10;

      if (pos === 'bottom') {
        top = rect.bottom + 10;
        left = rect.left;
      } else if (pos === 'right') {
        top = rect.top + (rect.height - pRect.height) / 2;
        left = rect.right + 14;
      } else if (pos === 'left') {
        top = rect.top + (rect.height - pRect.height) / 2;
        left = rect.left - pRect.width - 14;
      } else if (pos === 'top-right') {
        top = rect.top - pRect.height - 10;
        left = rect.right - pRect.width;
      }

      // Clamp inside viewport
      left = Math.max(8, Math.min(window.innerWidth - pRect.width - 8, left));
      top = Math.max(8, Math.min(window.innerHeight - pRect.height - 8, top));
      pill.style.left = `${left}px`;
      pill.style.top = `${top}px`;
    }

    // 3. Mouse Cursor + Click Ripple on the target element
    if (step.cursor) {
      const cx = rect.left + (step.cursorXRatio !== undefined ? rect.width * step.cursorXRatio : Math.min(rect.width * 0.65, rect.width - 14));
      const cy = rect.top + (step.cursorYRatio !== undefined ? rect.height * step.cursorYRatio : rect.height * 0.55);

      // Click ripple circles
      const ripple = document.createElement('div');
      ripple.style.cssText = `
        position: fixed;
        left: ${cx - 22}px;
        top: ${cy - 22}px;
        width: 44px;
        height: 44px;
        border-radius: 50%;
        border: 3px solid #ef4444;
        background: rgba(239, 68, 68, 0.25);
        box-shadow: 0 0 0 8px rgba(239, 68, 68, 0.14);
        z-index: 1000002;
      `;
      container.appendChild(ripple);

      // Crisp SVG Pointer Cursor
      const cursorEl = document.createElement('div');
      cursorEl.style.cssText = `
        position: fixed;
        left: ${cx - 4}px;
        top: ${cy - 2}px;
        width: 42px;
        height: 42px;
        z-index: 1000003;
        filter: drop-shadow(0 4px 8px rgba(0,0,0,0.55));
      `;
      cursorEl.innerHTML = `
        <svg viewBox="0 0 32 32" width="42" height="42" xmlns="http://www.w3.org/2000/svg">
          <path d="M5 3 L5 26 L11.5 20 L16 29 L20 27 L15.5 18 L24 18 Z"
                fill="#ffffff" stroke="#0f172a" stroke-width="2.4" stroke-linejoin="round"/>
          <circle cx="5" cy="3" r="3" fill="#ef4444"/>
        </svg>
      `;
      container.appendChild(cursorEl);
    }
  });
};
"""


def shoot(page, filename, steps):
    page.evaluate(OVERLAY_JS)
    page.evaluate("steps => window.__drawTutorialOverlays(steps)", steps)
    time.sleep(0.2)
    path = os.path.join(OUT_DIR, filename)
    page.screenshot(path=path)
    page.evaluate("window.__clearTutorialOverlays()")
    print(f"✔ Captura guardada: {filename}")


def restore_corp_branding():
    """Restaura Empresa Corporativa S.A.S. al color Horizon Blue por defecto."""
    conn = db.get_connection()
    with conn:
        emp1 = dbutil.query(conn, "SELECT id FROM empresas ORDER BY id ASC LIMIT 1").fetchone()
        if emp1:
            dbutil.query(
                conn,
                "UPDATE empresas SET razon_social = ?, nombre_marca = ?, "
                "color_primario = '#0070f2', color_secundario = '#1b90ff', "
                "color_sidebar = '#0f172a', color_fondo = '#f4f6f9', fuente_nombre = 'Inter' "
                "WHERE id = ?",
                ("Empresa Corporativa S.A.S.", "CORP", emp1["id"]),
            )
    conn.close()


def main():
    prepare_demo_data()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1600, "height": 950})

        # ---------------------------------------------------------
        # 1. Login paso a paso
        # ---------------------------------------------------------
        page.goto("http://127.0.0.1:8000")
        page.wait_for_selector("#login-screen", state="visible")
        page.fill("#login-usuario", "admin@sistema.com")
        page.fill("#login-password", "admin123")
        time.sleep(0.4)
        shoot(
            page,
            "01_login_screen.png",
            [
                {"selector": "#login-usuario", "num": "1", "label": "Escribe tu correo corporativo", "pos": "top"},
                {"selector": "#login-password", "num": "2", "label": "Ingresa tu contraseña", "pos": "right"},
                {"selector": "#login-form button[type='submit']", "num": "3", "label": "Haz clic en Iniciar Sesión Segura", "pos": "bottom", "cursor": True},
            ],
        )

        # Ejecutar login
        page.click("#login-form button[type='submit']")
        page.wait_for_selector("#main-header", state="visible")
        time.sleep(1.2)

        # ---------------------------------------------------------
        # 2. Barra Superior (Scope Bar) y Menú Lateral
        # ---------------------------------------------------------
        shoot(
            page,
            "02_header_scope_bar.png",
            [
                {"selector": "#btn-toggle-sidebar", "num": "1", "label": "Colapsar / Expandir Menú Lateral", "pos": "bottom"},
                {"selector": "#sidebar-quick-search", "num": "2", "label": "Buscador rápido de módulos (Ctrl+K)", "pos": "right"},
                {"selector": "#select-empresa-activa", "num": "3", "label": "Cambiar de Empresa Activa", "pos": "bottom"},
                {"selector": "#btn-customize-active-empresa", "num": "4", "label": "Clic aquí para personalizar Logo, Colores y Fuente", "pos": "bottom", "cursor": True},
            ],
        )

        # ---------------------------------------------------------
        # 3. Dashboard Ejecutivo
        # ---------------------------------------------------------
        page.click(".tab-btn[data-tab='dashboard']")
        time.sleep(0.8)
        shoot(
            page,
            "03_dashboard.png",
            [
                {"selector": ".tab-btn[data-tab='dashboard']", "num": "1", "label": "Haz clic en Dashboard", "pos": "right", "cursor": True},
                {"selector": "#kpi-ventas-mes", "num": "2", "label": "KPIs Financieros en Tiempo Real", "pos": "bottom"},
                {"selector": "#btn-refresh-dashboard", "num": "3", "label": "Actualizar indicadores", "pos": "left"},
            ],
        )

        # ---------------------------------------------------------
        # 4. Estudio de Identidad Visual y Marca por Empresa
        # ---------------------------------------------------------
        page.click("#btn-customize-active-empresa")
        time.sleep(1.0)
        shoot(
            page,
            "04_branding_empresa.png",
            [
                {"selector": "#emp-razon-social", "num": "1", "label": "Cambia el Nombre de la Empresa", "pos": "top"},
                {"selector": "#emp-logo-file", "num": "2", "label": "Sube el Logo de tu Empresa (PNG/SVG)", "pos": "top"},
                {"selector": ".branding-presets", "num": "3", "label": "Elige un Tema de Color en 1 Clic o personaliza el HEX", "pos": "top"},
                {"selector": "#emp-fuente-file", "num": "4", "label": "Elige o sube tu propia Fuente (.ttf / .woff2)", "pos": "bottom"},
                {"selector": "#form-empresa button[type='submit']", "num": "5", "label": "Haz clic en Guardar para aplicar el tema", "pos": "right", "cursor": True},
            ],
        )

        # ---------------------------------------------------------
        # 5. Demostración Multi-Empresa con Tema Esmeralda en Vivo
        # ---------------------------------------------------------
        # Cambiar a la segunda empresa (Inversiones Andinas S.A.S.) en el selector superior
        page.click(".tab-btn[data-tab='dashboard']")
        time.sleep(0.5)
        options = page.query_selector_all("#select-empresa-activa option")
        if len(options) > 1:
            second_val = options[1].get_attribute("value")
            page.select_option("#select-empresa-activa", second_val)
            time.sleep(1.2)
        shoot(
            page,
            "05_multiempresa_tema_esmeralda.png",
            [
                {"selector": "#select-empresa-activa", "num": "1", "label": "Selecciona otra empresa registrada", "pos": "right", "cursor": True},
                {"selector": "#header-logo-box", "num": "2", "label": "Logo, Nombre, Fuente y Colores cambian automáticamente", "pos": "bottom"},
            ],
        )
        # Volver a la empresa 1 (Horizon Blue)
        if len(options) > 0:
            first_val = options[0].get_attribute("value")
            page.select_option("#select-empresa-activa", first_val)
            time.sleep(1.0)

        # ---------------------------------------------------------
        # 6. Facturación Electrónica DIAN (Paso a Paso)
        # ---------------------------------------------------------
        page.click(".tab-btn[data-tab='facturacion']")
        time.sleep(0.8)
        shoot(
            page,
            "06_facturacion.png",
            [
                {"selector": ".tab-btn[data-tab='facturacion']", "num": "1", "label": "Entra a Facturación", "pos": "right"},
                {"selector": "#fac-cliente", "num": "2", "label": "Selecciona el Cliente Adquirente", "pos": "bottom"},
                {"selector": "#btn-add-item", "num": "3", "label": "Agrega productos o servicios a la factura", "pos": "top"},
                {"selector": "#btn-emitir-factura", "num": "4", "label": "Haz clic en Emitir Factura Electrónica a DIAN", "pos": "top", "cursor": True},
            ],
        )

        # ---------------------------------------------------------
        # 7. Notas Crédito Electrónicas
        # ---------------------------------------------------------
        page.click(".tab-btn[data-tab='notas-credito']")
        time.sleep(0.8)
        shoot(
            page,
            "07_notas_credito.png",
            [
                {"selector": ".tab-btn[data-tab='notas-credito']", "num": "1", "label": "Selecciona Notas Crédito", "pos": "right"},
                {"selector": "#nc-factura-id", "num": "2", "label": "Elige la Factura que deseas anular o corregir", "pos": "bottom"},
                {"selector": "#nc-motivo", "num": "3", "label": "Selecciona el concepto oficial DIAN", "pos": "bottom"},
                {"selector": "#form-nota-credito button[type='submit']", "num": "4", "label": "Haz clic en Emitir Nota Crédito", "pos": "top", "cursor": True},
            ],
        )

        # ---------------------------------------------------------
        # 8. Ciclo Comercial en Cascada
        # ---------------------------------------------------------
        page.click(".tab-btn[data-tab='ciclo-comercial']")
        time.sleep(0.8)
        shoot(
            page,
            "08_ciclo_comercial.png",
            [
                {"selector": ".tab-btn[data-tab='ciclo-comercial']", "num": "1", "label": "Abre Ciclo Comercial", "pos": "right"},
                {"selector": "#cot-cliente", "num": "2", "label": "Selecciona el cliente y productos a cotizar", "pos": "bottom"},
                {"selector": "#form-cotizacion button[type='submit']", "num": "3", "label": "Haz clic para Crear Cotización y avanzar a Pedido/Factura", "pos": "top", "cursor": True},
            ],
        )

        # ---------------------------------------------------------
        # 9. Punto de Venta POS Electrónico
        # ---------------------------------------------------------
        page.click(".tab-btn[data-tab='pos']")
        time.sleep(0.8)
        shoot(
            page,
            "09_pos_system.png",
            [
                {"selector": ".tab-btn[data-tab='pos']", "num": "1", "label": "Abre Punto de Venta (POS)", "pos": "right"},
                {"selector": "#pos-base-inicial", "num": "2", "label": "Digita la base de efectivo inicial de caja", "pos": "bottom"},
                {"selector": "#form-abrir-turno button[type='submit']", "num": "3", "label": "Haz clic en Abrir Turno para empezar a vender", "pos": "right", "cursor": True},
            ],
        )

        # ---------------------------------------------------------
        # 10. Cartera y Cuentas por Cobrar (CxC)
        # ---------------------------------------------------------
        page.click(".tab-btn[data-tab='cartera']")
        time.sleep(0.8)
        shoot(
            page,
            "10_cartera.png",
            [
                {"selector": ".tab-btn[data-tab='cartera']", "num": "1", "label": "Haz clic en Cartera (CxC)", "pos": "right"},
                {"selector": ".semaphore-grid", "num": "2", "label": "Semáforo de Edades de Cartera por vencimiento", "pos": "bottom"},
                {"selector": "#form-recaudo button[type='submit']", "num": "3", "label": "Haz clic para Registrar Recibo de Caja / Abono", "pos": "top", "cursor": True},
            ],
        )

        # ---------------------------------------------------------
        # 11. Buzón Compras, RADIAN y Cuentas por Pagar (CxP)
        # ---------------------------------------------------------
        page.click(".tab-btn[data-tab='compras-cxp']")
        time.sleep(0.8)
        shoot(
            page,
            "11_compras_cxp.png",
            [
                {"selector": ".tab-btn[data-tab='compras-cxp']", "num": "1", "label": "Entra a Compras & CxP", "pos": "right"},
                {"selector": "#xml-upload-zone", "num": "2", "label": "Arrastra o selecciona el XML/ZIP del proveedor", "pos": "bottom"},
                {"selector": "#btn-procesar-xml", "num": "3", "label": "Haz clic en Procesar XML y emitir eventos RADIAN", "pos": "right", "cursor": True},
            ],
        )

        # ---------------------------------------------------------
        # 12. Documento Soporte Electrónico (CUDS)
        # ---------------------------------------------------------
        page.click(".tab-btn[data-tab='documento-soporte']")
        time.sleep(0.8)
        shoot(
            page,
            "12_documento_soporte.png",
            [
                {"selector": ".tab-btn[data-tab='documento-soporte']", "num": "1", "label": "Selecciona Doc. Soporte", "pos": "right"},
                {"selector": "#ds-proveedor-nit", "num": "2", "label": "Ingresa NIT y nombre del proveedor no obligado", "pos": "bottom"},
                {"selector": "#form-doc-soporte button[type='submit']", "num": "3", "label": "Haz clic en Emitir Documento Soporte (CUDS)", "pos": "top", "cursor": True},
            ],
        )

        # ---------------------------------------------------------
        # 13. Precios, Inventario y Lotes
        # ---------------------------------------------------------
        page.click(".tab-btn[data-tab='precios']")
        time.sleep(0.8)
        shoot(
            page,
            "13_listas_precios.png",
            [
                {"selector": ".tab-btn[data-tab='precios']", "num": "1", "label": "Haz clic en Precios & Lotes", "pos": "right"},
                {"selector": "#lp-nombre", "num": "2", "label": "Define el nombre y descuento de la Lista de Precios", "pos": "bottom"},
                {"selector": "#form-lista-precios button[type='submit']", "num": "3", "label": "Haz clic en Crear Lista de Precios", "pos": "right", "cursor": True},
            ],
        )

        # ---------------------------------------------------------
        # 14. Contabilidad General PUC y Cierre Fiscal
        # ---------------------------------------------------------
        page.click(".tab-btn[data-tab='contabilidad']")
        time.sleep(0.8)
        shoot(
            page,
            "14_contabilidad_puc.png",
            [
                {"selector": ".tab-btn[data-tab='contabilidad']", "num": "1", "label": "Haz clic en Contabilidad", "pos": "right"},
                {"selector": "#contab-ecuacion-banner", "num": "2", "label": "Verifica que Débitos = Créditos en tiempo real", "pos": "bottom"},
                {"selector": "#btn-load-balance", "num": "3", "label": "Haz clic para actualizar el Balance de Prueba PUC", "pos": "left", "cursor": True},
            ],
        )

        # ---------------------------------------------------------
        # 15. Impuestos DIAN (Formularios 300, 350 y Exógena)
        # ---------------------------------------------------------
        page.click(".tab-btn[data-tab='impuestos']")
        time.sleep(0.8)
        shoot(
            page,
            "15_impuestos_dian.png",
            [
                {"selector": ".tab-btn[data-tab='impuestos']", "num": "1", "label": "Haz clic en Impuestos", "pos": "right"},
                {"selector": "#f300-periodo", "num": "2", "label": "Selecciona el Año y Periodo a declarar", "pos": "bottom"},
                {"selector": "#btn-generar-f300", "num": "3", "label": "Haz clic en Generar Borrador Formulario 300 / 350", "pos": "bottom", "cursor": True},
            ],
        )

        # ---------------------------------------------------------
        # 16. Nómina Electrónica DIAN
        # ---------------------------------------------------------
        page.click(".tab-btn[data-tab='nomina']")
        time.sleep(0.8)
        shoot(
            page,
            "16_nomina_electronica.png",
            [
                {"selector": ".tab-btn[data-tab='nomina']", "num": "1", "label": "Haz clic en Nómina", "pos": "right"},
                {"selector": "#emp-nombres", "num": "2", "label": "Registra los datos del empleado y salario base", "pos": "bottom"},
                {"selector": "#form-empleado button[type='submit']", "num": "3", "label": "Haz clic en Guardar Empleado y Liquidar Nómina", "pos": "top", "cursor": True},
            ],
        )

        # ---------------------------------------------------------
        # 17. Consola de Administración Multi-Empresa y Sub-Pestañas
        # ---------------------------------------------------------
        page.click(".tab-btn[data-tab='admin']")
        time.sleep(0.8)
        shoot(
            page,
            "17_consola_sistema.png",
            [
                {"selector": ".tab-btn[data-tab='admin']", "num": "1", "label": "Entra a Admin Sistema", "pos": "right"},
                {"selector": ".admin-subnav", "num": "2", "label": "Navega entre Empresas, Usuarios, Roles y Accesos", "pos": "bottom"},
                {"selector": "#tbody-empresas button.btn-primary", "num": "3", "label": "Haz clic en 🎨 Marca / Editar en cualquier empresa", "pos": "left", "cursor": True},
            ],
        )

        # ---------------------------------------------------------
        # 18. Matriz de Permisos y Segregación de Funciones (SoD)
        # ---------------------------------------------------------
        page.click(".admin-subnav-btn[data-admin-filter='roles']")
        time.sleep(0.6)
        perm_btn = page.query_selector("#tbody-roles button.btn-primary")
        if perm_btn:
            perm_btn.click()
            time.sleep(0.8)
        shoot(
            page,
            "18_sod_permisos_modal.png",
            [
                {"selector": "#sod-warnings-container", "num": "1", "label": "Auditoría SoD en vivo: alerta de combinaciones riesgosas", "pos": "top"},
                {"selector": "#permisos-modal .modal-actions", "num": "2", "label": "Selecciona o desmarca permisos y guarda cambios", "pos": "top", "cursor": True},
            ],
        )
        # Cerrar modal de permisos antes de cerrar sesión
        page.evaluate("const m = document.getElementById('permisos-modal'); if (m) m.style.display = 'none';")
        time.sleep(0.3)

        # Cerrar sesión para tomar las vistas por rol
        page.click("#btn-logout")
        time.sleep(0.8)

        # ---------------------------------------------------------
        # 19. Vista Acotada por Cargo: Vendedor Comercial
        # ---------------------------------------------------------
        page.fill("#login-usuario", "vendedor@empresa.com")
        page.fill("#login-password", "Vendedor123!")
        page.click("#login-form button[type='submit']")
        page.wait_for_selector("#main-header", state="visible")
        time.sleep(1.0)
        page.click(".tab-btn[data-tab='ciclo-comercial']")
        time.sleep(0.8)
        shoot(
            page,
            "19_vista_vendedor.png",
            [
                {"selector": "#user-badge", "num": "1", "label": "Sesión activa como VENDEDOR", "pos": "bottom"},
                {"selector": "#main-nav-tabs", "num": "2", "label": "Menú simplificado: solo módulos comerciales autorizados", "pos": "right"},
                {"selector": "#form-cotizacion button[type='submit']", "num": "3", "label": "El vendedor crea sus propias cotizaciones aquí", "pos": "top", "cursor": True},
            ],
        )
        page.click("#btn-logout")
        time.sleep(0.8)

        # ---------------------------------------------------------
        # 20. Vista Acotada por Cargo: Tesorero / CxP
        # ---------------------------------------------------------
        page.fill("#login-usuario", "tesorero@empresa.com")
        page.fill("#login-password", "Tesorero123!")
        page.click("#login-form button[type='submit']")
        page.wait_for_selector("#main-header", state="visible")
        time.sleep(1.0)
        page.click(".tab-btn[data-tab='compras-cxp']")
        time.sleep(0.8)
        shoot(
            page,
            "20_vista_tesorero.png",
            [
                {"selector": "#user-badge", "num": "1", "label": "Sesión activa como TESORERO", "pos": "bottom"},
                {"selector": ".tab-btn[data-tab='compras-cxp']", "num": "2", "label": "Acceso enfocado en Compras, RADIAN y Cartera", "pos": "right", "cursor": True},
            ],
        )
        page.click("#btn-logout")
        time.sleep(0.8)

        # ---------------------------------------------------------
        # 21. Vista Acotada por Cargo: Cajero POS
        # ---------------------------------------------------------
        page.fill("#login-usuario", "cajero@empresa.com")
        page.fill("#login-password", "Cajero123!")
        page.click("#login-form button[type='submit']")
        page.wait_for_selector("#main-header", state="visible")
        time.sleep(1.0)
        page.click(".tab-btn[data-tab='pos']")
        time.sleep(0.8)
        shoot(
            page,
            "21_vista_cajero_pos.png",
            [
                {"selector": "#user-badge", "num": "1", "label": "Sesión activa como CAJERO POS", "pos": "bottom"},
                {"selector": ".tab-btn[data-tab='pos']", "num": "2", "label": "Interfaz exclusiva de Caja POS de mostrador", "pos": "right", "cursor": True},
            ],
        )
        page.click("#btn-logout")
        time.sleep(0.8)

        # ---------------------------------------------------------
        # 22. Vista Acotada por Cargo: Recursos Humanos (Nómina)
        # ---------------------------------------------------------
        page.fill("#login-usuario", "rrhh@empresa.com")
        page.fill("#login-password", "Nomina123!")
        page.click("#login-form button[type='submit']")
        page.wait_for_selector("#main-header", state="visible")
        time.sleep(1.0)
        page.click(".tab-btn[data-tab='nomina']")
        time.sleep(0.8)
        shoot(
            page,
            "22_vista_rrhh.png",
            [
                {"selector": "#user-badge", "num": "1", "label": "Sesión activa como RECURSOS HUMANOS", "pos": "bottom"},
                {"selector": ".tab-btn[data-tab='nomina']", "num": "2", "label": "Acceso exclusivo a Nómina Electrónica y Empleados", "pos": "right", "cursor": True},
            ],
        )

        browser.close()
    restore_corp_branding()
    print("✅ Todas las capturas paso a paso con cursor y callouts fueron generadas exitosamente!")


if __name__ == "__main__":
    main()
