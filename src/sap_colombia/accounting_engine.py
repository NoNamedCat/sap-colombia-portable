"""Motor Contable y PUC (Plan Único de Cuentas NIIF) para SAP Colombia.

Garantiza el cumplimiento estricto del principio de partida doble:
Sumatoria de Débitos == Sumatoria de Créditos en cada transacción.
"""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from datetime import datetime, timezone
import sap_colombia.database as db


def to_decimal(valor) -> Decimal:
    """Convierte cualquier valor a Decimal con 2 cifras decimales."""
    if valor is None:
        return Decimal("0.00")
    if isinstance(valor, Decimal):
        return valor.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    try:
        return Decimal(str(valor).strip()).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        return Decimal("0.00")


class AsientoDescuadradoError(ValueError):
    """Excepción lanzada cuando un comprobante contable no cumple partida doble."""
    pass


def validar_partida_doble(movimientos: list[dict]) -> tuple[bool, Decimal, Decimal]:
    """Verifica que la suma de débitos sea exactamente igual a la suma de créditos."""
    total_debito = Decimal("0.00")
    total_credito = Decimal("0.00")

    for mov in movimientos:
        total_debito += to_decimal(mov.get("debito", "0.00"))
        total_credito += to_decimal(mov.get("credito", "0.00"))

    cuadrado = (total_debito == total_credito)
    return cuadrado, total_debito, total_credito


def contabilizar_factura_venta(factura: dict, conn=None) -> dict:
    """Genera automáticamente el asiento contable de una Factura de Venta emitida.
    
    Estructura de Partida Doble:
    - 130505 Clientes Nacionales: Débito por total neto a cobrar
    - 135515 Anticipo Retefuente: Débito por retefuente practicada
    - 135517 Anticipo ReteIVA: Débito por reteiva practicado
    - 135518 Anticipo ReteICA: Débito por reteica practicado
    - 240801 IVA 19% Generado: Crédito por IVA 19%
    - 240802 IVA 5% Generado: Crédito por IVA 5%
    - 413501 Ventas Operacionales: Crédito por Subtotal
    """
    consecutivo = factura.get("consecutivo", "0")
    prefijo = factura.get("prefijo", "SETP")
    comprobante_num = f"CC-FV-{prefijo}-{consecutivo}"
    fecha = factura.get("fecha") or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    cliente_nit = str(factura.get("cliente_nit", ""))
    
    subtotal = to_decimal(factura.get("subtotal", "0.00"))
    iva_19 = to_decimal(factura.get("iva_19", "0.00"))
    iva_5 = to_decimal(factura.get("iva_5", "0.00"))
    retefuente = to_decimal(factura.get("retefuente", "0.00"))
    reteica = to_decimal(factura.get("reteica", "0.00"))
    reteiva = to_decimal(factura.get("reteiva", "0.00"))
    total_factura = to_decimal(factura.get("total_factura", "0.00"))

    # Obtener nombre del cliente si es posible
    tercero_nombre = "Cliente"
    clientes = db.get_clientes()
    for c in clientes:
        if str(c.get("nit")) == cliente_nit:
            tercero_nombre = c.get("razon_social", "Cliente")
            break

    movimientos = []

    # 1. Débito a Clientes (Neto por cobrar)
    if total_factura > 0:
        movimientos.append({
            "cuenta_codigo": "130505",
            "tercero_nit": cliente_nit,
            "tercero_nombre": tercero_nombre,
            "concepto": f"Causación FV {prefijo}-{consecutivo}",
            "debito": str(total_factura),
            "credito": "0.00",
        })

    # 2. Débitos por Anticipos de Impuestos (Retenciones)
    if retefuente > 0:
        movimientos.append({
            "cuenta_codigo": "135515",
            "tercero_nit": cliente_nit,
            "tercero_nombre": tercero_nombre,
            "concepto": f"Retefuente practicada FV {prefijo}-{consecutivo}",
            "debito": str(retefuente),
            "credito": "0.00",
        })
    if reteiva > 0:
        movimientos.append({
            "cuenta_codigo": "135517",
            "tercero_nit": cliente_nit,
            "tercero_nombre": tercero_nombre,
            "concepto": f"ReteIVA 15% practicado FV {prefijo}-{consecutivo}",
            "debito": str(reteiva),
            "credito": "0.00",
        })
    if reteica > 0:
        movimientos.append({
            "cuenta_codigo": "135518",
            "tercero_nit": cliente_nit,
            "tercero_nombre": tercero_nombre,
            "concepto": f"ReteICA practicado FV {prefijo}-{consecutivo}",
            "debito": str(reteica),
            "credito": "0.00",
        })

    # 3. Créditos por Impuesto a las Ventas (IVA)
    if iva_19 > 0:
        movimientos.append({
            "cuenta_codigo": "240801",
            "tercero_nit": cliente_nit,
            "tercero_nombre": tercero_nombre,
            "concepto": f"IVA 19% generado FV {prefijo}-{consecutivo}",
            "debito": "0.00",
            "credito": str(iva_19),
        })
    if iva_5 > 0:
        movimientos.append({
            "cuenta_codigo": "240802",
            "tercero_nit": cliente_nit,
            "tercero_nombre": tercero_nombre,
            "concepto": f"IVA 5% generado FV {prefijo}-{consecutivo}",
            "debito": "0.00",
            "credito": str(iva_5),
        })

    # 4. Crédito por Ingresos Operacionales
    if subtotal > 0:
        movimientos.append({
            "cuenta_codigo": "413501",
            "tercero_nit": cliente_nit,
            "tercero_nombre": tercero_nombre,
            "concepto": f"Venta de mercancías/servicios FV {prefijo}-{consecutivo}",
            "debito": "0.00",
            "credito": str(subtotal),
        })

    cuadrado, total_deb, total_cred = validar_partida_doble(movimientos)
    if not cuadrado:
        raise AsientoDescuadradoError(
            f"El asiento contable de la factura {prefijo}-{consecutivo} está descuadrado: "
            f"Débito={total_deb} != Crédito={total_cred}"
        )

    datos_asiento = {
        "numero_comprobante": comprobante_num,
        "fecha": fecha,
        "tipo_documento": "FACTURA_VENTA",
        "documento_id": factura.get("id"),
        "glosa": f"Causación contable factura de venta {prefijo}-{consecutivo} a {tercero_nombre}",
        "total_debito": str(total_deb),
        "total_credito": str(total_cred),
    }

    asiento_id = db.guardar_asiento(datos_asiento, movimientos, conn=conn)
    return db.get_asiento_by_id(asiento_id)


