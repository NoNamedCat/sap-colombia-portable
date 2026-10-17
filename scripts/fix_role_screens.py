import time
from playwright.sync_api import sync_playwright

OUT_DIR = "/home/cattus/.gemini/antigravity-cli/brain/649668c6-1e2d-4580-b353-401ac6713f2c/screenshots"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1400, "height": 900})

    # 17. Vista Vendedor en Ciclo Comercial
    page.goto("http://127.0.0.1:8000")
    page.fill("#login-usuario", "vendedor@empresa.com")
    page.fill("#login-password", "Vendedor123!")
    page.click("#login-form button[type=submit]")
    page.wait_for_selector("#main-header", state="visible")
    page.click(".tab-btn[data-tab='ciclo-comercial']")
    time.sleep(1)
    page.screenshot(path=f"{OUT_DIR}/17_vista_vendedor.png")
    print("17. Vista Vendedor tomada")
    page.click("#btn-logout")
    time.sleep(1)

    # 18. Vista Tesorero en Buzón Compras & CxP
    page.fill("#login-usuario", "tesorero@empresa.com")
    page.fill("#login-password", "Tesorero123!")
    page.click("#login-form button[type=submit]")
    page.wait_for_selector("#main-header", state="visible")
    page.click(".tab-btn[data-tab='compras-cxp']")
    time.sleep(1)
    page.screenshot(path=f"{OUT_DIR}/18_vista_tesorero.png")
    print("18. Vista Tesorero tomada")

    # 19. Vista Cajero POS
    page.click("#btn-logout")
    time.sleep(1)
    page.fill("#login-usuario", "cajero@empresa.com")
    page.fill("#login-password", "Cajero123!")
    page.click("#login-form button[type=submit]")
    page.wait_for_selector("#main-header", state="visible")
    page.click(".tab-btn[data-tab='pos']")
    time.sleep(1)
    page.screenshot(path=f"{OUT_DIR}/19_vista_cajero_pos.png")
    print("19. Vista Cajero POS tomada")

    # 20. Vista Recursos Humanos
    page.click("#btn-logout")
    time.sleep(1)
    page.fill("#login-usuario", "rrhh@empresa.com")
    page.fill("#login-password", "Nomina123!")
    page.click("#login-form button[type=submit]")
    page.wait_for_selector("#main-header", state="visible")
    page.click(".tab-btn[data-tab='nomina']")
    time.sleep(1)
    page.screenshot(path=f"{OUT_DIR}/20_vista_rrhh.png")
    print("20. Vista RRHH tomada")

    browser.close()
