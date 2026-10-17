"""Pruebas del generador de Información Exógena en archivo plano.

Verifica el formato que la DIAN realmente ingiere (Res. 000162 de 2023):
archivo de texto delimitado con registro de encabezado y patrón de nombre
``mmmvvvaaaaaaaacccccccc.TXT``.
"""

import pytest

from sap_colombia import database as db, dbutil
from sap_colombia import exogena_flat as ex


NIT = "90012345678"


@pytest.fixture(autouse=True)
def _db():
    db.init_db()
    yield


def test_nombre_archivo_cumpatron_dian():
    nombre = ex.nombre_archivo("1003", NIT, 2026)
    assert nombre.startswith("1003012026")   # mmmvvvaaaa
    assert nombre.endswith(".TXT")
    # mmm(4) + vv(2) + aaaa(4) + NIT(14) + discriminante(1) + .TXT
    sin_ext = nombre[:-4]
    assert len(sin_ext) == 25
    assert sin_ext[0:4] == "1003"
    assert sin_ext[4:6] == "01"
    assert sin_ext[6:10] == "2026"
    assert sin_ext[10:24] == NIT.zfill(14)   # NIT alineado a 14
    assert sin_ext[24] == NIT[-1]           # dígito verificador


def test_nombre_archivo_rechaza_formato_invalido():
    with pytest.raises(ex.ErrorExogena):
        ex.nombre_archivo("1", NIT, 2026)
    with pytest.raises(ex.ErrorExogena):
        ex.nombre_archivo("1003", "", 2026)


def test_encabezado_tiene_16_campos():
    linea = ex.encabezado("1001", NIT, 2026)
    campos = linea.split(ex.DELIMITADOR)
    assert len(campos) == 16
    assert campos[0] == "000"
    assert campos[1] == "01"
    assert campos[2] == NIT
    assert campos[3] == "202601"


@pytest.mark.parametrize("formato", ["1001", "1003", "1007", "2275", "2276"])
def test_archivo_tiene_encabezado_y_delimitador(formato):
    contenido = ex.generar_archivo(formato, 2026, NIT)
    lineas = contenido.strip().splitlines()
    assert lineas[0].startswith("000|")
    for l in lineas:
        assert ex.DELIMITADOR in l
    assert contenido.endswith("\n")


def test_tipo_documento_catalogo():
    assert ex.tipo_documento_por_nit("900123456", "NIT") == "13"
    assert ex.tipo_documento_por_nit("1234567890", "CC") == "14"
    # Sin tipo explícito: 9-10 dígitos ⇒ NIT
    assert ex.tipo_documento_por_nit("900123456") == "13"
    assert ex.tipo_documento_por_nit("CC12345678") == "14"


def test_1003_no_duplica_prefijo():
    """Regresión: producía 'FFAC004' al concatenar prefijo + consecutivo."""
    conn = db.get_connection()
    with conn:
        dbutil.query(conn, "DELETE FROM facturas WHERE consecutivo = 'FACX1'")
        dbutil.query(
            conn,
            "INSERT INTO facturas (empresa_id, consecutivo, prefijo, fecha, "
            "cliente_nit, subtotal, iva_19, iva_5, iva_0, total_iva, "
            "total_factura, cufe, created_at) "
            "SELECT id, 'FACX1', 'F', '2026-05-05', '800999111', '1000.00', "
            "'190.00', '0.00', '0.00', '190.00', '1190.00', repeat('e', 96), now() "
            "FROM empresas ORDER BY id LIMIT 1",
        )
    conn.close()
    registros = ex.extraer_formato_1003(2026)
    consecutivos = [r["consecutivo"] for r in registros]
    assert "FFACX1" not in consecutivos
    assert "FACX1" in consecutivos


def test_importes_con_dos_decimales_y_sin_notacion_cientifica():
    """La DIAN rechaza '1E+3' o separadores de miles."""
    assert ex._d(1000) == "1000.00"
    assert ex._d("1E+3") == "1000.00"
    assert ex._d("1234567.891") == "1234567.89"
    assert ex._d(None) == "0.00"


def test_rounding_comercial_en_exogena():
    """ROUND_HALF_UP, igual que el resto del sistema."""
    assert ex._d("1234.565") == "1234.57"
    assert ex._d("0.005") == "0.01"


def test_2276_obligatorio_para_empleadores():
    """Todo empleador con nóminas debe poder generar el 2276."""
    contenido = ex.generar_archivo("2276", 2026, NIT)
    assert "2276" in ex.nombre_archivo("2276", NIT, 2026)
    assert contenido.startswith("000|")


def test_generar_todos_devuelve_cinco_formatos():
    salida = ex.generar_todos(2026, NIT)
    assert set(salida) == {"1001", "1003", "1007", "2275", "2276"}
    for formato, info in salida.items():
        assert info["nombre"].startswith(formato)
        assert info["contenido"].startswith("000|")


def test_partes_nombre_para_persona_natural():
    assert ex._partes_nombre("Pérez / Gómez / Juan / Carlos") == (
        "Pérez Gómez", "Juan Carlos")
    apellidos, nombres = ex._apellidos_nombres("Pérez Gómez / Juan Carlos")
    assert apellidos == "Pérez"
    assert nombres == "Juan"