def contabilizar_nota_credito(nota_credito: dict) -> dict:
    """Genera automáticamente el asiento contable de reversión de una Nota Crédito (tipo 91).
    
    Estructura de Partida Doble:
    - 417505 Devoluciones en Ventas: Débito por subtotal devuelto
    - 240801 IVA 19% Reversado: Débito por IVA reversado
    - 135515 Anticipo Retefuente: Crédito por retefuente anulada
    - 135517 Anticipo ReteIVA: Crédito por reteiva anulado
    - 135518 Anticipo ReteICA: Crédito por reteica anulado
    - 130505 Clientes Nacionales: Crédito por total de la nota
    """
    consecutivo = nota_credito.get("consecutivo", "0")
    prefijo = nota_credito.get("prefijo", "NC")
    comprobante_num = f"CC-NC-{prefijo}-{consecutivo}"
    fecha = nota_credito.get("fecha") or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    cliente_nit = str(nota_credito.get("cliente_nit", ""))

    subtotal = to_decimal(nota_credito.get("subtotal", "0.00"))
    total_iva = to_decimal(nota_credito.get("total_iva", "0.00"))
    retefuente = to_decimal(nota_credito.get("retefuente", "0.00"))
    reteica = to_decimal(nota_credito.get("reteica", "0.00"))
    reteiva = to_decimal(nota_credito.get("reteiva", "0.00"))
    total_nota = to_decimal(nota_credito.get("total_nota", "0.00"))

    tercero_nombre = "Cliente"
    clientes = db.get_clientes()
    for c in clientes:
        if str(c.get("nit")) == cliente_nit:
            tercero_nombre = c.get("razon_social", "Cliente")
            break

    movimientos = []

    # 1. Débito a Devoluciones en Ventas
    if subtotal > 0:
        movimientos.append({
            "cuenta_codigo": "417505",
            "tercero_nit": cliente_nit,
            "tercero_nombre": tercero_nombre,
            "concepto": f"Devolución/Rebaja en ventas NC {prefijo}-{consecutivo}",
            "debito": str(subtotal),
            "credito": "0.00",
        })

    # 2. Débito a IVA Reversado
    if total_iva > 0:
        movimientos.append({
            "cuenta_codigo": "240801",
            "tercero_nit": cliente_nit,
            "tercero_nombre": tercero_nombre,
            "concepto": f"IVA reversado NC {prefijo}-{consecutivo}",
            "debito": str(total_iva),
            "credito": "0.00",
        })

    # 3. Crédito a Anticipos de Retenciones reversados
    if retefuente > 0:
        movimientos.append({
            "cuenta_codigo": "135515",
            "tercero_nit": cliente_nit,
            "tercero_nombre": tercero_nombre,
            "concepto": f"Retefuente reversada NC {prefijo}-{consecutivo}",
            "debito": "0.00",
            "credito": str(retefuente),
        })
    if reteiva > 0:
        movimientos.append({
            "cuenta_codigo": "135517",
            "tercero_nit": cliente_nit,
            "tercero_nombre": tercero_nombre,
            "concepto": f"ReteIVA reversado NC {prefijo}-{consecutivo}",
            "debito": "0.00",
            "credito": str(reteiva),
        })
    if reteica > 0:
        movimientos.append({
            "cuenta_codigo": "135518",
            "tercero_nit": cliente_nit,
            "tercero_nombre": tercero_nombre,
            "concepto": f"ReteICA reversado NC {prefijo}-{consecutivo}",
            "debito": "0.00",
            "credito": str(reteica),
        })

    # 4. Crédito a Clientes (descarga de cartera)
    if total_nota > 0:
        movimientos.append({
            "cuenta_codigo": "130505",
            "tercero_nit": cliente_nit,
            "tercero_nombre": tercero_nombre,
            "concepto": f"Ajuste cartera por NC {prefijo}-{consecutivo}",
            "debito": "0.00",
            "credito": str(total_nota),
        })

    cuadrado, total_deb, total_cred = validar_partida_doble(movimientos)
    if not cuadrado:
        raise AsientoDescuadradoError(
            f"El asiento contable de la nota crédito {prefijo}-{consecutivo} está descuadrado: "
            f"Débito={total_deb} != Crédito={total_cred}"
        )

    datos_asiento = {
        "numero_comprobante": comprobante_num,
        "fecha": fecha,
        "tipo_documento": "NOTA_CREDITO",
        "documento_id": nota_credito.get("id"),
        "glosa": f"Reversión contable por nota crédito {prefijo}-{consecutivo} ref FV {nota_credito.get('factura_consecutivo', '')}",
        "total_debito": str(total_deb),
        "total_credito": str(total_cred),
    }

    asiento_id = db.guardar_asiento(datos_asiento, movimientos)
    return db.get_asiento_by_id(asiento_id)


