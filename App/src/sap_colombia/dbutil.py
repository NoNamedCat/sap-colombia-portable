"""Helpers para PostgreSQL directo (psycopg2) con pool de conexiones thread-safe."""
from __future__ import annotations

import sys
import threading
import psycopg2
import psycopg2.extensions
import psycopg2.extras
import psycopg2.pool

# Asegurar que `import dbutil` y `from sap_colombia import dbutil` resuelvan al mismo módulo
sys.modules.setdefault("dbutil", sys.modules[__name__])
sys.modules.setdefault("sap_colombia.dbutil", sys.modules[__name__])

_pools_lock = threading.Lock()
_pools: dict[str, psycopg2.pool.ThreadedConnectionPool] = {}


class _PooledConnection:
    """Wrapper transparente sobre una conexión psycopg2 que la devuelve al pool en close()."""

    __slots__ = ("_conn", "_pool", "_returned")

    def __init__(self, conn: psycopg2.extensions.connection, pool: psycopg2.pool.ThreadedConnectionPool | None):
        self._conn = conn
        self._pool = pool
        self._returned = False

    def cursor(self, *args, **kwargs):
        return self._conn.cursor(*args, **kwargs)

    def commit(self):
        return self._conn.commit()

    def rollback(self):
        return self._conn.rollback()

    @property
    def autocommit(self) -> bool:
        return self._conn.autocommit

    @autocommit.setter
    def autocommit(self, value: bool) -> None:
        self._conn.autocommit = value

    @property
    def closed(self) -> int:
        return 1 if self._returned else self._conn.closed

    def __enter__(self):
        self._conn.__enter__()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return self._conn.__exit__(exc_type, exc_val, exc_tb)

    def close(self) -> None:
        if self._returned:
            return
        self._returned = True
        if self._pool is None:
            try:
                self._conn.close()
            except Exception:
                pass
            return
        try:
            if self._conn.closed:
                self._pool.putconn(self._conn, close=True)
            else:
                if self._conn.info.transaction_status in (
                    psycopg2.extensions.TRANSACTION_STATUS_INTRANS,
                    psycopg2.extensions.TRANSACTION_STATUS_INERROR,
                ):
                    self._conn.rollback()
                self._conn.autocommit = False
                self._pool.putconn(self._conn)
        except Exception:
            try:
                self._conn.close()
            except Exception:
                pass

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def __getattr__(self, name: str):
        return getattr(self._conn, name)


def _get_pool(dsn: str) -> psycopg2.pool.ThreadedConnectionPool:
    with _pools_lock:
        pool = _pools.get(dsn)
        if pool is None or pool.closed:
            pool = psycopg2.pool.ThreadedConnectionPool(
                minconn=1,
                maxconn=64,
                dsn=dsn,
                cursor_factory=psycopg2.extras.RealDictCursor,
            )
            _pools[dsn] = pool
        return pool


def close_all_pools() -> None:
    """Cierra todos los pools activos (útil al cambiar de base de datos en tests)."""
    with _pools_lock:
        for pool in _pools.values():
            try:
                if not pool.closed:
                    pool.closeall()
            except Exception:
                pass
        _pools.clear()


def get_conn(dsn: str) -> _PooledConnection:
    try:
        pool = _get_pool(dsn)
        raw_conn = pool.getconn()
        if raw_conn.closed:
            pool.putconn(raw_conn, close=True)
            raw_conn = psycopg2.connect(dsn, cursor_factory=psycopg2.extras.RealDictCursor)
            raw_conn.autocommit = False
            return _PooledConnection(raw_conn, None)
        raw_conn.autocommit = False
        return _PooledConnection(raw_conn, pool)
    except Exception:
        raw_conn = psycopg2.connect(dsn, cursor_factory=psycopg2.extras.RealDictCursor)
        raw_conn.autocommit = False
        return _PooledConnection(raw_conn, None)


def query(conn, sql: str, params: tuple | None = None):
    """Ejecuta una consulta SQL con placeholders ?.

    Reescribe ? -> %s en la sentencia SQL para psycopg2.
    """
    sql = sql.replace("?", "%s")
    cur = conn.cursor()
    cur.execute(sql, params)
    return cur


def query_many(conn, sql: str, registros: list[tuple]) -> None:
    """Ejecuta INSERT/UPDATE parametrizado con múltiples filas."""
    sql = sql.replace("?", "%s")
    cur = conn.cursor()
    cur.executemany(sql, [tuple(r) for r in registros])
    cur.close()


def exec_script(conn, script: str) -> None:
    """Ejecuta un script SQL multi-sentencia separando por semicolones."""
    for statement in script.split(";"):
        statement = statement.strip()
        if statement:
            conn.cursor().execute(statement)
            conn.commit()


def table_columns(conn, table_name: str) -> list[str]:
    cur = conn.cursor()
    cur.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = %s AND table_schema = 'public' ORDER BY ordinal_position",
        (table_name,),
    )
    cols = [r["column_name"] for r in cur.fetchall()]
    cur.close()
    return cols
