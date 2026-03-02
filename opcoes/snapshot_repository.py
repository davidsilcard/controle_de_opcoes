from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .config import get_db_path
from .db import open_db
from .scraper.storage import _ensure_parent


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
    def __init__(self, *, backend: str, raw_conn: Any, pg_row_factory: Any = None) -> None:
        self.backend = backend
        self._raw_conn = raw_conn
        self._pg_row_factory = pg_row_factory

    def execute(self, query: str, params: Sequence[object] = ()):
        if self.backend == "sqlite":
            return self._raw_conn.execute(query, tuple(params))
        query_pg = query.replace("%", "%%").replace("?", "%s")
        with self._raw_conn.cursor(row_factory=self._pg_row_factory) as cur:
            cur.execute(query_pg, tuple(params))
            rowcount = int(cur.rowcount or 0)
            if cur.description is None:
                return _PgResult([], rowcount=rowcount)
            rows = cur.fetchall()
            return _PgResult(rows, rowcount=rowcount)

    def close(self) -> None:
        self._raw_conn.close()


def _connect(db_path: Optional[Path] = None) -> _DbConn:
    # Compatibilidade: db_path explícito força leitura SQLite por arquivo.
    if db_path is not None:
        path = db_path
    else:
        path = None
    if path is not None:
        _ensure_parent(path)
        raw = sqlite3.connect(path)
        raw.row_factory = sqlite3.Row
        return _DbConn(backend="sqlite", raw_conn=raw)

    raw = open_db()
    module_name = raw.__class__.__module__
    if module_name.startswith("sqlite3"):
        return _DbConn(backend="sqlite", raw_conn=raw)
    try:
        from psycopg.rows import dict_row

        return _DbConn(backend="postgres", raw_conn=raw, pg_row_factory=dict_row)
    except Exception:
        return _DbConn(backend="postgres", raw_conn=raw)


def _latest_snapshot_date_conn(conn: _DbConn) -> Optional[str]:
    row = conn.execute("SELECT MAX(snapshot_date) AS d FROM option_snapshots").fetchone()
    if not row:
        return None
    if isinstance(row, Mapping):
        return row.get("d")
    return row[0]


def latest_snapshot_date(db_path: Optional[Path] = None) -> Optional[str]:
    """Recupera a data mais recente disponível em option_snapshots."""

    conn = _connect(db_path)
    try:
        return _latest_snapshot_date_conn(conn)
    finally:
        conn.close()


def fetch_latest_underlying_options(
    underlying: str,
    *,
    db_path: Optional[Path] = None,
) -> List[Dict[str, object]]:
    """Busca linhas de option_snapshots do último snapshot para um underlying."""

    underlying = (underlying or "").strip().upper()
    if not underlying:
        return []

    conn = _connect(db_path)
    try:
        snapshot_date = _latest_snapshot_date_conn(conn)
        if not snapshot_date:
            return []
        rows = conn.execute(
            """
            SELECT
                ticker,
                underlying,
                option_type,
                vencimento,
                dias_uteis,
                strike,
                dist_perc_strike,
                underlying_price,
                underlying_price_date,
                extrinsic_pct_spot,
                "%_Alta_p_2x" AS pct_2x,
                score_total,
                best_bid,
                best_ask,
                ultimo,
                preco_teorico,
                vol_impl_perc,
                iv_rank_180d
            FROM option_snapshots
            WHERE snapshot_date = ?
              AND UPPER(underlying) = ?
              AND dias_uteis IS NOT NULL
            """,
            (snapshot_date, underlying),
        ).fetchall()
        return [dict(r) if isinstance(r, Mapping) else dict(zip(r.keys(), r)) for r in rows]
    finally:
        conn.close()


def fetch_latest_underlying_quote(
    underlying: str,
    *,
    db_path: Optional[Path] = None,
) -> Optional[Dict[str, object]]:
    """Busca a cotação mais recente do underlying em underlying_snapshots."""

    underlying = (underlying or "").strip().upper()
    if not underlying:
        return None

    conn = _connect(db_path)
    try:
        snapshot_date = _latest_snapshot_date_conn(conn)
        if not snapshot_date:
            return None
        row = conn.execute(
            """
            SELECT snapshot_date, underlying, price, price_date, mm200, return_3m, trend_flag, trend_reason
            FROM underlying_snapshots
            WHERE snapshot_date = ?
              AND UPPER(underlying) = ?
            LIMIT 1
            """,
            (snapshot_date, underlying),
        ).fetchone()
        if not row:
            return None
        if not isinstance(row, Mapping):
            row = dict(zip(row.keys(), row))
        return {
            "snapshot_date": row["snapshot_date"],
            "underlying": row["underlying"],
            "price": row["price"],
            "price_date": row["price_date"],
            "mm200": row["mm200"],
            "return_3m": row["return_3m"],
            "trend_flag": row["trend_flag"],
            "trend_reason": row["trend_reason"],
        }
    finally:
        conn.close()


__all__ = ["latest_snapshot_date", "fetch_latest_underlying_options", "fetch_latest_underlying_quote"]