def contabilizar_recibo_caja(recibo: dict, conn=None) -> dict:
    """Genera automáticamente el asiento contable de un Recibo de Caja (Recaudo de cartera).
    
    Estructura de Partida Doble:
    - 110505 Caja General (o 111005 Bancos): Débito por el monto recibido
    - 130505 Clientes Nacionales: Crédito por el monto amortizado
    """
    numero = recibo.get("numero", "0")
    comprobante_num = f"CC-RC-{numero}"
    fecha = recibo.get("fecha") or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    cliente_nit = str(recibo.get("cliente_nit", ""))
    monto = to_decimal(recibo.get("monto", "0.00"))
    medio_pago = recibo.get("medio_pago", "EFECTIVO").upper()

    cuenta_recaudo = "111005" if medio_pago in ("TRANSFERENCIA", "CONSIGNACION", "BANCO") else "110505"

    tercero_nombre = "Cliente"
    clientes = db.get_clientes()
    for c in clientes:
        if str(c.get("nit")) == cliente_nit:
            tercero_nombre = c.get("razon_social", "Cliente")
            break

    movimientos = [
        {
            "cuenta_codigo": cuenta_recaudo,
            "tercero_nit": cliente_nit,
            "tercero_nombre": tercero_nombre,
            "concepto": f"Ingreso a {cuenta_recaudo} por Recibo de Caja {numero}",
            "debito": str(monto),
            "credito": "0.00",
        },
        {
            "cuenta_codigo": "130505",
            "tercero_nit": cliente_nit,
            "tercero_nombre": tercero_nombre,
            "concepto": f"Abono cartera cliente por Recibo de Caja {numero}",
            "debito": "0.00",
            "credito": str(monto),
        },
    ]

    cuadrado, total_deb, total_cred = validar_partida_doble(movimientos)
    if not cuadrado:
        raise AsientoDescuadradoError(f"Asiento de recibo de caja descuadrado: {total_deb} != {total_cred}")

    datos_asiento = {
        "numero_comprobante": comprobante_num,
        "fecha": fecha,
        "tipo_documento": "RECIBO_CAJA",
        "documento_id": recibo.get("id"),
        "glosa": f"Recaudo cartera Recibo de Caja {numero} de {tercero_nombre}",
        "total_debito": str(total_deb),
        "total_credito": str(total_cred),
    }

    asiento_id = db.guardar_asiento(datos_asiento, movimientos, conn=conn)
    return db.get_asiento_by_id(asiento_id)


