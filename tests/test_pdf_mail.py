"""Pruebas TDD para generador de PDFs SAP Colombia (ReportLab)."""
import io
import pytest

from sap_colombia import pdf_generator


# --- Fixtures de datos de muestra ---

EMPRESA = {
    "nit": "90012345678",
    "razon_social": "Saluki Solutions S.A.S.",
    "direccion": "Cra 15 # 45-30, PBX 12",
    "municipio": "Bogotá D.C.",
    "departamento": "Cundinamarca",
    "prefijo_resolucion": "SETP",
    "resolucion_dian": "18760000001",
    "fecha_resolucion": "2026-01-15",
    "clave_tecnica": "3fa9c0b1d2e34f5a6b7c8d9e0f1a2b3c",
    "tipo_ambiente": "2",
}

CLIENTE = {
    "nit": "800197268",
    "dv": "4",
    "tipo_documento": "NIT",
    "razon_social": "Distribuidora del Café S.A.S.",
    "direccion": "Calle 26 # 68C-61",
    "municipio": "Bogotá D.C.",
    "email": "facturacion@districafe.com.co",
}


def _factura_sample():
    return {
        "id": 1,
        "consecutivo": "SETP990000001",
        "prefijo": "SETP",
        "fecha": "2026-01-15",
        "hora": "12:00:00",
        "cliente_nit": "800197268",
        "subtotal": "1000000.00",
        "iva_19": "190000.00",
        "iva_5": "0.00",
        "iva_0": "0.00",
        "total_iva": "190000.00",
        "retefuente": "25000.00",
        "reteica": "6900.00",
        "reteiva": "28500.00",
        "total_factura": "1129600.00",
        "cufe": "CUFE-DEMO-0001",
        "qr": "QR-DEMO-0001",
        "estado_dian": "EXITOSA",
        "track_id": "TRK-001",
        "lineas": [
            {
                "producto_codigo": "P001",
                "descripcion": "Laptop Dell",
                "cantidad": "1",
                "valor_unitario": "1000000.00",
                "subtotal": "1000000.00",
                "tarifa_iva": "IVA_19",
                "valor_iva": "190000.00",
            }
        ],
    }


def _nota_credito_sample():
    return {
        "id": 1,
        "consecutivo": "SETPNC990000001",
        "fecha": "2026-01-16",
        "hora": "13:00:00",
        "factura_id": 1,
        "factura_consecutivo": "SETP990000001",
        "cufe_factura": "CUFE-PADRE-0001",
        "cliente_nit": "800197268",
        "motivo_dian": "01",
        "descripcion_motivo": "Devolución parcial",
        "subtotal": "500000.00",
        "total_iva": "95000.00",
        "retefuente": "0.00",
        "reteica": "0.00",
        "reteiva": "0.00",
        "total_nota": "595000.00",
        "cude": "CUDE-0001",
        "qr": "QR-NC-0001",
        "lineas": [
            {
                "producto_codigo": "P001",
                "descripcion": "Laptop Dell",
                "cantidad": "0.5",
                "valor_unitario": "1000000.00",
                "subtotal": "500000.00",
                "tarifa_iva": "IVA_19",
                "valor_iva": "95000.00",
            }
        ],
    }


def _nota_debito_sample():
    return {
        "id": 1,
        "consecutivo": "SETEND990000001",
        "fecha": "2026-01-17",
        "hora": "14:00:00",
        "factura_id": 1,
        "factura_consecutivo": "SETP990000001",
        "cufe_factura": "CUFE-PADRE-0001",
        "cliente_nit": "800197268",
        "concepto_dian": "4",
        "descripcion_motivo": "Flete adicional",
        "subtotal": "100000.00",
        "total_iva": "19000.00",
        "total_nota": "119000.00",
        "cude": "CUDE-ND-0001",
        "qr": "QR-ND-0001",
        "lineas": [],
    }


def _documento_soporte_sample():
    return {
        "id": 1,
        "consecutivo": "SETDSP990000001",
        "prefijo": "SETDSP",
        "fecha": "2026-01-18",
        "hora": "15:00:00",
        "proveedor_nit": "800234567",
        "proveedor_nombre": "Prestadora de Servicios X",
        "subtotal": "200000.00",
        "retefuente": "25000.00",
        "reteica": "0.00",
        "total_documento": "175000.00",
        "cuds": "CUDS-0001",
        "qr": "QR-DS-0001",
        "lineas": [
            {"descripcion": "Servicios administrativos", "cantidad": "1", "valor_unitario": "200000.00", "subtotal": "200000.00"}
        ],
    }


