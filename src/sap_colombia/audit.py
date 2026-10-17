"""Auditoría de eventos de seguridad."""

from datetime import datetime
from sap_colombia import dbutil
from sap_colombia import database as db


def log_evento(usuario_id: int | None, email: str | None, evento: str,
               detalle: str | None = None, ip: str | None = None) -> None:
    conn = db.get_connection()
    dbutil.query(conn, 
        "CREATE TABLE IF NOT EXISTS auditoria ("
        " id SERIAL PRIMARY KEY,"
        " usuario_id INTEGER, email TEXT, evento TEXT NOT NULL,"
        " detalle TEXT, ip TEXT, created_at TEXT NOT NULL)"
    )
    dbutil.query(conn, 
        "INSERT INTO auditoria (usuario_id, email, evento, detalle, ip, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (usuario_id, email, evento, detalle, ip, datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()


def obtener_eventos(limite: int = 200) -> list[dict]:
    conn = db.get_connection()
    try:
        rows = dbutil.query(conn, 
            "SELECT * FROM auditoria ORDER BY id DESC LIMIT ?", (limite,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