def contabilizar_documento_soporte(documento: dict) -> dict:
    """Genera automáticamente el asiento contable de un Documento Soporte en adquisiciones.
    
    Estructura de Partida Doble:
    - 513501 Gastos Operacionales (Servicios/Compras): Débito por Subtotal
    - 236540 Retención en la Fuente por Pagar: Crédito por Retefuente asumida
    - 236801 Retención de ICA por Pagar: Crédito por ReteICA asumido
    - 220505 Proveedores Nacionales (CxP): Crédito por el Total neto a pagar
    """
    consecutivo = documento.get("consecutivo", "0")
    prefijo = documento.get("prefijo", "DS")
    comprobante_num = f"CC-DS-{prefijo}-{consecutivo}"
    fecha = documento.get("fecha") or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    proveedor_nit = str(documento.get("proveedor_nit", ""))
    proveedor_nombre = documento.get("proveedor_nombre", "Proveedor")

    subtotal = to_decimal(documento.get("subtotal", "0.00"))
    retefuente = to_decimal(documento.get("retefuente", "0.00"))
    reteica = to_decimal(documento.get("reteica", "0.00"))
    total_documento = to_decimal(documento.get("total_documento", "0.00"))

    movimientos = [
        {
            "cuenta_codigo": "513501",
            "tercero_nit": proveedor_nit,
            "tercero_nombre": proveedor_nombre,
            "concepto": f"Causación gasto/adquisición DS {prefijo}-{consecutivo}",
            "debito": str(subtotal),
            "credito": "0.00",
        }
    ]

    if retefuente > 0:
        movimientos.append({
            "cuenta_codigo": "236540",
            "tercero_nit": proveedor_nit,
            "tercero_nombre": proveedor_nombre,
            "concepto": f"Retefuente retenida en compras DS {prefijo}-{consecutivo}",
            "debito": "0.00",
            "credito": str(retefuente),
        })

    if reteica > 0:
        movimientos.append({
            "cuenta_codigo": "236801",
            "tercero_nit": proveedor_nit,
            "tercero_nombre": proveedor_nombre,
            "concepto": f"ReteICA retenido en compras DS {prefijo}-{consecutivo}",
            "debito": "0.00",
            "credito": str(reteica),
        })

    movimientos.append({
        "cuenta_codigo": "220505",
        "tercero_nit": proveedor_nit,
        "tercero_nombre": proveedor_nombre,
        "concepto": f"Cuentas por pagar proveedor DS {prefijo}-{consecutivo}",
        "debito": "0.00",
        "credito": str(total_documento),
    })

    cuadrado, total_deb, total_cred = validar_partida_doble(movimientos)
    if not cuadrado:
        raise AsientoDescuadradoError(f"Asiento de documento soporte descuadrado: {total_deb} != {total_cred}")

    datos_asiento = {
        "numero_comprobante": comprobante_num,
        "fecha": fecha,
        "tipo_documento": "DOCUMENTO_SOPORTE",
        "documento_id": documento.get("id"),
        "glosa": f"Causación compras a no obligado DS {prefijo}-{consecutivo} a {proveedor_nombre}",
        "total_debito": str(total_deb),
        "total_credito": str(total_cred),
    }

    asiento_id = db.guardar_asiento(datos_asiento, movimientos)
    return db.get_asiento_by_id(asiento_id)


