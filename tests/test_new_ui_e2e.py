"""Test e2e de las nuevas funcionalidades UI: Notas Débito, PDF/ZIP y Envío de Correo."""
import time
import socket
import threading
from http.server import HTTPServer
from unittest.mock import patch
from playwright.sync_api import sync_playwright
import pytest
from sap_colombia import dbutil
from sap_colombia import database as db
from sap_colombia.auth import hash_password, seed_usuarios
from web_server import SapWebHandler
from sap_colombia.dian_client import TransmisionResult


def test_new_ui_features():
    # Setup test server on free port
    db.init_db(seed=True)

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    server = HTTPServer(("127.0.0.1", port), SapWebHandler)
    srv_thread = threading.Thread(target=server.serve_forever, daemon=True)
    srv_thread.start()
    time.sleep(0.5)

    base_url = f"http://127.0.0.1:{port}"

    try:
        with patch("sap_colombia.dian_client.DianClient.transmitir_xml") as mock_dian, \
             patch("sap_colombia.mail_notifier._enviar_smtp") as mock_mail:
            mock_dian.return_value = TransmisionResult(
                estado="Aceptada",
                track_id="TRK-TEST-ND-UI",
                status_code="00",
                status_description="Documento validado con exito",
            )
            mock_mail.return_value = True

            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=True,
                    executable_path="/usr/bin/chromium",
                    args=["--no-sandbox", "--disable-setuid-sandbox"]
                )
                page = browser.new_page(viewport={"width": 1920, "height": 1080})
                page.on("dialog", lambda d: d.accept())

                # 1. Login
                from test_ui_multiyear_e2e import _ui_login, _ui_change_password
                page.goto(base_url, wait_until="networkidle")
                _ui_login(page, "admin@saluki.com", "admin123")
                try:
                    page.wait_for_selector("#force-change-screen", state="visible", timeout=3000)
                    _ui_change_password(page, "Admin123!")
                except Exception:
                    pass
                page.wait_for_selector("#main-header", state="visible", timeout=15000)

                # 2. Facturación: emitir factura
                page.click(".tab-btn[data-tab='facturacion']")
                page.wait_for_selector("#cliente-select", state="visible", timeout=15000)
                page.select_option("#cliente-select", index=1)
                page.click("#btn-add-linea")
                page.locator("#lineas-tbody tr:first-child input[type=number]").first.fill("2")
                page.click("#btn-emitir-dian")

                # 3. Verificar panel de resultado DIAN y botones PDF / ZIP / Email
                page.wait_for_selector("#resultado-dian >> visible=true", timeout=15000)
                pdf_href = page.locator("#btn-descargar-pdf").get_attribute("href")
                zip_href = page.locator("#btn-descargar-zip").get_attribute("href")
                assert "/pdf" in pdf_href, f"Enlace PDF invalido: {pdf_href}"
                assert "/zip" in zip_href, f"Enlace ZIP invalido: {zip_href}"

                # 4. Verificar tabla de historial y acciones
                page.wait_for_selector("#historial-tbody tr", timeout=15000)
                first_row = page.locator("#historial-tbody tr").first
                assert first_row.locator("a:has-text('PDF')").is_visible()
                assert first_row.locator("a:has-text('ZIP')").is_visible()
                assert first_row.locator("button:has-text('✉️')").is_visible()

                # 5. Emitir Nota Débito (Tipo 92 UBL)
                page.click(".tab-btn[data-tab='notas-debito']")
                page.wait_for_selector("#nd-factura-select", state="visible", timeout=15000)
                page.select_option("#nd-factura-select", index=1)
                page.select_option("#nd-concepto", value="1")
                page.fill("#nd-descripcion", "Intereses por mora UI")
                page.fill("#nd-subtotal", "30000")
                page.select_option("#nd-tarifa-iva", value="IVA_19")

                # Preview calculado
                total_preview = page.locator("#nd-total-preview").inner_text()
                assert "35" in total_preview or "COP" in total_preview

                # Click emitir ND
                page.click("#btn-emitir-nd")
                page.wait_for_selector("#nd-resultado >> visible=true", timeout=20000)

                nd_consecutivo = page.locator("#nd-res-consecutivo").inner_text().strip()
                nd_cude = page.locator("#nd-res-cude").inner_text().strip()
                assert len(nd_cude) == 96, f"CUDE esperado de 96 caracteres, obtuve {len(nd_cude)}"
                assert nd_consecutivo, "Consecutivo ND no generado"

                # Verificar tabla de Notas Débito
                page.wait_for_selector("#nd-tbody tr", timeout=10000)
                nd_rows = page.locator("#nd-tbody tr").count()
                assert nd_rows >= 1, "No se encontro la Nota Débito en la tabla"

                # 6. Test Enviar Factura por Correo (Modal)
                page.click(".tab-btn[data-tab='facturacion']")
                page.wait_for_selector("#historial-tbody tr", timeout=15000)
                page.locator("#historial-tbody tr").first.locator("button:has-text('✉️')").click()

                page.wait_for_selector("#modal-email-factura >> visible=true", timeout=10000)
                page.fill("#email-factura-destinatario", "cliente.auditado@empresa.com")
                page.click("#btn-confirmar-envio-email")

                # Esperar respuesta de envio
                page.wait_for_selector("#email-envio-resultado >> visible=true", timeout=15000)
                res_email_text = page.locator("#email-envio-resultado").inner_text()
                assert "enviado exitosamente" in res_email_text.lower() or "✓" in res_email_text

                browser.close()
    finally:
        from test_ui_multiyear_e2e import _forzar_cambio_password_admin
        _forzar_cambio_password_admin("admin123")
        server.shutdown()
        server.server_close()
