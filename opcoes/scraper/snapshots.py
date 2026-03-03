from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from ..config import (
    get_postgres_schema,
)
from ..db_health import resolve_postgres_target
from .storage import CSV_FIELDS
from .prices import PriceIndicators


class _PgResult:
    def __init__(self, rows: Optional[list[Mapping[str, Any]]] = None, *, rowcount: int = 0) -> None:
        self._rows = list(rows or [])
        self.rowcount = int(rowcount or 0)
        self.lastrowid = None

    def fetchone(self):
        if not self._rows:
            return None
        return self._rows[0]

    def fetchall(self):
        return list(self._rows)


class _DbConn:
    def __init__(
        self,
        *,
        backend: str,
        raw_conn: Any,
        pg_row_factory: Any = None,
    ) -> None:
        self.backend = backend
        self._raw_conn = raw_conn
        self._pg_row_factory = pg_row_factory

    def execute(self, query: str, params: Sequence[object] = ()):
        query_pg = query.replace("%", "%%").replace("?", "%s")
        with self._raw_conn.cursor(row_factory=self._pg_row_factory) as cur:
            cur.execute(query_pg, tuple(params))
            rowcount = int(cur.rowcount or 0)
            if cur.description is None:
                return _PgResult([], rowcount=rowcount)
            rows = cur.fetchall()
            return _PgResult(rows, rowcount=rowcount)

    def executemany(self, query: str, params_seq: Sequence[Sequence[object]]) -> None:
        query_pg = query.replace("%", "%%").replace("?", "%s")
        with self._raw_conn.cursor() as cur:
            cur.executemany(query_pg, params_seq)

    def commit(self) -> None:
        self._raw_conn.commit()

    def rollback(self) -> None:
        self._raw_conn.rollback()

    def close(self) -> None:
        self._raw_conn.close()


def _quote_ident(value: str) -> str:
    return '"' + str(value).replace('"', '""') + '"'


def _connect_postgres() -> _DbConn:
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
    raw_conn = psycopg.connect(target.dsn, row_factory=dict_row)
    with raw_conn.cursor() as cur:
        cur.execute(f"CREATE SCHEMA IF NOT EXISTS {_quote_ident(schema)}")
        cur.execute(f"SET search_path TO {_quote_ident(schema)}")
    return _DbConn(backend="postgres", raw_conn=raw_conn, pg_row_factory=dict_row)


def _connect(path: Optional[Path]) -> _DbConn:
    if path is not None:
        raise RuntimeError("Parâmetro path não é suportado no backend PostgreSQL.")
    return _connect_postgres()


class SnapshotDB:
    """Stores daily snapshots of options and underlying indicators."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = Path(path) if path is not None else None
        self.conn = _connect(self.path)
        self._ensure_schema()

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self.conn.close()

    def _ensure_schema(self) -> None:
        columns_sql = ",\n                ".join(
            f'{_quote_ident(col)} TEXT' for col in CSV_FIELDS
        )
        self.conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS option_snapshots (
                snapshot_date TEXT NOT NULL,
                {columns_sql},
                PRIMARY KEY (snapshot_date, ticker)
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS underlying_snapshots (
                snapshot_date TEXT NOT NULL,
                underlying TEXT NOT NULL,
                price DOUBLE PRECISION,
                price_date TEXT,
                mm200 DOUBLE PRECISION,
                return_3m DOUBLE PRECISION,
                trend_flag INTEGER,
                trend_reason TEXT,
                PRIMARY KEY (snapshot_date, underlying)
            )
            """
        )
        self._ensure_columns("option_snapshots", CSV_FIELDS)
        self.conn.commit()

    def _ensure_columns(self, table: str, columns: Iterable[str]) -> None:
        rows = self.conn.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = ?
            """,
            (table,),
        ).fetchall()
        existing = {str(r["column_name"]) for r in rows}
        for col in columns:
            if col not in existing:
                self.conn.execute(
                    f'ALTER TABLE {_quote_ident(table)} ADD COLUMN IF NOT EXISTS {_quote_ident(col)} TEXT'
                )
        self.conn.commit()

    def _upsert_underlyings_sql(self) -> str:
        return """
            INSERT INTO underlying_snapshots
            (snapshot_date, underlying, price, price_date, mm200, return_3m, trend_flag, trend_reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (snapshot_date, underlying) DO UPDATE SET
                price = EXCLUDED.price,
                price_date = EXCLUDED.price_date,
                mm200 = EXCLUDED.mm200,
                return_3m = EXCLUDED.return_3m,
                trend_flag = EXCLUDED.trend_flag,
                trend_reason = EXCLUDED.trend_reason
        """

    def record_underlyings(
        self,
        snapshot_date: str,
        price_map: Mapping[str, PriceIndicators],
        symbols: Sequence[str],
    ) -> None:
        records: List[tuple] = []
        for sym in symbols:
            info = price_map.get(sym)
            if not info:
                continue
            records.append(
                (
                    snapshot_date,
                    sym,
                    info.price,
                    info.price_date,
                    info.mm200,
                    info.return_3m,
                    info.trend_flag,
                    info.trend_reason,
                )
            )
        if not records:
            return
        self.conn.executemany(self._upsert_underlyings_sql(), records)
        self.conn.commit()

    def _upsert_options_sql(self, column_clause: str, placeholders: str, update_clause: str) -> str:
        return (
            f"""
            INSERT INTO option_snapshots ({column_clause})
            VALUES ({placeholders})
            ON CONFLICT (snapshot_date, ticker) DO UPDATE SET {update_clause}
            """
        )

    def record_options(self, snapshot_date: str, rows: Iterable[Dict[str, str]]) -> None:
        rows = list(rows)
        if not rows:
            return
        columns = ["snapshot_date"] + list(CSV_FIELDS)
        column_clause = ",".join(f'"{col}"' for col in columns)
        placeholders = ",".join(["?"] * len(columns))
        update_clause = ", ".join(f'"{col}" = EXCLUDED."{col}"' for col in CSV_FIELDS)
        payload: List[List[str]] = []
        for row in rows:
            values: List[Optional[str]] = [snapshot_date]
            for col in CSV_FIELDS:
                values.append(row.get(col, ""))
            payload.append(values)
        self.conn.executemany(
            self._upsert_options_sql(column_clause, placeholders, update_clause),
            payload,
        )
        self.conn.commit()


__all__ = ["SnapshotDB"]