def contabilizar_factura_compra(factura_compra: dict, conn=None) -> dict:
    """Genera automáticamente el asiento contable de una Factura de Compra recibida de proveedor.
    
    Estructura de Partida Doble:
    - 143501 Mercancías no Fabricadas (Inventario/Compras): Débito por Subtotal
    - 240808 IVA descontable: Débito por Total IVA
    - 236540 Retención en la Fuente por Pagar: Crédito por Retefuente practicada
    - 236801 Retención de ICA por Pagar: Crédito por ReteICA practicado
    - 236802 ReteIVA por Pagar: Crédito por ReteIVA practicado
    - 220505 Proveedores Nacionales (CxP): Crédito por Saldo Neto a Pagar
    """
    fc_id = factura_compra.get("id") or 0
    consecutivo = factura_compra.get("consecutivo", "0")
    prefijo = factura_compra.get("prefijo") or "FC"
    comprobante_num = f"CC-FC-{prefijo}-{consecutivo}-{fc_id}" if fc_id else f"CC-FC-{prefijo}-{consecutivo}"
    fecha = factura_compra.get("fecha") or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    proveedor_nit = str(factura_compra.get("proveedor_nit", ""))
    proveedor_nombre = factura_compra.get("proveedor_nombre") or "Proveedor"

    subtotal = to_decimal(factura_compra.get("subtotal", "0.00"))
    total_iva = to_decimal(factura_compra.get("total_iva", "0.00"))
    retefuente = to_decimal(factura_compra.get("retefuente", "0.00"))
    reteica = to_decimal(factura_compra.get("reteica", "0.00"))
    reteiva = to_decimal(factura_compra.get("reteiva", "0.00"))
    
    total_debito = subtotal + total_iva
    retenciones_total = retefuente + reteica + reteiva
    neto_cxp = total_debito - retenciones_total
    if neto_cxp < 0:
        neto_cxp = Decimal("0.00")

    movimientos = []
    if subtotal > 0:
        movimientos.append({
            "cuenta_codigo": "143501",
            "tercero_nit": proveedor_nit,
            "tercero_nombre": proveedor_nombre,
            "concepto": f"Compra mercancías/servicios FC {prefijo}-{consecutivo}",
            "debito": str(subtotal),
            "credito": "0.00",
        })

    if total_iva > 0:
        movimientos.append({
            "cuenta_codigo": "240808",
            "tercero_nit": proveedor_nit,
            "tercero_nombre": proveedor_nombre,
            "concepto": f"IVA descontable compra FC {prefijo}-{consecutivo}",
            "debito": str(total_iva),
            "credito": "0.00",
        })

    if retefuente > 0:
        movimientos.append({
            "cuenta_codigo": "236540",
            "tercero_nit": proveedor_nit,
            "tercero_nombre": proveedor_nombre,
            "concepto": f"Retefuente practicada en compras FC {prefijo}-{consecutivo}",
            "debito": "0.00",
            "credito": str(retefuente),
        })

    if reteica > 0:
        movimientos.append({
            "cuenta_codigo": "236801",
            "tercero_nit": proveedor_nit,
            "tercero_nombre": proveedor_nombre,
            "concepto": f"ReteICA practicado en compras FC {prefijo}-{consecutivo}",
            "debito": "0.00",
            "credito": str(reteica),
        })

    if reteiva > 0:
        movimientos.append({
            "cuenta_codigo": "236802",
            "tercero_nit": proveedor_nit,
            "tercero_nombre": proveedor_nombre,
            "concepto": f"ReteIVA practicado en compras FC {prefijo}-{consecutivo}",
            "debito": "0.00",
            "credito": str(reteiva),
        })

    if neto_cxp > 0:
        movimientos.append({
            "cuenta_codigo": "220505",
            "tercero_nit": proveedor_nit,
            "tercero_nombre": proveedor_nombre,
            "concepto": f"Cuentas por pagar proveedor FC {prefijo}-{consecutivo}",
            "debito": "0.00",
            "credito": str(neto_cxp),
        })

    cuadrado, total_deb, total_cred = validar_partida_doble(movimientos)
    if not cuadrado:
        raise AsientoDescuadradoError(f"Asiento de factura de compra descuadrado: {total_deb} != {total_cred}")

    datos_asiento = {
        "numero_comprobante": comprobante_num,
        "fecha": fecha,
        "tipo_documento": "FACTURA_COMPRA",
        "documento_id": factura_compra.get("id"),
        "glosa": f"Causación factura de compra {prefijo}-{consecutivo} de {proveedor_nombre}",
        "total_debito": str(total_deb),
        "total_credito": str(total_cred),
    }

    asiento_id = db.guardar_asiento(datos_asiento, movimientos, conn=conn)
    return db.get_asiento_by_id(asiento_id)


