"""Ciclo Comercial en Cascada para ERP SAP Colombia.

Flujo de Ventas Completo:
Cotizaciones ➔ Pedidos de Venta ➔ Remisiones de Despacho ➔ Factura Electrónica en 1 Clic.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from decimal import Decimal

from sap_colombia import dbutil
from sap_colombia import database as db
from sap_colombia.tax_engine import TaxEngine, LineaFactura
from sap_colombia.ubl_builder import Emisor, Adquirente, UblInvoiceBuilder
from sap_colombia.dian_factory import get_dian_client


def _to_decimal(val) -> Decimal:
    try:
        return Decimal(str(val or "0.00").strip())
    except Exception:
        return Decimal("0.00")


def calcular_totales_lineas(lineas: list[dict]) -> tuple[Decimal, Decimal, Decimal]:
    """Calcula subtotal, IVA y total de una lista de líneas de venta."""
    subtotal = Decimal("0.00")
    total_iva = Decimal("0.00")

    for l in lineas:
        cant = _to_decimal(l.get("cantidad", 1))
        unit = _to_decimal(l.get("valor_unitario", 0))
        sub = cant * unit
        subtotal += sub

        tarifa_iva = str(l.get("tarifa_iva", "IVA_19")).upper()
        if "19" in tarifa_iva:
            total_iva += (sub * Decimal("0.19")).quantize(Decimal("0.01"))
        elif "5" in tarifa_iva:
            total_iva += (sub * Decimal("0.05")).quantize(Decimal("0.01"))

    total = subtotal + total_iva
    return subtotal, total_iva, total


def crear_cotizacion(datos: dict, empresa_id: int | None = None, conn=None) -> dict:
    """Crea una cotización comercial."""
    empresa_id = empresa_id or db.get_current_empresa_id() or 1
    usuario_id = datos.get("usuario_id")
    descuento_porcentaje = _to_decimal(datos.get("descuento_porcentaje", 0))
    consecutivo = str(datos.get("consecutivo") or f"COT-{int(datetime.now(timezone.utc).timestamp())}")
    cliente_nit = str(datos.get("cliente_nit", "")).strip()
    fecha = datos.get("fecha") or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    fecha_vencimiento = datos.get("fecha_vencimiento") or (
        datetime.now(timezone.utc) + timedelta(days=15)
    ).strftime("%Y-%m-%d")
    observaciones = str(datos.get("observaciones") or "")
    lineas = datos.get("lineas") or []

    subtotal, iva, total = calcular_totales_lineas(lineas)
    if descuento_porcentaje > Decimal("0.00"):
        descuento_monto = (subtotal * (descuento_porcentaje / Decimal("100.00"))).quantize(Decimal("0.01"))
        total = total - descuento_monto

    estado = "REQUIERE_APROBACION" if descuento_porcentaje > Decimal("15.00") else "COTIZADO"

    propia_conexion = conn is None
    conn = conn or db.get_connection()
    try:
        ahora = datetime.now(timezone.utc).isoformat()
        cursor = dbutil.query(
            conn,
            """INSERT INTO cotizaciones (
                empresa_id, usuario_id, consecutivo, cliente_nit, fecha, fecha_vencimiento,
                subtotal, iva, total, descuento_porcentaje, estado, lineas, observaciones, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING id""",
            (
                empresa_id,
                usuario_id,
                consecutivo,
                cliente_nit,
                fecha,
                fecha_vencimiento,
                str(subtotal),
                str(iva),
                str(total),
                str(descuento_porcentaje),
                estado,
                json.dumps(lineas),
                observaciones,
                ahora,
            ),
        )
        row = cursor.fetchone()
        cotizacion_id = row["id"] if row else 1

        if propia_conexion:
            conn.commit()

        return {
            "id": cotizacion_id,
            "empresa_id": empresa_id,
            "usuario_id": usuario_id,
            "consecutivo": consecutivo,
            "cliente_nit": cliente_nit,
            "fecha": fecha,
            "fecha_vencimiento": fecha_vencimiento,
            "subtotal": str(subtotal),
            "iva": str(iva),
            "total": str(total),
            "descuento_porcentaje": str(descuento_porcentaje),
            "estado": estado,
            "aprobado_por": None,
            "lineas": lineas,
            "observaciones": observaciones,
        }
    finally:
        if propia_conexion:
            conn.close()


def aprobar_cotizacion(cotizacion_id: int, usuario_aprobador_id: int, empresa_id: int | None = None) -> dict:
    """Aprueba una cotización que requiere visto bueno previo por descuento."""
    empresa_id = empresa_id or db.get_current_empresa_id() or 1
    conn = db.get_connection()
    try:
        cot = dbutil.query(
            conn,
            "SELECT * FROM cotizaciones WHERE id = ? AND empresa_id = ?",
            (cotizacion_id, empresa_id),
        ).fetchone()
        if not cot:
            raise ValueError(f"Cotización #{cotizacion_id} no encontrada.")

        dbutil.query(
            conn,
            "UPDATE cotizaciones SET estado = 'COTIZADO', aprobado_por = ? WHERE id = ? AND empresa_id = ?",
            (usuario_aprobador_id, cotizacion_id, empresa_id),
        )
        conn.commit()
        return {
            "id": cotizacion_id,
            "estado": "COTIZADO",
            "aprobado_por": usuario_aprobador_id,
            "mensaje": f"Cotización #{cotizacion_id} aprobada con éxito.",
        }
    finally:
        conn.close()


def convertir_cotizacion_a_pedido(cotizacion_id: int, empresa_id: int | None = None) -> dict:
    """Convierte una cotización aprobada en un pedido de venta."""
    empresa_id = empresa_id or db.get_current_empresa_id() or 1
    conn = db.get_connection()
    try:
        cot = dbutil.query(
            conn,
            "SELECT * FROM cotizaciones WHERE id = ? AND empresa_id = ?",
            (cotizacion_id, empresa_id),
        ).fetchone()
        if not cot:
            raise ValueError(f"Cotización #{cotizacion_id} no encontrada.")

        if cot.get("estado") == "REQUIERE_APROBACION":
            raise ValueError(
                f"La cotización {cot['consecutivo']} requiere aprobación previa de gerencia por descuento superior al 15%."
            )

        lineas = json.loads(cot["lineas"]) if isinstance(cot["lineas"], str) else (cot["lineas"] or [])
        consecutivo_pedido = f"PED-{cot['consecutivo'].replace('COT-', '')}"
        ahora = datetime.now(timezone.utc).isoformat()
        fecha = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        cursor = dbutil.query(
            conn,
            """INSERT INTO pedidos_venta (
                empresa_id, usuario_id, consecutivo, cotizacion_id, cliente_nit, fecha,
                subtotal, iva, total, estado, aprobado_por, lineas, observaciones, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDIENTE', ?, ?, ?, ?)
            RETURNING id""",
            (
                empresa_id,
                cot.get("usuario_id"),
                consecutivo_pedido,
                cotizacion_id,
                cot["cliente_nit"],
                fecha,
                cot["subtotal"],
                cot["iva"],
                cot["total"],
                cot.get("aprobado_por"),
                json.dumps(lineas),
                cot["observaciones"] or "",
                ahora,
            ),
        )
        row = cursor.fetchone()
        pedido_id = row["id"] if row else 1

        dbutil.query(conn, "UPDATE cotizaciones SET estado = 'APROBADO' WHERE id = ?", (cotizacion_id,))
        conn.commit()

        return {
            "id": pedido_id,
            "empresa_id": empresa_id,
            "usuario_id": cot.get("usuario_id"),
            "consecutivo": consecutivo_pedido,
            "cotizacion_id": cotizacion_id,
            "cliente_nit": cot["cliente_nit"],
            "fecha": fecha,
            "subtotal": cot["subtotal"],
            "iva": cot["iva"],
            "total": cot["total"],
            "estado": "PENDIENTE",
            "lineas": lineas,
            "observaciones": cot["observaciones"],
        }
    finally:
        conn.close()


def convertir_pedido_a_remision(pedido_id: int, empresa_id: int | None = None) -> dict:
    """Genera una remisión de entrega / despacho a partir de un pedido."""
    empresa_id = empresa_id or db.get_current_empresa_id() or 1
    conn = db.get_connection()
    try:
        ped = dbutil.query(
            conn,
            "SELECT * FROM pedidos_venta WHERE id = ? AND empresa_id = ?",
            (pedido_id, empresa_id),
        ).fetchone()
        if not ped:
            raise ValueError(f"Pedido #{pedido_id} no encontrado.")

        lineas = json.loads(ped["lineas"]) if isinstance(ped["lineas"], str) else (ped["lineas"] or [])
        consecutivo_remision = f"REM-{ped['consecutivo'].replace('PED-', '')}"
        ahora = datetime.now(timezone.utc).isoformat()
        fecha = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        cursor = dbutil.query(
            conn,
            """INSERT INTO remisiones_venta (
                empresa_id, consecutivo, pedido_id, cliente_nit, fecha,
                lineas, observaciones, estado, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'ENTREGADO', ?)
            RETURNING id""",
            (
                empresa_id,
                consecutivo_remision,
                pedido_id,
                ped["cliente_nit"],
                fecha,
                json.dumps(lineas),
                ped["observaciones"] or "",
                ahora,
            ),
        )
        row = cursor.fetchone()
        remision_id = row["id"] if row else 1

        dbutil.query(conn, "UPDATE pedidos_venta SET estado = 'DESPACHADO' WHERE id = ?", (pedido_id,))
        conn.commit()

        return {
            "id": remision_id,
            "empresa_id": empresa_id,
            "consecutivo": consecutivo_remision,
            "pedido_id": pedido_id,
            "cliente_nit": ped["cliente_nit"],
            "fecha": fecha,
            "lineas": lineas,
            "estado": "ENTREGADO",
        }
    finally:
        conn.close()


def convertir_pedido_a_factura(pedido_id: int, empresa_id: int | None = None) -> dict:
    """Convierte un pedido en una Factura Electrónica DIAN en 1 Clic."""
    empresa_id = empresa_id or db.get_current_empresa_id() or 1
    conn = db.get_connection()
    try:
        ped = dbutil.query(
            conn,
            "SELECT * FROM pedidos_venta WHERE id = ? AND empresa_id = ?",
            (pedido_id, empresa_id),
        ).fetchone()
        if not ped:
            raise ValueError(f"Pedido #{pedido_id} no encontrado.")

        cliente_nit = ped["cliente_nit"]
        cliente = db.get_cliente_by_nit(cliente_nit)
        if not cliente:
            raise ValueError(f"Cliente con NIT {cliente_nit} no encontrado.")

        empresa = db.get_empresa(empresa_id)
        if not empresa:
            raise ValueError(f"Empresa #{empresa_id} no encontrada.")

        lineas_raw = json.loads(ped["lineas"]) if isinstance(ped["lineas"], str) else (ped["lineas"] or [])
        lineas_engine = []
        for l in lineas_raw:
            lineas_engine.append(
                LineaFactura(
                    codigo=l.get("producto_codigo", "GEN"),
                    descripcion=l.get("descripcion", "Producto"),
                    cantidad=Decimal(str(l.get("cantidad", 1))),
                    valor_unitario=Decimal(str(l.get("valor_unitario", 0))),
                    tarifa_iva=l.get("tarifa_iva", "IVA_19"),
                    clasificacion=l.get("tipo_bien_servicio", "BIENES"),
                )
            )

        # Usar TaxEngine para liquidación estricta DIAN
        tax_res = TaxEngine().liquidar_factura(lineas_engine)
        consecutivo = str(db.get_siguiente_consecutivo(empresa_id=empresa_id))
        prefijo = empresa.get("prefijo_resolucion") or "SETP"

        emisor = Emisor(
            nit=empresa["nit"],
            nombre=empresa["razon_social"],
            direccion=empresa.get("direccion") or "",
            ciudad=empresa.get("municipio") or "Bogotá D.C.",
            departamento=empresa.get("departamento") or "Cundinamarca",
        )
        adquirente = Adquirente(
            nit=cliente["nit"],
            nombre=cliente["razon_social"],
            tipo_documento=cliente.get("tipo_documento") or "NIT",
            direccion=cliente.get("direccion") or "",
            ciudad=cliente.get("municipio") or "Bogotá D.C.",
            email=cliente.get("email") or "",
            telefono=cliente.get("telefono") or "",
        )

        ahora_dt = datetime.now(timezone.utc)
        fecha_emision = ahora_dt.strftime("%Y-%m-%d")
        hora_emision = ahora_dt.strftime("%H:%M:%S-05:00")

        builder = UblInvoiceBuilder(emisor, adquirente)
        num_fac = f"{prefijo}{consecutivo}"
        factura_ubl = builder.build(
            num_fac=num_fac,
            fecha=fecha_emision,
            hora=hora_emision,
            lineas=lineas_engine,
            clave_tecnica=empresa.get("clave_tecnica") or "3fa9c0b1d2e34f5a6b7c8d9e0f1a2b3c",
            tipo_ambiente=str(empresa.get("tipo_ambiente") or "1"),
        )

        iva_19 = sum((r.valor_iva for r in tax_res.lineas if r.linea.tarifa_iva == "IVA_19"), Decimal("0"))
        iva_5 = sum((r.valor_iva for r in tax_res.lineas if r.linea.tarifa_iva == "IVA_5"), Decimal("0"))
        iva_0 = sum((r.valor_iva for r in tax_res.lineas if r.linea.tarifa_iva == "IVA_0"), Decimal("0"))

        factura_data = {
            "consecutivo": consecutivo,
            "prefijo": prefijo,
            "fecha": fecha_emision,
            "hora": hora_emision,
            "cliente_nit": cliente["nit"],
            "subtotal": str(tax_res.base_total),
            "iva_19": str(iva_19),
            "iva_5": str(iva_5),
            "iva_0": str(iva_0),
            "total_iva": str(tax_res.iva_total),
            "retefuente": str(tax_res.retencion_fuente_total),
            "reteica": str(tax_res.reteica_total),
            "reteiva": str(tax_res.reteiva_total),
            "total_factura": str(tax_res.valor_transaccion),
            "cufe": factura_ubl.cufe,
            "qr": factura_ubl.qr,
            "xml_ubl": factura_ubl.xml,
            "empresa_id": empresa_id,
        }

        # Transmitir a DIAN
        dian_client = get_dian_client(str(empresa.get("nit", "")), empresa)
        trans_res = dian_client.transmitir_xml(factura_ubl.xml)
        factura_data["estado_dian"] = trans_res.estado
        factura_data["track_id"] = trans_res.track_id
        factura_data["mensaje_dian"] = trans_res.status_description
        factura_data["application_response_xml"] = trans_res.application_response_xml

        lineas_db = [
            {
                "producto_codigo": l.get("producto_codigo", "GEN"),
                "descripcion": l.get("descripcion", "Producto"),
                "cantidad": l.get("cantidad", 1),
                "valor_unitario": l.get("valor_unitario", 0),
                "subtotal": str(Decimal(str(l.get("cantidad", 1))) * Decimal(str(l.get("valor_unitario", 0)))),
                "tarifa_iva": l.get("tarifa_iva", "IVA_19"),
                "valor_iva": str(Decimal(str(l.get("cantidad", 1))) * Decimal(str(l.get("valor_unitario", 0))) * (Decimal("0.19") if l.get("tarifa_iva") == "IVA_19" else Decimal("0"))),
                "tipo_bien_servicio": l.get("tipo_bien_servicio", "BIENES"),
            }
            for l in lineas_raw
        ]

        # Guardar en base de datos transaccionalmente
        with db.transactional_scope() as tx_conn:
            factura_id = db.guardar_factura(factura_data, lineas=lineas_db, conn=tx_conn)
            factura_data["id"] = factura_id

            try:
                accounting_engine.contabilizar_factura_venta(factura_data, conn=tx_conn)
            except Exception:
                pass

            # Marcar pedido como facturado
            dbutil.query(tx_conn, "UPDATE pedidos_venta SET estado = 'FACTURADO' WHERE id = ?", (pedido_id,))

        return {
            "pedido_id": pedido_id,
            "factura_id": factura_id,
            "consecutivo": consecutivo,
            "prefijo": prefijo,
            "total_factura": str(tax_res.total_con_iva),
            "valor_transaccion": str(tax_res.valor_transaccion),
            "cufe": factura_ubl.cufe,
            "estado_dian": trans_res.estado,
        }
    finally:
        conn.close()


def listar_cotizaciones(empresa_id: int | None = None, usuario_id: int | None = None) -> list[dict]:
    empresa_id = empresa_id or db.get_current_empresa_id() or 1
    conn = db.get_connection()
    try:
        if usuario_id is not None:
            rows = dbutil.query(
                conn,
                "SELECT * FROM cotizaciones WHERE empresa_id = ? AND (usuario_id = ? OR usuario_id IS NULL) ORDER BY id DESC",
                (empresa_id, usuario_id),
            ).fetchall()
        else:
            rows = dbutil.query(
                conn,
                "SELECT * FROM cotizaciones WHERE empresa_id = ? ORDER BY id DESC",
                (empresa_id,),
            ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            if isinstance(d.get("lineas"), str):
                try:
                    d["lineas"] = json.loads(d["lineas"])
                except Exception:
                    pass
            result.append(d)
        return result
    finally:
        conn.close()


def listar_pedidos(empresa_id: int | None = None, usuario_id: int | None = None) -> list[dict]:
    empresa_id = empresa_id or db.get_current_empresa_id() or 1
    conn = db.get_connection()
    try:
        if usuario_id is not None:
            rows = dbutil.query(
                conn,
                "SELECT * FROM pedidos_venta WHERE empresa_id = ? AND (usuario_id = ? OR usuario_id IS NULL) ORDER BY id DESC",
                (empresa_id, usuario_id),
            ).fetchall()
        else:
            rows = dbutil.query(
                conn,
                "SELECT * FROM pedidos_venta WHERE empresa_id = ? ORDER BY id DESC",
                (empresa_id,),
            ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            if isinstance(d.get("lineas"), str):
                try:
                    d["lineas"] = json.loads(d["lineas"])
                except Exception:
                    pass
            result.append(d)
        return result
    finally:
        conn.close()


def listar_remisiones(empresa_id: int | None = None) -> list[dict]:
    empresa_id = empresa_id or db.get_current_empresa_id() or 1
    conn = db.get_connection()
    try:
        rows = dbutil.query(
            conn,
            "SELECT * FROM remisiones_venta WHERE empresa_id = ? ORDER BY id DESC",
            (empresa_id,),
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            if isinstance(d.get("lineas"), str):
                try:
                    d["lineas"] = json.loads(d["lineas"])
                except Exception:
                    pass
            result.append(d)
        return result
    finally:
        conn.close()
