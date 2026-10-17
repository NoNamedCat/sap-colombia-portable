"""Importación Masiva via Flat File (CSV/Excel) para SAP Colombia."""

import csv
import io
import uuid
import os
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(BASE_DIR)
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from sap_colombia import database as db
from sap_colombia import inventory
from sap_colombia import inventory_accounting
from sap_colombia.tax_engine import TaxEngine, LineaFactura


class ImportErrorMassive(Exception):
    pass


def _to_decimal(valor) -> Decimal:
    if valor is None:
        return Decimal("0.00")
    if isinstance(valor, Decimal):
        return valor.quantize(Decimal("0.01"))
    try:
        return Decimal(str(valor).strip()).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        raise ImportErrorMassive(f"Valor numérico inválido: {valor}")


def _parse_csv(content: bytes) -> list[dict]:
    text = content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    return [dict(row) for row in reader]


def _parse_xlsx(content: bytes) -> list[dict]:
    try:
        from openpyxl import load_workbook
    except ImportError:
        raise ImportErrorMassive("La librería openpyxl no está instalada.")
    wb = load_workbook(io.BytesIO(content), read_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return []
    headers = [str(h).strip() if h else "" for h in rows[0]]
    data = []
    for row in rows[1:]:
        if all(v is None for v in row):
            continue
        data.append({headers[i]: row[i] for i in range(len(headers))})
    return data


def _parse_file(content: bytes, formato: str) -> list[dict]:
    formato = (formato or "csv").lower().strip()
    if formato == "csv":
        return _parse_csv(content)
    if formato in ("xlsx", "excel"):
        return _parse_xlsx(content)
    raise ImportErrorMassive(f"Formato no soportado: {formato}")


def plantilla_facturas(formato: str = "csv") -> bytes:
    """Genera plantilla de importación para facturas."""
    columnas = [
        "cliente_nit", "producto_codigo", "cantidad", "valor_unitario",
        "tarifa_iva", "bodega_codigo"
    ]
    rows = [
        {"cliente_nit": "800197268", "producto_codigo": "PROD-01",
         "cantidad": "1", "valor_unitario": "100000", "tarifa_iva": "19",
         "bodega_codigo": "BODEGA-01"}
    ]
    return _exportar(columnas, rows, "facturas", formato)


def plantilla_saldos_iniciales(formato: str = "csv") -> bytes:
    """Genera plantilla de importación para saldos iniciales."""
    columnas = ["cuenta_codigo", "tercero_nit", "tercero_nombre", "concepto", "saldo"]
    rows = [
        {"cuenta_codigo": "130505", "tercero_nit": "800197268",
         "tercero_nombre": "Cliente Test", "concepto": "Causación inicial",
         "saldo": "500000"}
    ]
    return _exportar(columnas, rows, "saldos_iniciales", formato)


def plantilla_toma_inventario(formato: str = "csv") -> bytes:
    """Genera plantilla de importación para toma de inventario."""
    columnas = ["producto_codigo", "bodega_codigo", "cantidad", "costo_unitario"]
    rows = [
        {"producto_codigo": "PROD-01", "bodega_codigo": "BODEGA-01",
         "cantidad": "100", "costo_unitario": "5000"}
    ]
    return _exportar(columnas, rows, "toma_inventario", formato)


def _exportar(columnas: list[str], rows: list[dict], titulo: str, formato: str) -> bytes:
    from sap_colombia import excel_export
    return excel_export.exportar(formato, columnas, rows, titulo=titulo)


def importar_facturas(content: bytes, formato: str = "csv", empresa_id: int | None = None) -> dict:
    """Importa facturas masivamente desde CSV/Excel."""
    db.set_current_empresa_id(empresa_id)
    rows = _parse_file(content, formato)
    # Identificador único de la ejecución. Antes la referencia reiniciaba en
    # cada archivo, de modo que dos importaciones distintas colisionaban en el
    # numero_comprobante del asiento contable.
    run_id = uuid.uuid4().hex[:8].upper()
    conn = db.get_connection()
    procesadas = 0
    errores = 0
    errores_detalle = []

    for idx, row in enumerate(rows, start=1):
        try:
            cliente_nit = str(row.get("cliente_nit", "")).strip()
            producto_codigo = str(row.get("producto_codigo", "")).strip()
            cantidad = _to_decimal(row.get("cantidad"))
            valor_unitario = _to_decimal(row.get("valor_unitario"))
            tarifa_iva = str(row.get("tarifa_iva", "19")).strip()
            bodega = str(row.get("bodega_codigo", "BODEGA-01")).strip()

            if not cliente_nit or not producto_codigo:
                raise ImportErrorMassive(f"Fila {idx}: cliente_nit y producto_codigo requeridos")
            if cantidad <= 0:
                raise ImportErrorMassive(f"Fila {idx}: cantidad debe ser > 0")

            tarifa_iva_db = f"IVA_{tarifa_iva}" if tarifa_iva and tarifa_iva.isdigit() else tarifa_iva
            if not tarifa_iva_db or tarifa_iva_db not in ("IVA_19", "IVA_5", "IVA_0"):
                tarifa_iva_db = "IVA_19"

            linea = LineaFactura(
                codigo=producto_codigo,
                descripcion=producto_codigo,
                cantidad=cantidad,
                valor_unitario=valor_unitario,
                tarifa_iva=tarifa_iva_db,
            )
            engine = TaxEngine()
            resultado = engine.liquidar_factura([linea])
            subtotal = resultado.base_total
            total_iva = resultado.iva_total
            total = resultado.total_con_iva

            datos_factura = {
                "consecutivo": f"IMP{datetime.now().strftime('%Y%m%d%H%M%S%f')}",
                "prefijo": "IMP",
                "fecha": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                "cliente_nit": cliente_nit,
                "subtotal": str(subtotal),
                "iva_19": str(resultado.iva_total) if tarifa_iva_db == "IVA_19" else "0.00",
                "iva_5": str(resultado.iva_total) if tarifa_iva_db == "IVA_5" else "0.00",
                "iva_0": "0.00",
                "total_iva": str(total_iva),
                "total_factura": str(total),
                "saldo_pendiente": str(total),
                "estado_cartera": "PENDIENTE",
                "plazo_dias": 30,
                "fecha_vencimiento": (datetime.now(timezone.utc) + timedelta(days=30)).strftime("%Y-%m-%d"),
            }
            lineas = [{
                "producto_codigo": producto_codigo,
                "descripcion": producto_codigo,
                "cantidad": str(cantidad),
                "valor_unitario": str(valor_unitario),
                "subtotal": str(subtotal),
                "tarifa_iva": tarifa_iva_db,
                "valor_iva": str(total_iva),
            }]
            db.guardar_factura(datos_factura, lineas)
            procesadas += 1
        except Exception as e:
            errores += 1
            errores_detalle.append(f"Fila {idx}: {str(e)}")

    conn.commit()
    conn.close()
    return {"procesadas": procesadas, "errores": errores, "errores_detalle": errores_detalle}


def importar_saldos_iniciales(content: bytes, formato: str = "csv", empresa_id: int | None = None) -> dict:
    """Importa saldos iniciales a asientos contables."""
    db.set_current_empresa_id(empresa_id)
    rows = _parse_file(content, formato)
    # Identificador único de la ejecución. Antes la referencia reiniciaba en
    # cada archivo, de modo que dos importaciones distintas colisionaban en el
    # numero_comprobante del asiento contable.
    run_id = uuid.uuid4().hex[:8].upper()
    conn = db.get_connection()
    procesadas = 0
    errores = 0
    errores_detalle = []

    for idx, row in enumerate(rows, start=1):
        try:
            cuenta_codigo = str(row.get("cuenta_codigo", "")).strip()
            tercero_nit = str(row.get("tercero_nit", "")).strip()
            tercero_nombre = str(row.get("tercero_nombre", "Tercero")).strip()
            concepto = str(row.get("concepto", "Saldo inicial")).strip()
            saldo = _to_decimal(row.get("saldo"))

            if not cuenta_codigo:
                raise ImportErrorMassive(f"Fila {idx}: cuenta_codigo requerido")
            if saldo == 0:
                continue

            movimientos = [{
                "cuenta_codigo": cuenta_codigo,
                "tercero_nit": tercero_nit,
                "tercero_nombre": tercero_nombre,
                "concepto": concepto,
                "debito": str(saldo) if saldo > 0 else "0.00",
                "credito": "0.00" if saldo > 0 else str(abs(saldo)),
            }]
            # Validar partida doble (solo un movimiento, se asume contrapartida implícita)
            # En saldos iniciales, se genera asiento de apertura con contrapartida 135500
            movimientos.append({
                "cuenta_codigo": "110505",
                "tercero_nit": "",
                "tercero_nombre": "Cuenta de ajuste",
                "concepto": "Contrapartida saldo inicial",
                "debito": "0.00" if saldo > 0 else str(saldo),
                "credito": str(saldo) if saldo > 0 else "0.00",
            })

            total_deb = sum(_to_decimal(m["debito"]) for m in movimientos)
            total_cred = sum(_to_decimal(m["credito"]) for m in movimientos)
            datos_asiento = {
                "numero_comprobante": f"SI-{idx:06d}-{datetime.now().strftime('%Y%m%d%H%M%S%f')}",
                "fecha": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                "tipo_documento": "SALDO_INICIAL",
                "documento_id": None,
                "glosa": f"Saldo inicial: {concepto}",
                "total_debito": str(total_deb),
                "total_credito": str(total_cred),
            }
            db.guardar_asiento(datos_asiento, movimientos)
            procesadas += 1
        except Exception as e:
            errores += 1
            errores_detalle.append(f"Fila {idx}: {str(e)}")

    conn.commit()
    conn.close()
    return {"procesadas": procesadas, "errores": errores, "errores_detalle": errores_detalle}


def importar_toma_inventario(content: bytes, formato: str = "csv", empresa_id: int | None = None) -> dict:
    """Importa toma de inventario (cargues/descargues)."""
    db.set_current_empresa_id(empresa_id)
    rows = _parse_file(content, formato)
    # Identificador único de la ejecución. Antes la referencia reiniciaba en
    # cada archivo, de modo que dos importaciones distintas colisionaban en el
    # numero_comprobante del asiento contable.
    run_id = uuid.uuid4().hex[:8].upper()
    conn = db.get_connection()
    procesadas = 0
    errores = 0
    errores_detalle = []
    try:
        for idx, row in enumerate(rows, start=1):
            try:
                producto_codigo = str(row.get("producto_codigo", "")).strip()
                bodega_codigo = str(row.get("bodega_codigo", "BODEGA-01")).strip()
                cantidad = _to_decimal(row.get("cantidad"))
                costo_unitario = _to_decimal(row.get("costo_unitario", "0"))

                if not producto_codigo:
                    raise ImportErrorMassive(f"Fila {idx}: producto_codigo requerido")
                if cantidad < 0:
                    raise ImportErrorMassive(f"Fila {idx}: cantidad no puede ser negativa")
                if cantidad == 0:
                    continue

                # Una toma de inventario genera el ajuste contable
                # correspondiente (antes solo movía el kárdex).
                if cantidad > 0:
                    movimiento = inventory.registrar_entrada(
                        producto_codigo=producto_codigo,
                        bodega_codigo=bodega_codigo,
                        cantidad=cantidad,
                        costo_unitario=costo_unitario,
                        referencia_documento=f"IMP-INV-{run_id}-{idx:06d}",
                        conn=conn,
                        contabilizar=False,
                    )
                    diferencia = cantidad
                else:
                    movimiento = inventory.registrar_salida(
                        producto_codigo=producto_codigo,
                        bodega_codigo=bodega_codigo,
                        cantidad=abs(cantidad),
                        referencia_documento=f"IMP-INV-{run_id}-{idx:06d}",
                        conn=conn,
                    )
                    diferencia = -abs(cantidad)
                costo_unit = costo_unitario or _to_decimal(movimiento["costo_promedio"])
                if diferencia != 0:
                    inventory_accounting.contabilizar_ajuste_inventario(
                        producto_codigo=producto_codigo,
                        diferencia_cantidad=diferencia,
                        costo_unitario=costo_unit,
                        referencia_documento=f"IMP-INV-{run_id}-{idx:06d}",
                        conn=conn,
                    )
                procesadas += 1
            except Exception as e:
                errores += 1
                errores_detalle.append(f"Fila {idx}: {str(e)}")

        conn.commit()
    finally:
        conn.close()
    return {"procesadas": procesadas, "errores": errores, "errores_detalle": errores_detalle}