def contabilizar_comprobante_egreso(comprobante: dict, conn=None) -> dict:
    """Genera automáticamente el asiento contable de un Comprobante de Egreso (Pago a Proveedores).
    
    Estructura de Partida Doble:
    - 220505 Proveedores Nacionales (CxP): Débito por el monto cancelado
    - 111005 Bancos Nacionales (o 110505 Caja General): Crédito por el egreso
    """
    ce_id = comprobante.get("id") or 0
    consecutivo = comprobante.get("consecutivo", "0")
    comprobante_num = f"CC-CE-{consecutivo}-{ce_id}" if ce_id else f"CC-CE-{consecutivo}"
    fecha = comprobante.get("fecha") or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    proveedor_nit = str(comprobante.get("proveedor_nit", ""))
    proveedor_nombre = comprobante.get("proveedor_nombre") or "Proveedor"
    monto = to_decimal(comprobante.get("monto", "0.00"))
    medio_pago = (comprobante.get("medio_pago") or "TRANSFERENCIA").upper()
    cuenta_origen = comprobante.get("cuenta_origen") or ("110505" if medio_pago == "EFECTIVO" else "111005")

    movimientos = [
        {
            "cuenta_codigo": "220505",
            "tercero_nit": proveedor_nit,
            "tercero_nombre": proveedor_nombre,
            "concepto": f"Cancelación factura proveedor CE-{consecutivo}",
            "debito": str(monto),
            "credito": "0.00",
        },
        {
            "cuenta_codigo": cuenta_origen,
            "tercero_nit": proveedor_nit,
            "tercero_nombre": proveedor_nombre,
            "concepto": f"Egreso de fondos {cuenta_origen} CE-{consecutivo}",
            "debito": "0.00",
            "credito": str(monto),
        },
    ]

    cuadrado, total_deb, total_cred = validar_partida_doble(movimientos)
    if not cuadrado:
        raise AsientoDescuadradoError(f"Asiento de comprobante de egreso descuadrado: {total_deb} != {total_cred}")

    datos_asiento = {
        "numero_comprobante": comprobante_num,
        "fecha": fecha,
        "tipo_documento": "COMPROBANTE_EGRESO",
        "documento_id": comprobante.get("id"),
        "glosa": f"Pago a proveedor {proveedor_nombre} mediante CE-{consecutivo}",
        "total_debito": str(total_deb),
        "total_credito": str(total_cred),
    }

    asiento_id = db.guardar_asiento(datos_asiento, movimientos, conn=conn)
    return db.get_asiento_by_id(asiento_id)


def contabilizar_pago_nomina(recibo: dict) -> dict:
    """Genera el asiento de pago de nómina (recibo de caja al empleado).

    Estructura de Partida Doble:
      Débito  250505 Salarios por Pagar: neto_pagar
      Crédito 110505 Caja General (EFECTIVO) o 111005 Bancos (TRANSFERENCIA): neto_pagar
    """
    neto_pagar = to_decimal(recibo.get("neto_pagar", "0.00"))
    medio_pago = recibo.get("medio_pago", "EFECTIVO").upper()
    cuenta_caja = "111005" if medio_pago in ("TRANSFERENCIA", "CONSIGNACION", "BANCO") else "110505"
    consecutivo = recibo.get("consecutivo", "0")
    prefijo = recibo.get("prefijo", "NOM")
    empleado_id = recibo.get("empleado_id")
    empleado = db.get_empleado_by_id(empleado_id) if empleado_id else None
    tercero_doc = str(empleado.get("documento", "")) if empleado else ""
    tercero_nombre = f"{empleado.get('nombres', '')} {empleado.get('apellidos', '')}".strip() or "Empleado" if empleado else "Empleado"
    fecha = recibo.get("fecha") or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    movimientos = [
        {
            "cuenta_codigo": "250505",
            "tercero_nit": tercero_doc,
            "tercero_nombre": tercero_nombre,
            "concepto": f"Pago nómina {prefijo}-{consecutivo} a {tercero_nombre}",
            "debito": str(neto_pagar),
            "credito": "0.00",
        },
        {
            "cuenta_codigo": cuenta_caja,
            "tercero_nit": tercero_doc,
            "tercero_nombre": tercero_nombre,
            "concepto": f"Pago nómina {prefijo}-{consecutivo} vía {medio_pago}",
            "debito": "0.00",
            "credito": str(neto_pagar),
        },
    ]

    cuadrado, total_deb, total_cred = validar_partida_doble(movimientos)
    if not cuadrado:
        raise AsientoDescuadradoError(f"Asiento de pago nómina descuadrado: {total_deb} != {total_cred}")

    datos_asiento = {
        "numero_comprobante": f"CC-PAGNOM-{prefijo}-{consecutivo}",
        "fecha": fecha,
        "tipo_documento": "PAGO_NOMINA",
        "documento_id": recibo.get("nomina_id"),
        "glosa": f"Pago de nómina {prefijo}-{consecutivo} a {tercero_nombre}",
        "total_debito": str(total_deb),
        "total_credito": str(total_cred),
    }

    asiento_id = db.guardar_asiento(datos_asiento, movimientos)
    return db.get_asiento_by_id(asiento_id)


