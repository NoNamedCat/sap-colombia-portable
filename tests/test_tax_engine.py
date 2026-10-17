"""Pruebas unitarias del motor fiscal colombiano."""

import unittest

from decimal import Decimal

from sap_colombia.tax_engine import (
    ErrorFiscal,
    LineaFactura,
    TaxEngine,
)


class TestTarifasIVA(unittest.TestCase):
    def setUp(self):
        self.motor = TaxEngine()

    def test_iva_general_19_por_ciento(self):
        linea = LineaFactura("001", "Producto general", "1", "100000")
        resultado = self.motor.liquidar_linea(linea)
        self.assertEqual(resultado.base, Decimal("100000.00"))
        self.assertEqual(resultado.valor_iva, Decimal("19000.00"))
        self.assertEqual(resultado.valor_con_iva, Decimal("119000.00"))

    def test_iva_reducido_5_por_ciento(self):
        linea = LineaFactura("002", "Producto reducido", "1", "50000",
                             tarifa_iva="IVA_5")
        resultado = self.motor.liquidar_linea(linea)
        self.assertEqual(resultado.valor_iva, Decimal("2500.00"))

    def test_iva_exento_0(self):
        linea = LineaFactura("003", "Producto exento", "1", "10000",
                             tarifa_iva="IVA_0")
        resultado = self.motor.liquidar_linea(linea)
        self.assertEqual(resultado.valor_iva, Decimal("0"))
        self.assertEqual(resultado.valor_con_iva, Decimal("10000.00"))

    def test_tarifa_iva_invalida(self):
        with self.assertRaises(ErrorFiscal):
            LineaFactura("004", "Inválido", "1", "1000",
                         tarifa_iva="IVA_21")


class TestReteICA(unittest.TestCase):
    def setUp(self):
        self.motor = TaxEngine()

    def test_reteica_sobre_base_por_defecto(self):
        # 0.0069 sobre base 100000 = 690.00
        linea = LineaFactura("010", "Bienes", "1", "100000")
        resultado = self.motor.liquidar_linea(linea)
        self.assertEqual(resultado.reteica, Decimal("690.00"))

    def test_reteica_tarifa_personalizada(self):
        motor = TaxEngine(tarifa_reteica=Decimal("0.005"))
        linea = LineaFactura("011", "Bienes", "1", "100000")
        resultado = motor.liquidar_linea(linea)
        self.assertEqual(resultado.reteica, Decimal("500.00"))

    def test_reteica_sobre_base_inclusive_con_iva_cero(self):
        linea = LineaFactura("012", "Exento IVA", "1", "100000",
                             tarifa_iva="IVA_0")
        resultado = self.motor.liquidar_linea(linea)
        self.assertEqual(resultado.reteica, Decimal("690.00"))

    def test_tarifa_reteica_negativa_rechazada(self):
        with self.assertRaises(ErrorFiscal):
            TaxEngine(tarifa_reteica=Decimal("-0.01"))


class TestReteIVA(unittest.TestCase):
    def setUp(self):
        self.motor = TaxEngine()

    def test_reteiva_15_por_ciento_del_iva(self):
        # 15% del IVA facturado (19000) = 2850.00
        linea = LineaFactura("020", "Bienes", "1", "100000")
        resultado = self.motor.liquidar_linea(linea)
        self.assertEqual(resultado.reteiva, Decimal("2850.00"))

    def test_reteiva_tarifa_reducida(self):
        # IVA 5% de 50000 = 2500 -> 15% = 375.00
        linea = LineaFactura("021", "Reducido", "1", "50000",
                             tarifa_iva="IVA_5")
        resultado = self.motor.liquidar_linea(linea)
        self.assertEqual(resultado.reteiva, Decimal("375.00"))

    def test_reteiva_cero_si_no_hay_iva(self):
        linea = LineaFactura("022", "Sin IVA", "1", "10000",
                             tarifa_iva="IVA_0")
        resultado = self.motor.liquidar_linea(linea)
        self.assertEqual(resultado.reteiva, Decimal("0"))


class TestRetefuente(unittest.TestCase):
    def setUp(self):
        self.motor = TaxEngine()

    def test_retfuente_bienes_2_5(self):
        linea = LineaFactura("030", "Venta de bienes", "1", "100000",
                             clasificacion="BIENES")
        resultado = self.motor.liquidar_linea(linea)
        self.assertEqual(resultado.retencion_fuente, Decimal("2500.00"))

    def test_retfuente_servicios_4(self):
        linea = LineaFactura("031", "Servicio", "1", "100000",
                             clasificacion="SERVICIOS")
        resultado = self.motor.liquidar_linea(linea)
        self.assertEqual(resultado.retencion_fuente, Decimal("4000.00"))

    def test_retfuente_arrendamiento_3_5(self):
        linea = LineaFactura("032", "Arrendamiento", "1", "100000",
                             clasificacion="ARRENDAMIENTO")
        resultado = self.motor.liquidar_linea(linea)
        self.assertEqual(resultado.retencion_fuente, Decimal("3500.00"))


