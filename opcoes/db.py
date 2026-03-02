from __future__ import annotations

from contextlib import contextmanager
from typing import Any

from .config import (
    get_postgres_schema,
)
from .db_health import resolve_postgres_target


def _quote_ident(value: str) -> str:
    return '"' + str(value).replace('"', '""') + '"'


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
    return _open_postgres()


@contextmanager
def db_transaction() -> Any:
    conn = open_db()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


__all__ = ["open_db", "db_transaction"]