def generar_balance_prueba() -> dict:
    """Genera el Balance de Comprobación consolidando todos los movimientos por cuenta contable."""
    cuentas = {c["codigo"]: dict(c) for c in db.get_cuentas_puc()}
    
    # Inicializar balances
    balance = {}
    for codigo, c in cuentas.items():
        balance[codigo] = {
            "codigo": codigo,
            "nombre": c["nombre"],
            "naturaleza": c["naturaleza"],
            "categoria": c["categoria"],
            "debitos": Decimal("0.00"),
            "creditos": Decimal("0.00"),
            "saldo_final": Decimal("0.00"),
        }

    asientos = db.get_asientos()
    gran_total_debitos = Decimal("0.00")
    gran_total_creditos = Decimal("0.00")

    for a in asientos:
        for m in a.get("movimientos", []):
            cod = m["cuenta_codigo"]
            deb = to_decimal(m.get("debito", "0.00"))
            cred = to_decimal(m.get("credito", "0.00"))
            
            gran_total_debitos += deb
            gran_total_creditos += cred

            if cod in balance:
                balance[cod]["debitos"] += deb
                balance[cod]["creditos"] += cred
            else:
                balance[cod] = {
                    "codigo": cod,
                    "nombre": m.get("cuenta_nombre", "Cuenta Desconocida"),
                    "naturaleza": "DEBITO",
                    "categoria": "OTRO",
                    "debitos": deb,
                    "creditos": cred,
                    "saldo_final": Decimal("0.00"),
                }

    # Calcular saldos finales según naturaleza
    filas = []
    for cod in sorted(balance.keys()):
        item = balance[cod]
        if item["naturaleza"] == "DEBITO":
            item["saldo_final"] = item["debitos"] - item["creditos"]
        else:
            item["saldo_final"] = item["creditos"] - item["debitos"]
        
        # Solo incluir cuentas con movimiento
        if item["debitos"] > 0 or item["creditos"] > 0:
            filas.append({
                "codigo": item["codigo"],
                "nombre": item["nombre"],
                "naturaleza": item["naturaleza"],
                "categoria": item["categoria"],
                "debitos": str(item["debitos"]),
                "creditos": str(item["creditos"]),
                "saldo_final": str(item["saldo_final"]),
            })

    cuadrado = (gran_total_debitos == gran_total_creditos)

    return {
        "cuentas": filas,
        "total_debitos": str(gran_total_debitos),
        "total_creditos": str(gran_total_creditos),
        "balance_cuadrado": cuadrado,
    }


