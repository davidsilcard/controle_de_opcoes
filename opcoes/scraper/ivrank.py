from __future__ import annotations

import contextlib
import datetime as dt
from typing import Any, Iterable, Mapping, Optional, Sequence, Tuple

from ..config import get_postgres_shared_schema
from ..db_health import resolve_postgres_target


class _PgResult:
    def __init__(
        self,
        rows: Optional[list[tuple]] = None,
        *,
        rowcount: int = 0,
    ) -> None:
        self._rows = list(rows or [])
        self.rowcount = int(rowcount or 0)

    def fetchall(self) -> list[tuple]:
        return list(self._rows)


class _DbConn:
    def __init__(self, *, raw_conn: Any) -> None:
        self.backend = "postgres"
        self._raw_conn = raw_conn

    def execute(self, query: str, params: Sequence[object] = ()):
        query_pg = query.replace("%", "%%").replace("?", "%s")
        with self._raw_conn.cursor() as cur:
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
    except Exception as exc:
        raise RuntimeError(
            "Driver psycopg não encontrado. Instale com: uv add psycopg[binary]"
        ) from exc

    schema = get_postgres_shared_schema()
    raw = psycopg.connect(target.dsn)
    with raw.cursor() as cur:
        cur.execute(f"CREATE SCHEMA IF NOT EXISTS {_quote_ident(schema)}")
        cur.execute(f"SET search_path TO {_quote_ident(schema)}")
    return _DbConn(raw_conn=raw)


def _first_col(row: Any) -> Any:
    if row is None:
        return None
    if isinstance(row, Mapping):
        values = list(row.values())
        return values[0] if values else None
    try:
        return row[0]
    except Exception:
        return None


class IVRankStore:
    """Armazena histórico diário de IV por underlying/vencimento e calcula o rank."""

    def __init__(self, path: Optional[object] = None, window_days: int = 180) -> None:
        if path is not None:
            raise RuntimeError(
                "SQLite foi removido: IVRankStore não aceita mais caminho de arquivo."
            )
        self.conn = _connect_postgres()
        self.backend = self.conn.backend
        self.window_days = window_days
        self._ensure_schema()

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self.conn.close()

    def _ensure_schema(self) -> None:
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS iv_history (
                underlying TEXT NOT NULL,
                vencimento TEXT NOT NULL,
                snapshot_date TEXT NOT NULL,
                iv_value DOUBLE PRECISION NOT NULL,
                PRIMARY KEY (underlying, vencimento, snapshot_date)
            )
            """
        )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_iv_history_lookup ON iv_history (underlying, vencimento, snapshot_date)"
        )
        self.conn.commit()

    def record_many(self, entries: Iterable[Tuple[str, str, str, float]]) -> None:
        payload = list(entries)
        if not payload:
            return
        self.conn.executemany(
            """
            INSERT INTO iv_history (underlying, vencimento, snapshot_date, iv_value)
            VALUES (?, ?, ?, ?)
            ON CONFLICT (underlying, vencimento, snapshot_date) DO UPDATE SET
                iv_value = EXCLUDED.iv_value
            """,
            payload,
        )
        self.conn.commit()

    def rank_for(
        self,
        underlying: str,
        vencimento: str,
        snapshot_date: str,
        current_value: float,
    ) -> Optional[float]:
        if current_value is None:
            return None
        start_date = _subtract_days(snapshot_date, self.window_days).isoformat()
        cur = self.conn.execute(
            """
            SELECT iv_value FROM iv_history
            WHERE underlying = ? AND vencimento = ?
              AND snapshot_date BETWEEN ? AND ?
            """,
            (underlying, vencimento, start_date, snapshot_date),
        )
        values = []
        for row in cur.fetchall():
            value = _first_col(row)
            if value is None:
                continue
            try:
                values.append(float(value))
            except (TypeError, ValueError):
                continue
        if not values or len(values) < 5:
            return None
        min_val = min(values)
        max_val = max(values)
        if max_val - min_val < 1e-6:
            return None
        rank = ((current_value - min_val) / (max_val - min_val)) * 100.0
        return max(0.0, min(100.0, rank))


def _subtract_days(date_iso: str, days: int) -> dt.date:
    base = dt.date.fromisoformat(date_iso)
    return base - dt.timedelta(days=days)


__all__ = ["IVRankStore"]
