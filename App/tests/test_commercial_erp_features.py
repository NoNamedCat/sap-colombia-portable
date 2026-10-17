"""Pruebas unitarias e integración para módulos comerciales y de producción ERP SAP Colombia:
1. Buzón de recepción de facturas de proveedores + RADIAN (030, 032, 033).
2. Cuentas por Pagar (CxP) y Comprobantes de Egreso (CE) con partida doble.
3. Ciclo comercial en cascada (Cotización ➔ Pedido ➔ Remisión ➔ Factura Electrónica).
4. Sistema POS Electrónico (Res. DIAN 000165/2023), apertura/cierre de caja y tirilla térmica.
5. Múltiples listas de precios y trazabilidad de inventarios (lotes y traslados).
6. Borradores de Formularios DIAN 300 (IVA) y 350 (Retención en la fuente).
7. Seguridad y autenticación multifactor 2FA / TOTP (RFC 6238).
"""

import time
import uuid
import pytest
from decimal import Decimal

from sap_colombia import database as db
from sap_colombia import accounting_engine
from sap_colombia import vendor_bills
from sap_colombia import accounts_payable
from sap_colombia import commercial_cycle
from sap_colombia import pos_system
from sap_colombia import price_lists
from sap_colombia import inventory
from sap_colombia import tax_forms
from sap_colombia import auth


SAMPLE_INVOICE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
         xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
         xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
    <cbc:ID>SETP-990000001</cbc:ID>
    <cbc:UUID>9876543210abcdef9876543210abcdef9876543210abcdef9876543210abcdef9876543210abcdef9876543210abcdef</cbc:UUID>
    <cbc:IssueDate>2026-02-15</cbc:IssueDate>
    <cbc:DueDate>2026-03-15</cbc:DueDate>
    <cac:AccountingSupplierParty>
        <cac:Party>
            <cac:PartyIdentification>
                <cbc:ID>901234567</cbc:ID>
            </cac:PartyIdentification>
            <cac:PartyLegalEntity>
                <cbc:RegistrationName>Distribuidora Colombia S.A.S.</cbc:RegistrationName>
            </cac:PartyLegalEntity>
        </cac:Party>
    </cac:AccountingSupplierParty>
    <cac:TaxTotal>
        <cbc:TaxAmount currencyID="COP">190000.00</cbc:TaxAmount>
        <cac:TaxSubtotal>
            <cbc:TaxableAmount currencyID="COP">1000000.00</cbc:TaxableAmount>
            <cbc:TaxAmount currencyID="COP">190000.00</cbc:TaxAmount>
            <cac:TaxCategory>
                <cbc:Percent>19.00</cbc:Percent>
            </cac:TaxCategory>
        </cac:TaxSubtotal>
    </cac:TaxTotal>
    <cac:WithholdingTaxTotal>
        <cbc:TaxAmount currencyID="COP">25000.00</cbc:TaxAmount>
    </cac:WithholdingTaxTotal>
    <cac:LegalMonetaryTotal>
        <cbc:LineExtensionAmount currencyID="COP">1000000.00</cbc:LineExtensionAmount>
        <cbc:PayableAmount currencyID="COP">1165000.00</cbc:PayableAmount>
    </cac:LegalMonetaryTotal>
