"""Generación de reportes CSV y Excel para exportación de datos gerenciales."""

import csv
import io
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(BASE_DIR)
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

try:
    from openpyxl import Workbook
    OPENPYXL_AVAILABLE = True
except ImportError:
    Workbook = None
    OPENPYXL_AVAILABLE = False


class ExportError(Exception):
    pass


def _to_row(row: dict, columnas: list[str]) -> list:
    return [row.get(col) if row.get(col) is not None else "" for col in columnas]


def _escribir_csv(columnas: list[str], rows: list[dict], nombres_columnas: list[str] | None = None) -> bytes:
    nombres = nombres_columnas or columnas
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(nombres)
    for row in rows:
        writer.writerow([str(v) if v is not None else "" for v in _to_row(row, columnas)])
    return buffer.getvalue().encode("utf-8-sig")


def _escribir_excel(columnas: list[str], rows: list[dict], titulo: str = "Reporte") -> bytes:
    if not OPENPYXL_AVAILABLE:
        raise ExportError("La librería openpyxl no está instalada para generar Excel.")
    wb = Workbook()
    ws = wb.active
    ws.title = titulo[:31] or "Reporte"
    ws.append(columnas)
    for row in rows:
        ws.append([row.get(col) for col in columnas])
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def exportar_csv(
    columnas: list[str],
    rows: list[dict],
    nombres_columnas: list[str] | None = None,
) -> bytes:
    return _escribir_csv(columnas, rows, nombres_columnas)


def exportar_excel(
    columnas: list[str],
    rows: list[dict],
    titulo: str = "Reporte",
) -> bytes:
    return _escribir_excel(columnas, rows, titulo)


def exportar(
    formato: str,
    columnas: list[str],
    rows: list[dict],
    nombres_columnas: list[str] | None = None,
    titulo: str = "Reporte",
) -> bytes:
    formato = (formato or "csv").lower().strip()
    if formato == "csv":
        return exportar_csv(columnas, rows, nombres_columnas)
    if formato == "xlsx":
        return exportar_excel(columnas, rows, titulo)
    raise ExportError(f"Formato de exportación no soportado: {formato}")