def _recibo_caja_sample():
    return {
        "id": 1,
        "numero": "RC-0001",
        "fecha": "2026-01-19",
        "cliente_nit": "800197268",
        "factura_id": 1,
        "factura_consecutivo": "SETP990000001",
        "monto": "500000.00",
        "medio_pago": "EFECTIVO",
        "referencia": "REF-001",
        "cliente_nombre": "Distribuidora del Café S.A.S.",
    }


def _nomina_sample():
    return {
        "id": 1,
        "consecutivo": "NOM0001",
        "prefijo": "NOM",
        "periodo_inicio": "2026-01-01",
        "periodo_fin": "2026-01-31",
        "empleado_id": 1,
        "total_devengado": "3000000.00",
        "total_deducciones": "200000.00",
        "neto_pagar": "2800000.00",
        "cune": "CUNE-0001",
        "estado_dian": "EXITOSA",
        "fecha_emision": "2026-01-31",
        "hora_emision": "23:59:59",
        "empleado": {
            "tipo_documento": "CC",
            "documento": "123456789",
            "nombres": "Juan",
            "apellidos": "Pérez",
            "salario_base": "2800000.00",
            "auxilio_transporte": "167600.00",
        },
    }


# --- Pruebas: Cabecera PDF ---

def test_pdf_factura_genera_bytes():
    pdf_bytes = pdf_generator.generar_pdf_documento(
        tipo="FACTURA",
        documento=_factura_sample(),
        empresa=EMPRESA,
        cliente=CLIENTE,
    )
    assert isinstance(pdf_bytes, bytes)
    assert len(pdf_bytes) > 0


def test_pdf_factura_cabecera_pdf():
    pdf_bytes = pdf_generator.generar_pdf_documento(
        tipo="FACTURA",
        documento=_factura_sample(),
        empresa=EMPRESA,
        cliente=CLIENTE,
    )
    assert pdf_bytes.startswith(b"%PDF-")


def test_pdf_factura_incluye_cufe():
    pdf_bytes = pdf_generator.generar_pdf_documento(
        tipo="FACTURA",
        documento=_factura_sample(),
        empresa=EMPRESA,
        cliente=CLIENTE,
    )
    # CUFE debe aparecer en el contenido del PDF
    assert b"CUFE-DEMO-0001" in pdf_bytes


def test_pdf_factura_incluye_qr_binario():
    """El QR debe estar incrustado como imagen (bytes PNG/JPG) en el PDF."""
    pdf_bytes = pdf_generator.generar_pdf_documento(
        tipo="FACTURA",
        documento=_factura_sample(),
        empresa=EMPRESA,
        cliente=CLIENTE,
    )
    # PDF con imagen embebida tiene XObject o Image stream
    assert b"XObject" in pdf_bytes or b"/Image" in pdf_bytes


def test_pdf_factura_incluye_montos():
    pdf_bytes = pdf_generator.generar_pdf_documento(
        tipo="FACTURA",
        documento=_factura_sample(),
        empresa=EMPRESA,
        cliente=CLIENTE,
    )
    assert b"1129600.00" in pdf_bytes


def test_pdf_factura_incluye_ley_1231():
    pdf_bytes = pdf_generator.generar_pdf_documento(
        tipo="FACTURA",
        documento=_factura_sample(),
        empresa=EMPRESA,
        cliente=CLIENTE,
    )
    assert b"Ley 1231" in pdf_bytes


def test_pdf_factura_incluye_resolucion_dian():
    pdf_bytes = pdf_generator.generar_pdf_documento(
        tipo="FACTURA",
        documento=_factura_sample(),
        empresa=EMPRESA,
        cliente=CLIENTE,
    )
    assert b"18760000001" in pdf_bytes


# --- Pruebas: Nota Crédito ---

def test_pdf_nota_credito_genera_bytes():
    pdf_bytes = pdf_generator.generar_pdf_documento(
        tipo="NOTA_CREDITO",
        documento=_nota_credito_sample(),
        empresa=EMPRESA,
        cliente=CLIENTE,
    )
    assert pdf_bytes.startswith(b"%PDF-")


def test_pdf_nota_credito_incluye_cude():
    pdf_bytes = pdf_generator.generar_pdf_documento(
        tipo="NOTA_CREDITO",
        documento=_nota_credito_sample(),
        empresa=EMPRESA,
        cliente=CLIENTE,
    )
    assert b"CUDE-0001" in pdf_bytes


