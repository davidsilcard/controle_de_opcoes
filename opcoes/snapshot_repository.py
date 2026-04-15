from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .config import (
    get_postgres_shared_schema,
    reset_pg_schema_override,
    set_pg_schema_override,
)
from .db import open_db


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
    if db_path is not None:
        raise RuntimeError("Parâmetro db_path não é suportado no backend PostgreSQL.")

    token = set_pg_schema_override(get_postgres_shared_schema())
    try:
        raw = open_db()
    finally:
        reset_pg_schema_override(token)
    try:
        from psycopg.rows import dict_row

        return _DbConn(backend="postgres", raw_conn=raw, pg_row_factory=dict_row)
    except Exception:
        return _DbConn(backend="postgres", raw_conn=raw)


def _latest_snapshot_date_conn(conn: _DbConn) -> Optional[str]:
    try:
        row = conn.execute("SELECT MAX(snapshot_date) AS d FROM option_snapshots").fetchone()
    except Exception as exc:
        if 'relation "option_snapshots" does not exist' in str(exc).lower():
            return None
        raise
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
        try:
            rows = conn.execute(
                """
                SELECT
                    snapshot_date,
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
        except Exception as exc:
            if 'relation "option_snapshots" does not exist' in str(exc).lower():
                return []
            raise
        return [dict(r) if isinstance(r, Mapping) else dict(zip(r.keys(), r)) for r in rows]
    finally:
        conn.close()


def fetch_latest_option_snapshots(
    tickers: Sequence[str],
    *,
    db_path: Optional[Path] = None,
) -> Dict[str, Dict[str, object]]:
    normalized = sorted(
        {
            (ticker or "").strip().upper()
            for ticker in tickers
            if (ticker or "").strip()
        }
    )
    if not normalized:
        return {}

    conn = _connect(db_path)
    try:
        placeholders = ",".join(["?"] * len(normalized))
        try:
            rows = conn.execute(
                f"""
                WITH latest AS (
                    SELECT ticker, MAX(snapshot_date) AS snapshot_date
                    FROM option_snapshots
                    WHERE ticker IN ({placeholders})
                    GROUP BY ticker
                )
                SELECT
                    os.ticker,
                    os.underlying,
                    os.snapshot_date,
                    os."ultimo" AS last_price_raw,
                    os."score_total" AS last_score_total,
                    os."trend_flag" AS last_trend_flag,
                    os."vencimento" AS last_vencimento,
                    os."dias_uteis" AS last_dias_uteis,
                    os."underlying_price" AS last_underlying_price,
                    os."extrinsic_pct_spot" AS last_extrinsic_pct_spot,
                    os."%_Alta_p_2x" AS last_pct_2x,
                    os."strike" AS last_strike
                FROM option_snapshots os
                INNER JOIN latest
                    ON latest.ticker = os.ticker
                   AND latest.snapshot_date = os.snapshot_date
                """,
                normalized,
            ).fetchall()
        except Exception as exc:
            if 'relation "option_snapshots" does not exist' in str(exc).lower():
                return {}
            raise
        result: Dict[str, Dict[str, object]] = {}
        for row in rows:
            payload = dict(row) if isinstance(row, Mapping) else dict(zip(row.keys(), row))
            ticker = str(payload.get("ticker") or "").strip().upper()
            if ticker:
                result[ticker] = payload
        return result
    finally:
        conn.close()


def fetch_latest_option_snapshot(
    ticker: str,
    *,
    db_path: Optional[Path] = None,
) -> Optional[Dict[str, object]]:
    normalized = (ticker or "").strip().upper()
    if not normalized:
        return None
    return fetch_latest_option_snapshots([normalized], db_path=db_path).get(normalized)


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
        try:
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
        except Exception as exc:
            if 'relation "underlying_snapshots" does not exist' in str(exc).lower():
                return None
            raise
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


__all__ = [
    "latest_snapshot_date",
    "fetch_latest_option_snapshot",
    "fetch_latest_option_snapshots",
    "fetch_latest_underlying_options",
    "fetch_latest_underlying_quote",
]
