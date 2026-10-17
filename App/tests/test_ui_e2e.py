#!/usr/bin/env python3
"""E2E UI test for SAP Colombia - Playwright + Chromium"""
import sys, time
from playwright.sync_api import sync_playwright

BASE = 'http://localhost:8000'
passed = 0
failed = 0

def log(msg):
    print(f'\n{"="*60}')
    print(msg)
    print(f'{"="*60}')

def ok(msg):
    global passed
    passed += 1
    log(f'   PASSED: {msg}')

def fail(msg):
    global failed
    failed += 1
    log(f'   FAILED: {msg}')

def main():
    global passed, failed
    with sync_playwright() as pw:
        headless = '--headless' in sys.argv
        browser = pw.chromium.launch(
            headless=headless,
            executable_path='/usr/bin/chromium',
            args=['--no-sandbox', '--start-maximized']
        )
        ctx = browser.new_context(viewport={'width': 1920, 'height': 1080}, device_scale_factor=1)
        page = ctx.new_page()
        console_errors = []
        page.on('console', lambda m: console_errors.append(m.text) if m.type == 'error' else None)
        page.on('pageerror', lambda e: console_errors.append(str(e)))
        page.on('dialog', lambda d: d.accept())

        # 1. LOGIN
        log('1. LOGIN COMO NUEVO CLIENTE')
        print('\n>>> VENTANA DE CHROME ABIERTA <<<')
        print('>>> Esperando 10 segundos para que veas la ventana... <<<')
        page.goto(BASE)
        page.wait_for_timeout(10000)
        page.wait_for_selector('#login-screen', state='visible', timeout=10000)
        page.fill('#login-usuario', 'admin@saluki.com')
        page.fill('#login-password', 'admin123')
        page.click('#login-form button[type="submit"]')
        page.wait_for_timeout(3000)

        fc = page.locator('#force-change-screen')
        if fc.is_visible():
            log('   -> Cambio de contrasena obligatorio')
            page.fill('#fc-password', 'admin12345')
            page.fill('#fc-password-confirm', 'admin12345')
            page.click('#force-change-form button[type="submit"]')
            page.wait_for_timeout(3000)

        if page.locator('.tab-btn[data-tab="nomina"]').is_visible():
            ok('Login exitoso, app principal visible')
        else:
            fail('Login fallido')
            err = page.locator('#login-error')
            if err.is_visible():
                log(f'   ERROR: {err.text_content()}')
            browser.close()
            sys.exit(1)

        # 2. CREAR EMPRESA
        log('2. CREAR EMPRESA')
        page.click('.tab-btn[data-tab="admin"]')
        page.wait_for_timeout(500)
        page.click('#btn-new-empresa')
        page.wait_for_timeout(500)

        card = page.locator('#card-empresa-form')
        form = page.locator('#form-empresa')
        if not form.is_visible():
            fail('Form empresa no visible despues de click')
            browser.close()
            sys.exit(1)

        page.locator('#form-empresa #emp-nit').fill('900123456-7')
        page.locator('#form-empresa #emp-razon-social').fill('Colombia Tech S.A.S.')
        page.locator('#form-empresa #emp-direccion').fill('Calle 10 #20-30')
        page.locator('#form-empresa #emp-municipio').fill('Bogota')
        page.locator('#form-empresa #emp-departamento').fill('Cundinamarca')
        page.locator('#form-empresa #emp-prefijo').fill('FAC')
        page.locator('#form-empresa #emp-resolucion').fill('0001234')
        page.locator('#form-empresa #emp-fecha-resolucion').fill('2026-01-01')
        page.locator('#form-empresa #emp-clave').fill('test_clave_123')
        page.click('#form-empresa button[type="submit"]')
        page.wait_for_timeout(2000)

        count = page.locator('#tbody-empresas tr').count()
        if count >= 2:
            ok(f'{count} empresas en tabla')
        else:
            fail(f'Solo {count} empresas')

        # 3. CREAR 3 EMPLEADOS
        log('3. CREAR 3 EMPLEADOS')
        page.click('.tab-btn[data-tab="nomina"]')
        page.wait_for_timeout(500)

        empleados = [
            ('1001', 'Maria', 'Perez Garcia', '4500000', '175405'),
            ('1002', 'Carlos', 'Lopez Ramirez', '3200000', '175405'),
            ('1003', 'Ana', 'Martinez Torres', '2800000', '175405'),
        ]

        for nit, nombres, apellidos, salario, aux in empleados:
            if not page.locator('#form-empleado').is_visible():
                page.click('#btn-toggle-form-empleado')
                page.wait_for_timeout(300)
            page.locator('#form-empleado #emp-nit').fill(nit)
            page.locator('#form-empleado #emp-nombres').fill(nombres)
            page.locator('#form-empleado #emp-apellidos').fill(apellidos)
            page.locator('#form-empleado #emp-salario').fill(salario)
            page.locator('#form-empleado #emp-auxilio').fill(aux)
            page.click('#form-empleado button[type="submit"]')
            page.wait_for_timeout(1500)

        emp_count = page.locator('#tabla-empleados tbody tr').count()
        if emp_count == 3:
            ok('3 empleados creados')
        else:
            fail(f'Empleados: {emp_count} (esperado 3)')

        actives = page.locator('#nomina-summary-actives').text_content().strip()
        if actives == '3':
            ok(f'Summary actives = {actives}')
        else:
            fail(f'Summary actives = {actives}')

        # 4. LIQUIDAR
        log('4. LIQUIDAR NOMINAS')
        print('Esperando 5 segundos antes de liquidar...')
        page.wait_for_timeout(5000)
        page.click('.nomina-subtab[data-nomina-tab="procesar"]')
        page.wait_for_timeout(500)
        page.fill('#nomina-periodo-inicio', '2026-10-01')
        page.fill('#nomina-periodo-fin', '2026-10-31')
        page.click('#btn-liquidar-todos')
        page.wait_for_timeout(8000)

        resultado = page.locator('#resultado-liquidacion')
        if resultado.is_visible():
            text = resultado.text_content()
            if '0 fallos' in text:
                ok(f'Liquidacion: {text}')
            else:
                fail(f'Fallos en liquidacion: {text}')
        else:
            fail('Sin resultado liquidacion')

        # 5. EMITIR + PAGAR
        log('5. EMITIR + PAGAR TODOS')
        page.click('#btn-emitir-todos')
        page.wait_for_timeout(12000)

        re = page.locator('#resultado-nomina')
        if re.is_visible():
            text = re.text_content()
            if '0 fallos' in text:
                ok(f'Emitir+Pagar: {text}')
            else:
                fail(f'Fallos: {text}')
        else:
            fail('Sin resultado emision')

        # 6. HISTORIAL
        log('6. HISTORIAL')
        page.click('.nomina-subtab[data-nomina-tab="historial"]')
        page.wait_for_timeout(1000)

        nom_count = page.locator('#tabla-nominas tbody tr').count()
        if nom_count == 3:
            ok('3 nominas en historial')
        else:
            fail(f'Nominas: {nom_count}')

        for i in range(nom_count):
            cells = page.locator('#tabla-nominas tbody tr').nth(i).locator('td')
            consec = cells.nth(1).text_content().strip()
            nombre = cells.nth(3).text_content().strip()
            neto = cells.nth(6).text_content().strip()
            dian = cells.nth(7).text_content().strip()
            pago = cells.nth(8).text_content().strip()
            log(f'   NOM #{consec}: {nombre} | {neto} | {dian} | {pago}')

        # 7. FILTRO
        log('7. FILTRO PENDIENTE')
        page.select_option('#nomina-historial-filtro', 'PENDIENTE')
        page.wait_for_timeout(1000)
        pend = page.locator('#tabla-nominas tbody tr').count()
        if pend == 0:
            ok('0 pendientes')
        else:
            fail(f'{pend} pendientes')

        # 8. SUMMARY
        log('8. SUMMARY')
        a = page.locator('#nomina-summary-actives').text_content().strip()
        t = page.locator('#nomina-summary-total').text_content().strip()
        c = page.locator('#nomina-summary-costo').text_content().strip()
        log(f'   Activos: {a} | Total: {t} | Costo: {c}')

        # 9. CONSOLA
        log('9. CONSOLA')
        real_errs = [e for e in console_errors if 'favicon' not in e.lower()]
        if real_errs:
            for e in real_errs:
                fail(f'Console: {e}')
        else:
            ok('Sin errores')

        page.screenshot(path='/tmp/sap_final.png', full_page=True)
        browser.close()

    print(f'\n{"="*60}')
    print(f'RESULTADO: {passed} PASSED, {failed} FAILED')
    print(f'{"="*60}')
    sys.exit(1 if failed > 0 else 0)

if __name__ == '__main__':
    main()