def contabilizar_nomina(nomina: dict, conn=None) -> dict:
    """Asiento contable de una nómina electrónica (CUNE).

    El asiento se construye **por componentes** y cierra con la diferencia del
    neto, de modo que cuadra por construcción con cualquier liquidación:

      DÉBITOS
        510506  Sueldos y salarios                     salario_base
        510527  Auxilio de transporte                  auxilio_transporte
        513501  Horas extras y bonificaciones         horas + bonificaciones
        5111xx  Recargos                               recargos
        511110  Cesantías                              cesantias
        511120  Intereses sobre cesantías              intereses
        511130  Prima de servicios                     prima
        5135xx  Aportes patronales (salud/pensión/ARL/SENA/ICBF/caja)

      CRÉDITOS
        237005  Aportes salud del empleado
        238030  Aportes pensión del empleado
        236505  Retención en la fuente
        250505  Salarios por pagar (neto)

    Antes las cargas patronales iban todas a "513501 Gastos Operacionales"
    (naturaleza incorrecta) y no existían las cuentas de prestaciones sociales,
    SENA, ICBF ni caja.
    """
    consecutivo = nomina.get("consecutivo", "0")
    prefijo = nomina.get("prefijo", "NOM")
    numero_comprobante = f"CC-NOM-{prefijo}-{consecutivo}"
    fecha = nomina.get("fecha_emision") or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def d(clave):
        return to_decimal(nomina.get(clave, "0.00"))

    empleado = db.get_empleado_by_id(nomina.get("empleado_id"))
    tercero_nombre = f"{empleado.get('nombres', '')} {empleado.get('apellidos', '')}".strip() if empleado else "Empleado"
    tercero_doc = str(empleado.get("documento", "")) if empleado else ""

    concepto_base = f"Nómina {prefijo}-{consecutivo}"
    movimientos = []

    def deb(cuenta, valor, concepto):
        if valor != 0:
            movimientos.append({
                "cuenta_codigo": cuenta, "tercero_nit": tercero_doc,
                "tercero_nombre": tercero_nombre, "concepto": concepto,
                "debito": str(valor), "credito": "0.00",
            })

    def cred(cuenta, valor, concepto):
        if valor != 0:
            movimientos.append({
                "cuenta_codigo": cuenta, "tercero_nit": tercero_doc,
                "tercero_nombre": tercero_nombre, "concepto": concepto,
                "debito": "0.00", "credito": str(valor),
            })

    deb("510506", d("salario_base"), f"Sueldos {concepto_base}")
    deb("510527", d("auxilio_transporte"), f"Auxilio de transporte {concepto_base}")
    deb("513501", d("total_horas_extras") + d("bonificaciones"),
        f"Horas extras y bonificaciones {concepto_base}")
    deb("513501", d("recargo_nocturno") + d("recargo_dominical") + d("recargo_festivo"),
        f"Recargos {concepto_base}")
    deb("511110", d("cesantias"), f"Cesantías {concepto_base}")
    deb("511120", d("intereses_cesantias"), f"Intereses sobre cesantías {concepto_base}")
    deb("511130", d("prima_servicios"), f"Prima de servicios {concepto_base}")
    deb("512510", d("vacaciones"), f"Vacaciones {concepto_base}")

    deb("513530", d("empleador_salud"), f"Salud patronal {concepto_base}")
    deb("513520", d("empleador_pension"), f"Pensión patronal {concepto_base}")
    deb("541120", d("empleador_arl"), f"ARL {concepto_base}")
    deb("542510", d("empleador_sena"), f"SENA {concepto_base}")
    deb("542520", d("empleador_icbf"), f"ICBF {concepto_base}")
    deb("542530", d("empleador_caja"), f"Caja de compensación {concepto_base}")

    cred("237005", d("ded_salud"), f"Aporte salud empleado {concepto_base}")
    cred("238030", d("ded_pension"), f"Aporte pensión empleado {concepto_base}")
    cred("236505", d("ded_retencion"), f"Retención en la fuente {concepto_base}")

    # El neto a pagar es el remanente de los devengados ya posteados menos
    # las deducciones; se usa ese valor (no el declarado) para que el asiento
    # cuadre por construcción.
    neto = _neto_calculado(movimientos)
    cred("250505", neto, f"Salarios por pagar {concepto_base}")

    total_debito = sum((to_decimal(m["debito"]) for m in movimientos), Decimal("0.00"))
    total_credito = sum((to_decimal(m["credito"]) for m in movimientos), Decimal("0.00"))
    cuadrado, _, _ = validar_partida_doble(movimientos)
    if not cuadrado:
        raise AsientoDescuadradoError(
            f"El asiento contable de la nómina {numero_comprobante} está "
            f"descuadrado: Débito={total_debito} != Crédito={total_credito}"
        )

    asiento_id = db.guardar_asiento({
        "numero_comprobante": numero_comprobante,
        "fecha": fecha,
        "tipo_documento": "NOMINA",
        "documento_id": nomina.get("id"),
        "glosa": concepto_base,
        "total_debito": str(total_debito),
        "total_credito": str(total_credito),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }, movimientos, conn=conn)
    return db.get_asiento_by_id(asiento_id)


def _neto_calculado(movimientos: list[dict]) -> Decimal:
    """Suma de débitos menos retenciones: el neto implícito del asiento."""
    total = Decimal("0.00")
    for m in movimientos:
        total += to_decimal(m["debito"]) - to_decimal(m["credito"])
    return total