def test_pdf_nota_credito_incluye_referencia_padre():
    pdf_bytes = pdf_generator.generar_pdf_documento(
        tipo="NOTA_CREDITO",
        documento=_nota_credito_sample(),
        empresa=EMPRESA,
        cliente=CLIENTE,
    )
    assert b"SETP990000001" in pdf_bytes


# --- Pruebas: Nota Débito ---

def test_pdf_nota_debito_genera_bytes():
    pdf_bytes = pdf_generator.generar_pdf_documento(
        tipo="NOTA_DEBITO",
        documento=_nota_debito_sample(),
        empresa=EMPRESA,
        cliente=CLIENTE,
    )
    assert pdf_bytes.startswith(b"%PDF-")


def test_pdf_nota_debito_incluye_cude():
    pdf_bytes = pdf_generator.generar_pdf_documento(
        tipo="NOTA_DEBITO",
        documento=_nota_debito_sample(),
        empresa=EMPRESA,
        cliente=CLIENTE,
    )
    assert b"CUDE-ND-0001" in pdf_bytes


# --- Pruebas: Documento de Soporte ---

def test_pdf_documento_soporte_genera_bytes():
    pdf_bytes = pdf_generator.generar_pdf_documento(
        tipo="DOCUMENTO_SOPOrTE".upper(),
        documento=_documento_soporte_sample(),
        empresa=EMPRESA,
        cliente=None,
    )
    assert pdf_bytes.startswith(b"%PDF-")


def test_pdf_documento_soporte_incluye_cuds():
    pdf_bytes = pdf_generator.generar_pdf_documento(
        tipo="DOCUMENTO_SOPOrTE".upper(),
        documento=_documento_soporte_sample(),
        empresa=EMPRESA,
        cliente=None,
    )
    assert b"CUDS-0001" in pdf_bytes


# --- Pruebas: Recibo de Caja ---

def test_pdf_recibo_caja_genera_bytes():
    pdf_bytes = pdf_generator.generar_pdf_documento(
        tipo="RECIBO_CAJA",
        documento=_recibo_caja_sample(),
        empresa=EMPRESA,
        cliente=CLIENTE,
    )
    assert pdf_bytes.startswith(b"%PDF-")


def test_pdf_recibo_caja_incluye_monto():
    pdf_bytes = pdf_generator.generar_pdf_documento(
        tipo="RECIBO_CAJA",
        documento=_recibo_caja_sample(),
        empresa=EMPRESA,
        cliente=CLIENTE,
    )
    assert b"500000.00" in pdf_bytes


# --- Pruebas: Nómina Desprendible ---

def test_pdf_nomina_desprendible_genera_bytes():
    pdf_bytes = pdf_generator.generar_pdf_documento(
        tipo="NOMINA_DESPRENDIBLE",
        documento=_nomina_sample(),
        empresa=EMPRESA,
        cliente=None,
    )
    assert pdf_bytes.startswith(b"%PDF-")


def test_pdf_nomina_desprendible_incluye_neto():
    pdf_bytes = pdf_generator.generar_pdf_documento(
        tipo="NOMINA_DESPRENDIBLE",
        documento=_nomina_sample(),
        empresa=EMPRESA,
        cliente=None,
    )
    assert b"2800000.00" in pdf_bytes


def test_pdf_nomina_incluye_cune():
    pdf_bytes = pdf_generator.generar_pdf_documento(
        tipo="NOMINA_DESPRENDIBLE",
        documento=_nomina_sample(),
        empresa=EMPRESA,
        cliente=None,
    )
    assert b"CUNE-0001" in pdf_bytes


# --- Pruebas: API pública ---

def test_tiempos_documento_soporte():
    assert "DOCUMENTO_SOPOrTE".upper() in pdf_generator.TIPOS_DOCUMENTO


def test_factura_tipo_válido():
    assert "FACTURA" in pdf_generator.TIPOS_DOCUMENTO


def test_generar_pdf_inmemory():
    buffer = io.BytesIO()
    pdf_generator.generar_pdf_documento(
        tipo="FACTURA",
        documento=_factura_sample(),
        empresa=EMPRESA,
        cliente=CLIENTE,
    )
    assert True


def test_pdf_bytes_no_vacío():
    pdf_bytes = pdf_generator.generar_pdf_documento(
        tipo="FACTURA",
        documento=_factura_sample(),
        empresa=EMPRESA,
        cliente=CLIENTE,
    )
    assert len(pdf_bytes) > 500  # PDF mínimo con contenido
