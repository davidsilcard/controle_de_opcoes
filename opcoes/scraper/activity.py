from __future__ import annotations

import contextlib
from typing import Any, Iterable, Mapping, Optional, Sequence, Tuple

from ..config import get_postgres_schema
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

    schema = get_postgres_schema()
    raw = psycopg.connect(target.dsn)
    with raw.cursor() as cur:
        cur.execute(f"CREATE SCHEMA IF NOT EXISTS {_quote_ident(schema)}")
        cur.execute(f"SET search_path TO {_quote_ident(schema)}")
    return _DbConn(raw_conn=raw)


def _row_get(row: Any, *, key: str, index: int) -> Any:
    if row is None:
        return None
    if isinstance(row, Mapping):
        return row.get(key)
    try:
        return row[index]
    except Exception:
        return None


class FlowStore:
    """Historiza volume financeiro e número de negócios por ticker."""

    def __init__(self, path: Optional[object] = None, window: int = 5) -> None:
        if path is not None:
            raise RuntimeError(
                "SQLite foi removido: FlowStore não aceita mais caminho de arquivo."
            )
        self.conn = _connect_postgres()
        self.backend = self.conn.backend
        self.window = window
        self._ensure_schema()

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self.conn.close()

    def _ensure_schema(self) -> None:
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS flow_history (
                ticker TEXT NOT NULL,
                snapshot_date TEXT NOT NULL,
                vol_fin DOUBLE PRECISION,
                num_neg DOUBLE PRECISION,
                PRIMARY KEY (ticker, snapshot_date)
            )
            """
        )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_flow_history ON flow_history (ticker, snapshot_date)"
        )
        self.conn.commit()

    def averages(self, ticker: str, snapshot_date: str) -> Tuple[Optional[float], Optional[float]]:
        cur = self.conn.execute(
            """
            SELECT vol_fin, num_neg FROM flow_history
            WHERE ticker = ? AND snapshot_date < ?
            ORDER BY snapshot_date DESC
            LIMIT ?
            """,
            (ticker, snapshot_date, self.window),
        )
        rows = cur.fetchall()
        if not rows:
            return None, None
        vols: list[float] = []
        nums: list[float] = []
        for row in rows:
            vol = _row_get(row, key="vol_fin", index=0)
            num = _row_get(row, key="num_neg", index=1)
            try:
                if vol is not None and float(vol) > 0:
                    vols.append(float(vol))
            except (TypeError, ValueError):
                pass
            try:
                if num is not None and float(num) > 0:
                    nums.append(float(num))
            except (TypeError, ValueError):
                pass
        avg_vol = sum(vols) / len(vols) if vols else None
        avg_num = sum(nums) / len(nums) if nums else None
        return avg_vol, avg_num

    def record_many(self, rows: Iterable[Tuple[str, str, Optional[float], Optional[float]]]) -> None:
        payload = [
            (ticker, date, vol if vol is not None else None, num if num is not None else None)
            for ticker, date, vol, num in rows
        ]
        if not payload:
            return
        self.conn.executemany(
            """
            INSERT INTO flow_history (ticker, snapshot_date, vol_fin, num_neg)
            VALUES (?, ?, ?, ?)
            ON CONFLICT (ticker, snapshot_date) DO UPDATE SET
                vol_fin = EXCLUDED.vol_fin,
                num_neg = EXCLUDED.num_neg
            """,
            payload,
        )
        self.conn.commit()


__all__ = ["FlowStore"]
