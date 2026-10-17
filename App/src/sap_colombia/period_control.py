"""Control de periodos contables: cierre, reapertura y validación."""

import psycopg2
from sap_colombia import dbutil
from datetime import datetime

from sap_colombia import database as db


class PeriodoCerradoError(Exception):
    pass


class PeriodoNoAutorizadoError(Exception):
    pass


def _get_conn():
    return db.get_connection()


def get_periodo_actual() -> dict:
    """Devuelve el periodo contable actual (año, mes)."""
    ahora = datetime.now()
    periodo_key = f"{ahora.year}-{ahora.month:02d}"
    conn = _get_conn()
    try:
        row = dbutil.query(conn, 
            "SELECT * FROM periodos_contables WHERE periodo = ?", (periodo_key,)
        ).fetchone()
    finally:
        conn.close()
    if row:
        return dict(row)
    return {"periodo": periodo_key, "estado": "ABIERTO"}


def validar_periodo_abierto(periodo: str | None = None) -> dict:
    """Valida que un periodo está abierto. Lanza PeriodoCerradoError si está cerrado."""
    if periodo is None:
        periodo = get_periodo_actual()["periodo"]
    conn = _get_conn()
    try:
        row = dbutil.query(conn, 
            "SELECT * FROM periodos_contables WHERE periodo = ?", (periodo,)
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return {"periodo": periodo, "estado": "ABIERTO"}
    periodo_dict = dict(row)
    if periodo_dict["estado"] != "ABIERTO":
        raise PeriodoCerradoError(f"El periodo {periodo} está {periodo_dict['estado']}")
    return periodo_dict


def cerrar_periodo(periodo: str, usuario_id: int, justificacion: str) -> dict:
    """Cierra un periodo contable. Requiere justificación."""
    if not justificacion:
        raise ValueError("Se requiere una justificación para cerrar el periodo")
    conn = _get_conn()
    try:
        row = dbutil.query(conn, 
            "SELECT * FROM periodos_contables WHERE periodo = ?", (periodo,)
        ).fetchone()
        if row is None:
            dbutil.query(conn, 
                "INSERT INTO periodos_contables (periodo, estado, cerrado_por, fecha_cierre, justificacion) VALUES (?, 'CERRADO', ?, ?, ?)",
                (periodo, usuario_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), justificacion),
            )
        else:
            estado_actual = row["estado"]
            if estado_actual == "CERRADO":
                raise ValueError(f"El periodo {periodo} ya está cerrado")
            dbutil.query(conn, 
                "UPDATE periodos_contables SET estado = 'CERRADO', cerrado_por = ?, fecha_cierre = ?, justificacion = ? WHERE periodo = ?",
                (usuario_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), justificacion, periodo),
            )
        conn.commit()
    finally:
        conn.close()
    return {"periodo": periodo, "estado": "CERRADO", "cerrado_por": usuario_id, "justificacion": justificacion}


def reabrir_periodo(periodo: str, usuario_id: int, justificacion: str) -> dict:
    """Reabre un periodo cerrado. Requiere rol ADMIN."""
    conn = _get_conn()
    try:
        user_row = dbutil.query(conn, 
            "SELECT rol FROM usuarios WHERE id = ?", (usuario_id,)
        ).fetchone()
        if user_row is None:
            raise PermissionError("Usuario no encontrado")
        if user_row["rol"] not in ("ADMIN", "SUPERADMIN"):
            raise PermissionError("Solo el rol ADMIN o SUPERADMIN puede reabrir un periodo")
        if not justificacion:
            raise ValueError("Se requiere una justificación para reabrir el periodo")
        row = dbutil.query(conn, 
            "SELECT * FROM periodos_contables WHERE periodo = ?", (periodo,)
        ).fetchone()
        if row is None:
            raise ValueError(f"El periodo {periodo} no existe")
        estado_actual = row["estado"]
        if estado_actual == "ABIERTO":
            raise ValueError(f"El periodo {periodo} ya está abierto")
        dbutil.query(conn, 
            "UPDATE periodos_contables SET estado = 'ABIERTO', cerrado_por = NULL, fecha_cierre = NULL, justificacion = ? WHERE periodo = ?",
            (justificacion, periodo),
        )
        conn.commit()
    finally:
        conn.close()
    return {"periodo": periodo, "estado": "ABIERTO", "reabierto_por": usuario_id, "justificacion": justificacion}

