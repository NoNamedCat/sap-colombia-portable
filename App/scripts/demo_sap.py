#!/usr/bin/env python3
"""Demo end-to-end de la emisión de una factura colombiana (FacturaE DIAN).

Pasos:
1. Definir Emisor y Adquirente ficticios.
2. Crear líneas de factura (IVA 19%, 5% y exento).
3. Liquidar con TaxEngine (Base, IVA, Retefuente, ReteICA, Total).
4. Generar XML UBL 2.1, CUFE y QR con UblInvoiceBuilder/cufe_calculator.
5. Transmitir a DianMockServer mediante DianClient.
6. Consultar el TrackId y verificar StatusCode '00'.
7. Parar el mock server de forma limpia.
"""

import sys
from decimal import Decimal
from pathlib import Path

RAIZ_PROYECTO = Path(__file__).resolve().parent.parent
if str(RAIZ_PROYECTO) not in sys.path:
    sys.path.insert(0, str(RAIZ_PROYECTO))

from sap_colombia.cufe_calculator import cufe_base
from sap_colombia.dian_client import DianClient
from sap_colombia.dian_mock_server import DianMockServer
from sap_colombia.tax_engine import LineaFactura, TaxEngine
from sap_colombia.ubl_builder import Adquirente, Emisor, UblInvoiceBuilder


def _cop(valor: Decimal) -> str:
    return f"COP {valor:,.2f}".replace(",", ".")


def main() -> int:
    print("=" * 78)
    print("DEMO SAP Colombia - Emisión de factura DIAN (FacturaE)")
    print("=" * 78)

    print("\n[1/7] Datos de las partes (ficticios)")
    emisor = Emisor(
        nit="900.123.456-7",
        nombre="Saluki Solutions S.A.S.",
        direccion="Cra 15 # 45-30, PBX 12",
        ciudad="Bogotá D.C.",
        subdib="11",
    )
    adquirente = Adquirente(
        nit="800.987.654-3",
        nombre="Comercial Andina Ltda.",
        direccion="Av. El Poblado # 34-12, Of. 503",
        ciudad="Medellín",
        subdib="11",
    )
    print(f"  Emisor:     {emisor.nombre} (NIT {emisor.nit})")
    print(f"  Adquirente: {adquirente.nombre} (NIT {adquirente.nit})")

    print("\n[2/7] Líneas de la factura")
    lineas = [
        LineaFactura("001", "Laptop Dell XPS 13 (16GB/512GB)", "2", "3200000.00"),
        LineaFactura("002", "Licencia anual de software corporativo", "1", "1500000.00",
                     clasificacion="SERVICIOS", tarifa_iva="IVA_5"),
        LineaFactura("003", "Vestuario médico (exento)", "10", "85000.00",
                     clasificacion="EXENTO", tarifa_iva="IVA_0"),
    ]
    for l in lineas:
        print(f"  {l.codigo} - {l.descripcion} x{l.cantidad} @ {_cop(l.valor_unitario)} "
              f"[{l.tarifa_iva}/{l.clasificacion}]")

    print("\n[3/7] Liquidación fiscal (TaxEngine)")
    engine = TaxEngine()
    resultado = engine.liquidar_factura(lineas)
    print(f"  Base:          {_cop(resultado.base_total)}")
    print(f"  IVA:           {_cop(resultado.iva_total)}")
    print(f"  Total c/ IVA:  {_cop(resultado.total_con_iva)}")
    print(f"  ReteFuente:    {_cop(resultado.retencion_fuente_total)}")
    print(f"  ReteICA:       {_cop(resultado.reteica_total)}")
    print(f"  Total:         {_cop(resultado.valor_transaccion)}")

    print("\n[4/7] Generación UBL 2.1 / CUFE / QR (UblInvoiceBuilder + cufe_calculator)")
    builder = UblInvoiceBuilder(emisor, adquirente, engine=engine)
    factura = builder.build("1001", "2024-01-15", "10:30:00", lineas)
    categorias = {t: Decimal("0") for t in ("IVA_0", "IVA_5", "IVA_19")}
    for r in factura.resultado.lineas:
        categorias[r.linea.tarifa_iva] += r.valor_iva
    base_cufe = cufe_base("1001", "2024-01-15", "10:30:00",
                          factura.valor_factura, categorias,
                          emisor.nit, adquirente.nit, "10", "1",
                          factura.valor_transaccion)
    print(f"  Base CUFE (96+ chars): {base_cufe}")
    print(f"  XML UBL generado:     {len(factura.xml)} bytes")

    print("\n[5/7] CUFE y cadena QR")
    print(f"  CUFE: {factura.cufe}")
    assert len(factura.cufe) == 96, "El CUFE debe tener 96 caracteres"
    print(f"  QR:   {factura.qr}")

    print("\n[6/7] Transmisión al mock DIAN (DianMockServer + DianClient)")
    server = DianMockServer(emisor.nit)
    server.start()
    print(f"  Mock server iniciado: {server.base_url}")
    try:
        cliente = DianClient(server.base_url)
        transmision = cliente.transmitir(factura)
        print(f"  TrackId:            {transmision.track_id}")
        print(f"  StatusCode:         {transmision.status_code}")
        print(f"  StatusDescription:  {transmision.status_description}")
        print(f"  Fecha validación:   {transmision.fecha_validacion}")

        print("\n[7/7] Consulta por TrackId")
        consulta = cliente.consultar(transmision.track_id)
        print(f"  Estado:           {consulta.estado}")
        print(f"  StatusCode:       {consulta.status_code}")
        print(f"  StatusDescription: {consulta.status_description}")
        if consulta.status_code != "00" or consulta.estado != "Aceptada":
            print("  ERROR: la DIAN (mock) no validó la factura.")
            return 1
        print("\n  OK: factura validada por la DIAN (mock).")
    finally:
        server.stop()
        print("\n  Mock server detenido.")

    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