</Invoice>"""


def make_sample_xml(cufe_suffix: str = "", consec_suffix: str = "") -> str:
    xml = SAMPLE_INVOICE_XML
    if cufe_suffix:
        xml = xml.replace(
            "9876543210abcdef9876543210abcdef9876543210abcdef9876543210abcdef9876543210abcdef9876543210abcdef",
            (cufe_suffix * 3)[:96],
        )
    if consec_suffix:
        xml = xml.replace("SETP-990000001", f"SETP-{consec_suffix}")
    return xml


def test_vendor_bills_parsing_and_journal():
    """Valida el procesamiento de XML de proveedor, causación automática y partida doble."""
    db.init_db(seed=True)
    xml = make_sample_xml(uuid.uuid4().hex, f"99{uuid.uuid4().hex[:6]}")
    factura = vendor_bills.procesar_factura_proveedor(xml, auto_contabilizar=False)
    assert factura is not None
    assert factura["proveedor_nit"] == "901234567"
    assert factura["proveedor_nombre"] == "Distribuidora Colombia S.A.S."
    assert Decimal(factura["subtotal"]) == Decimal("1000000.00")
    assert Decimal(factura["total_iva"]) == Decimal("190000.00")
    assert Decimal(factura["retefuente"]) == Decimal("25000.00")
    assert Decimal(factura["total"]) == Decimal("1165000.00")

    # Verificar que se creó la cuenta por pagar (CxP)
    cxp_list = accounts_payable.listar_cuentas_por_pagar(solo_pendientes=True)
    found = [c for c in cxp_list if c["factura_compra_id"] == factura["id"]]
    assert len(found) == 1
    assert Decimal(found[0]["saldo_pendiente"]) == Decimal("1165000.00")

    # Verificar asiento contable generado
    asiento = accounting_engine.contabilizar_factura_compra(factura)
    assert asiento is not None
    assert Decimal(asiento["total_debito"]) == Decimal(asiento["total_credito"])


def test_radian_vendor_event_emission():
    """Valida la emisión de eventos RADIAN 030, 032 y 033 para una factura de compra."""
    db.init_db(seed=True)
    xml = make_sample_xml(uuid.uuid4().hex, f"99{uuid.uuid4().hex[:6]}")
    factura = vendor_bills.procesar_factura_proveedor(xml, auto_contabilizar=False)
    fid = factura["id"]

    # 1. Acuse de recibo (030)
    ev030 = vendor_bills.emitir_evento_radian_proveedor(fid, "030", observaciones="Acuse factura recibido")
    assert ev030["codigo_evento"] == "030"
    assert ev030["cude"] is not None
    assert len(ev030["cude"]) == 96  # SHA-384 hex
    assert ev030["estado_radian"] == "RECIBIDO_030"

    # 2. Recepción de bienes/servicios (032)
    ev032 = vendor_bills.emitir_evento_radian_proveedor(fid, "032")
    assert ev032["codigo_evento"] == "032"
    assert ev032["estado_radian"] == "BIENES_032"

    # 3. Aceptación expresa (033)
    ev033 = vendor_bills.emitir_evento_radian_proveedor(fid, "033")
    assert ev033["codigo_evento"] == "033"
    assert ev033["estado_radian"] == "ACEPTADO_033"


def test_accounts_payable_aging_and_payment_voucher():
    """Valida el análisis de vencimientos y la emisión de Comprobantes de Egreso."""
    db.init_db(seed=True)
    xml = make_sample_xml(uuid.uuid4().hex, f"99{uuid.uuid4().hex[:6]}")
    factura = vendor_bills.procesar_factura_proveedor(xml, auto_contabilizar=False)
    fid = factura["id"]

    # Análisis de edades inicial
    edades = accounts_payable.obtener_edades_cxp()
    assert Decimal(edades["total_deuda"]) >= Decimal("1165000.00")

    # Registrar comprobante de egreso parcial
    egreso = accounts_payable.registrar_comprobante_egreso({
        "factura_compra_id": fid,
        "monto": "600000.00",
        "medio_pago": "TRANSFERENCIA",
        "proveedor_nit": factura["proveedor_nit"],
        "proveedor_nombre": factura["proveedor_nombre"],
        "observaciones": "Abono inicial 50%",
    }, auto_contabilizar=True)
    assert egreso is not None

    # Verificar saldo restante en cuentas por pagar
    cxp = [c for c in accounts_payable.listar_cuentas_por_pagar() if c["factura_compra_id"] == fid][0]
    assert Decimal(cxp["saldo_pendiente"]) == Decimal("565000.00")
    assert cxp["estado"] == "PARCIAL"

    # Pagar el saldo restante
    accounts_payable.registrar_comprobante_egreso({
        "factura_compra_id": fid,
        "monto": "565000.00",
        "medio_pago": "EFECTIVO",
        "proveedor_nit": factura["proveedor_nit"],
        "proveedor_nombre": factura["proveedor_nombre"],
    }, auto_contabilizar=True)

    cxp_final = [c for c in accounts_payable.listar_cuentas_por_pagar() if c["factura_compra_id"] == fid][0]
    assert Decimal(cxp_final["saldo_pendiente"]) == Decimal("0.00")
    assert cxp_final["estado"] == "PAGADA"


def test_commercial_cycle_cascade():
    """Valida el ciclo en cascada: Cotización ➔ Pedido ➔ Remisión ➔ Factura."""
    db.init_db(seed=True)
    cliente = db.get_clientes()[0]

    # 1. Crear Cotización
    cot = commercial_cycle.crear_cotizacion({
        "cliente_nit": cliente["nit"],
        "lineas": [
            {
                "producto_codigo": "P001",
                "descripcion": "Producto General 19%",
                "cantidad": 2,
                "valor_unitario": "100000.00",
                "tarifa_iva": "IVA_19",
            }
        ],
        "observaciones": "Cotización de prueba",
    })
    assert cot["id"] is not None
    assert Decimal(cot["subtotal"]) == Decimal("200000.00")
    assert Decimal(cot["iva"]) == Decimal("38000.00")
    assert Decimal(cot["total"]) == Decimal("238000.00")
    assert cot["estado"] == "COTIZADO"

    # 2. Convertir a Pedido de Venta
    ped = commercial_cycle.convertir_cotizacion_a_pedido(cot["id"])
    assert ped["estado"] == "PENDIENTE"
    assert ped["cotizacion_id"] == cot["id"]

    # 3. Convertir a Remisión
    rem = commercial_cycle.convertir_pedido_a_remision(ped["id"])
    assert rem["estado"] == "ENTREGADO"
    assert rem["pedido_id"] == ped["id"]

    # 4. Facturar en 1 Clic
    fact = commercial_cycle.convertir_pedido_a_factura(ped["id"])
    assert fact["factura_id"] is not None
    assert fact["estado_dian"] in ("Aceptada", "EXITOSA", "ACEPTADO")
    assert Decimal(fact["total_factura"]) == Decimal("238000.00")


def test_pos_system_sessions_and_tickets():
    """Valida el funcionamiento de caja registradora POS y tirilla ESC/POS."""
    db.init_db(seed=True)

    caja = pos_system.crear_caja("Caja Mostrador Norte", ubicacion="Norte")
    assert caja["id"] is not None

    # Apertura de turno con base
    sesion = pos_system.abrir_caja(caja["id"], monto_inicial="150000.00")
    assert sesion["estado"] == "ABIERTA"
    assert Decimal(sesion["monto_inicial"]) == Decimal("150000.00")

    # Simular acumulación de ventas
    pos_system.registrar_venta_pos(sesion["id"], "50000.00", medio_pago="EFECTIVO")
    pos_system.registrar_venta_pos(sesion["id"], "30000.00", medio_pago="TARJETA")

    # Cierre con conteo físico exacto (base 150000 + efectivo 50000 = esperado 200000)
    cierre = pos_system.cerrar_caja(sesion["id"], total_real="200000.00", observaciones="Arqueo conforme")
    assert cierre["estado"] == "CERRADA"
    assert Decimal(cierre["diferencia"]) == Decimal("0.00")
    assert cierre["descuadre_tipo"] == "EXACTO"

    # Ticket de factura
    facturas = db.get_facturas()
    if facturas:
        ticket = pos_system.generar_ticket_pos(facturas[0]["id"], ancho_mm=80)
        assert ticket["texto_ticket"] is not None
        assert "DOCUMENTO EQUIVALENTE ELECTRONICO POS" in ticket["texto_ticket"]
        assert "TOTAL A PAGAR:" in ticket["texto_ticket"]


def test_price_lists_and_inventory_traceability():
    """Valida listas de precios múltiples y traslados de bodega con control de lotes."""
    db.init_db(seed=True)

    # 1. Listas de precios
    lp = price_lists.crear_lista_precios("Mayorista Especial", descripcion="Para distribuidores certificados")
    assert lp["id"] is not None

    asig = price_lists.asignar_precio_producto(lp["id"], "P001", "85000.00")
    assert asig["precio"] == "85000.00"

    precio_recup = price_lists.obtener_precio_producto(lp["id"], "P001")
    assert precio_recup == Decimal("85000.00")

    # 2. Trazabilidad: entrada con lote
    bodegas = db.get_bodegas()
    if len(bodegas) >= 2:
        b1 = bodegas[0]["codigo"]
        b2 = bodegas[1]["codigo"]

        inventory.registrar_entrada(
            producto_codigo="P001",
            bodega_codigo=b1,
            cantidad=Decimal("100"),
            costo_unitario=Decimal("50000.00"),
            lote="LOTE-EXP-2026",
            fecha_vencimiento="2027-12-31",
        )

        # Traslado entre bodegas
        tras = inventory.trasladar_bodega(
            producto_codigo="P001",
            bodega_origen=b1,
            bodega_destino=b2,
            cantidad=Decimal("30"),
            lote="LOTE-EXP-2026",
        )
        assert tras["bodega_origen"] == b1
        assert tras["bodega_destino"] == b2
        assert Decimal(tras["cantidad"]) == Decimal("30")


def test_official_dian_tax_forms():
    """Valida los agregadores oficiales para Formularios 300 (IVA) y 350 (Retención)."""
    db.init_db(seed=True)

    # Formulario 300 (IVA)
    f300 = tax_forms.generar_formulario_300(bimestre=1, anio=2026)
    assert f300["formulario"] == "300"
    assert "renglones" in f300
    assert "27_ingresos_gravados_19" in f300["renglones"]
    assert "59_impuesto_generado_19" in f300["renglones"]
    assert "67_total_impuesto_generado" in f300["renglones"]
    assert "83_saldo_a_pagar" in f300["renglones"]

    # Formulario 350 (Retención)
    f350 = tax_forms.generar_formulario_350(mes=2, anio=2026)
    assert f350["formulario"] == "350"
    assert "renglones" in f350
    assert "50_retencion_compras" in f350["renglones"]
    assert "87_total_retenciones" in f350["renglones"]


def test_2fa_totp_security():
    """Valida la generación de secretos, validación RFC 6238 y activación de 2FA."""
    db.init_db(seed=True)
    auth.seed_usuarios()

    secret = auth.generar_totp_secret()
    assert len(secret) >= 16

    uri = auth.generar_totp_uri("admin@saluki.com", secret)
    assert "otpauth://totp/" in uri
    assert secret in uri

    # Código TOTP para el intervalo actual
    ahora_intervalo = int(time.time()) // 30
    code = auth._calcular_totp(secret, ahora_intervalo)
    assert len(code) == 6
    assert auth.verificar_totp(secret, code)

    # Habilitar 2FA para el usuario administrador
    admin_user = auth.verificar_credenciales("admin@saluki.com", "admin123")
    assert admin_user is not None

    ok = auth.habilitar_2fa(admin_user["id"], secret, code)
    assert ok is True

    # Verificar que el usuario ahora tiene 2FA activado
    estado = auth.obtener_estado_2fa(admin_user["id"])
    assert estado["enabled"] is True

    # Desactivar 2FA
    auth.deshabilitar_2fa(admin_user["id"])
    assert auth.obtener_estado_2fa(admin_user["id"])["enabled"] is False
