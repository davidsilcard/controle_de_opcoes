from __future__ import annotations

from contextlib import contextmanager
import os
import sqlite3
from typing import Any

from .config import (
    get_data_backend,
    get_db_path,
    get_postgres_schema,
    is_postgres_strict_mode,
)
from .db_health import resolve_postgres_target


def _sqlite_timeout_seconds() -> float:
    raw = os.getenv("OPCOES_SQLITE_TIMEOUT_SECONDS", "30").strip()
    try:
        value = float(raw)
    except ValueError:
        value = 30.0
    if value <= 0:
        value = 30.0
    return value


def _quote_ident(value: str) -> str:
    return '"' + str(value).replace('"', '""') + '"'


def _open_sqlite() -> sqlite3.Connection:
    path = get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    timeout_seconds = _sqlite_timeout_seconds()
    conn = sqlite3.connect(path, timeout=timeout_seconds)
    conn.row_factory = sqlite3.Row
    conn.execute(f"PRAGMA busy_timeout = {int(timeout_seconds * 1000)}")
    return conn


def _open_postgres():
    target, errors = resolve_postgres_target()
    if target is None:
        reasons = "; ".join(errors) if errors else "configuração ausente"
        raise RuntimeError(f"PostgreSQL não configurado: {reasons}")
    try:
        import psycopg
        from psycopg.rows import dict_row
    except Exception as exc:
        raise RuntimeError(
            "Driver psycopg não encontrado. Instale com: uv add psycopg[binary]"
        ) from exc

    schema = get_postgres_schema()
    conn = psycopg.connect(target.dsn, row_factory=dict_row)
    with conn.cursor() as cur:
        cur.execute(f"CREATE SCHEMA IF NOT EXISTS {_quote_ident(schema)}")
        cur.execute(f"SET search_path TO {_quote_ident(schema)}")
    return conn


def open_db() -> Any:
    if get_data_backend() == "postgres":
        try:
            return _open_postgres()
        except Exception:
            if is_postgres_strict_mode():
                raise
            return _open_sqlite()
    return _open_sqlite()


@contextmanager
def db_transaction() -> Any:
    conn = open_db()
    try:
        if isinstance(conn, sqlite3.Connection):
            conn.execute("BEGIN")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


__all__ = ["open_db", "db_transaction"]