class TestExencion(unittest.TestCase):
    def setUp(self):
        self.motor = TaxEngine()

    def test_linea_exenta_anula_solo_retfuente(self):
        # EXENTO con IVA_19: base 100000, iva 19000
        linea = LineaFactura("040", "Persona exenta", "1", "100000",
                             clasificacion="EXENTO")
        resultado = self.motor.liquidar_linea(linea)
        self.assertEqual(resultado.retencion_fuente, Decimal("0.00"))
        self.assertEqual(resultado.reteiva, Decimal("2850.00"))
        self.assertEqual(resultado.reteica, Decimal("690.00"))
        self.assertEqual(
            resultado.total_linea,
            Decimal("119000.00") - Decimal("2850.00") - Decimal("690.00"),
        )
        self.assertEqual(resultado.total_linea, Decimal("115460.00"))

    def test_clasificacion_invalida(self):
        with self.assertRaises(ErrorFiscal):
            LineaFactura("041", "Inválido", "1", "1000",
                         clasificacion="OTRA")


class TestValidacionLinea(unittest.TestCase):
    def test_cantidad_negativa_rechazada(self):
        with self.assertRaises(ErrorFiscal):
            LineaFactura("050", "Negativo", "-1", "1000")

    def test_valor_unitario_negativo_rechazado(self):
        with self.assertRaises(ErrorFiscal):
            LineaFactura("051", "Negativo", "1", "-500")

    def test_valores_se_convierten_a_decimal(self):
        linea = LineaFactura("052", "String num", "3", "10.5")
        self.assertIsInstance(linea.cantidad, Decimal)
        self.assertIsInstance(linea.valor_unitario, Decimal)


class TestRedondeo(unittest.TestCase):
    def setUp(self):
        self.motor = TaxEngine()

    def test_redondeo_comercial(self):
        # 0.025 -> 0.03 (redondeo comercial, HALF_UP)
        linea = LineaFactura("060", "Redondeo", "1", "0.025")
        resultado = self.motor.liquidar_linea(linea)
        self.assertEqual(resultado.base, Decimal("0.03"))


class TestLiquidarFactura(unittest.TestCase):
    def setUp(self):
        self.motor = TaxEngine()

    def test_factura_mixta(self):
        lineas = [
            LineaFactura("100", "Bienes", "2", "100000", clasificacion="BIENES"),
            LineaFactura("101", "Servicio", "1", "50000", clasificacion="SERVICIOS"),
            LineaFactura("102", "Exento", "1", "20000",
                         clasificacion="EXENTO", tarifa_iva="IVA_0"),
        ]
        resultado = self.motor.liquidar_factura(lineas)

        self.assertEqual(len(resultado.lineas), 3)
        self.assertEqual(resultado.base_total, Decimal("270000.00"))
        # IVA: 200000 * 19% + 50000 * 19% + 0
        self.assertEqual(resultado.iva_total, Decimal("47500.00"))
        self.assertEqual(resultado.total_con_iva, Decimal("317500.00"))
        # ReteICA: 1380 + 345 + 138
        self.assertEqual(resultado.reteica_total, Decimal("1863.00"))
        # ReteIVA: 15% de (38000 + 9500)
        self.assertEqual(resultado.reteiva_total, Decimal("7125.00"))
        # Retefuente: 200000 * 2.5% + 50000 * 4%
        self.assertEqual(
            resultado.retencion_fuente_total, Decimal("7000.00")
        )
        self.assertEqual(
            resultado.valor_transaccion,
            Decimal("317500.00") - Decimal("7000.00")
            - Decimal("7125.00") - Decimal("1863.00"),
        )
        self.assertEqual(resultado.valor_transaccion, Decimal("301512.00"))

    def test_totales_suman_lineas_redondeadas(self):
        lineas = [
            LineaFactura("110", "Bienes A", "1", "100000",
                         clasificacion="BIENES"),
            LineaFactura("111", "Bienes B", "1", "100000",
                         clasificacion="BIENES"),
        ]
        resultado = self.motor.liquidar_factura(lineas)
        base_esperada = sum(r.base for r in resultado.lineas)
        self.assertEqual(resultado.base_total, base_esperada)
        iva_esperado = sum(r.valor_iva for r in resultado.lineas)
        self.assertEqual(resultado.iva_total, iva_esperado)

    def test_factura_vacia_rechazada(self):
        with self.assertRaises(ErrorFiscal):
            self.motor.liquidar_factura([])


if __name__ == "__main__":
    unittest.main()
