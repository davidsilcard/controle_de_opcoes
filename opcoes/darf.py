from __future__ import annotations

import datetime as dt
import os
import sqlite3
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .config import get_data_backend, get_db_path, get_postgres_schema
from .db_health import resolve_postgres_target


@dataclass(frozen=True)
class DarfMonth:
    id: int
    period: str  # YYYY-MM
    due_date: str  # YYYY-MM-DD
    amount: float  # valor a pagar (positivo)
    paid_date: Optional[str] = None  # YYYY-MM-DD
    paid_amount: Optional[float] = None  # positivo
    notes: Optional[str] = None
    is_simulated: bool = False


class _PgResult:
    def __init__(
        self,
        rows: Optional[list[Mapping[str, Any]]] = None,
        *,
        rowcount: int = 0,
        lastrowid: Optional[int] = None,
    ) -> None:
        self._rows = list(rows or [])
        self.rowcount = int(rowcount or 0)
        self.lastrowid = lastrowid

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

    def commit(self) -> None:
        self._raw_conn.commit()

    def rollback(self) -> None:
        self._raw_conn.rollback()

    def close(self) -> None:
        self._raw_conn.close()


def _quote_ident(value: str) -> str:
    return '"' + str(value).replace('"', '""') + '"'


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


def _sqlite_timeout_seconds() -> float:
    raw = os.getenv("OPCOES_SQLITE_TIMEOUT_SECONDS", "30").strip()
    try:
        value = float(raw)
    except ValueError:
        value = 30.0
    if value <= 0:
        value = 30.0
    return value


def _connect_sqlite(*, ensure_schema: bool = False) -> _DbConn:
    timeout_seconds = _sqlite_timeout_seconds()
    raw_conn = sqlite3.connect(get_db_path(), timeout=timeout_seconds)
    raw_conn.row_factory = sqlite3.Row
    raw_conn.execute(f"PRAGMA busy_timeout = {int(timeout_seconds * 1000)}")
    conn = _DbConn(backend="sqlite", raw_conn=raw_conn)
    if ensure_schema:
        _ensure_tables(conn, commit=True)
    return conn


def _connect_postgres(*, ensure_schema: bool = False) -> _DbConn:
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
    conn = _DbConn(backend="postgres", raw_conn=raw_conn, pg_row_factory=dict_row)
    if ensure_schema:
        _ensure_tables(conn, commit=True)
    return conn


def _connect(*, ensure_schema: bool = False) -> _DbConn:
    backend = get_data_backend()
    if backend == "postgres":
        try:
            return _connect_postgres(ensure_schema=ensure_schema)
        except Exception:
            return _connect_sqlite(ensure_schema=ensure_schema)
    return _connect_sqlite(ensure_schema=ensure_schema)


def _table_exists(conn: _DbConn, table_name: str) -> bool:
    if conn.backend == "postgres":
        row = conn.execute("SELECT to_regclass(?)", (table_name,)).fetchone()
        return _first_col(row) is not None
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ? LIMIT 1",
        (table_name,),
    ).fetchone()
    return row is not None


def _ensure_tables(conn: _DbConn, *, commit: bool) -> None:
    if conn.backend == "postgres":
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS darf_months (
                id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                period TEXT NOT NULL,
                due_date TEXT NOT NULL,
                amount DOUBLE PRECISION NOT NULL,
                paid_date TEXT,
                paid_amount DOUBLE PRECISION,
                notes TEXT,
                is_simulated INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(period, is_simulated)
            )
            """
        )
    else:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS darf_months (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                period TEXT NOT NULL,
                due_date TEXT NOT NULL,
                amount REAL NOT NULL,
                paid_date TEXT,
                paid_amount REAL,
                notes TEXT,
                is_simulated INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(period, is_simulated)
            )
            """
        )
    if commit:
        conn.commit()


def _parse_period(period: str) -> str:
    text = (period or "").strip()
    if len(text) != 7 or text[4] != "-":
        raise ValueError("Período inválido (use YYYY-MM).")
    year = int(text[:4])
    month = int(text[5:7])
    if month < 1 or month > 12:
        raise ValueError("Período inválido (mês).")
    return f"{year:04d}-{month:02d}"


def last_business_day_next_month(period: str) -> str:
    """Último dia útil do mês seguinte (considera apenas fim de semana; ignora feriados)."""
    p = _parse_period(period)
    year = int(p[:4])
    month = int(p[5:7])

    next_year = year + 1 if month == 12 else year
    next_month = 1 if month == 12 else month + 1

    # último dia do mês seguinte
    if next_month == 12:
        first_after = dt.date(next_year + 1, 1, 1)
    else:
        first_after = dt.date(next_year, next_month + 1, 1)
    d = first_after - dt.timedelta(days=1)

    # ajusta se cair em sábado/domingo
    while d.weekday() >= 5:
        d -= dt.timedelta(days=1)
    return d.isoformat()


def upsert_month(
    *,
    period: str,
    due_date: str,
    amount: float,
    is_simulated: bool = False,
    notes: Optional[str] = None,
) -> int:
    p = _parse_period(period)
    now = dt.datetime.now().isoformat(timespec="seconds")
    conn = _connect(ensure_schema=True)
    try:
        existing = conn.execute(
            "SELECT id FROM darf_months WHERE period = ? AND COALESCE(is_simulated, 0) = ?",
            (p, 1 if is_simulated else 0),
        ).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE darf_months
                SET due_date = ?,
                    amount = ?,
                    notes = COALESCE(?, notes),
                    updated_at = ?
                WHERE id = ?
                """,
                (due_date, float(amount), notes, now, int(existing["id"])),
            )
            conn.commit()
            return int(existing["id"])

        params = (p, due_date, float(amount), notes, 1 if is_simulated else 0, now, now)
        if conn.backend == "postgres":
            row = conn.execute(
                """
                INSERT INTO darf_months
                (period, due_date, amount, notes, is_simulated, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                RETURNING id
                """,
                params,
            ).fetchone()
            record_id = _first_col(row)
        else:
            cur = conn.execute(
                """
                INSERT INTO darf_months
                (period, due_date, amount, notes, is_simulated, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                params,
            )
            record_id = cur.lastrowid
        if record_id is None:
            raise RuntimeError("Falha ao obter id do registro DARF.")
        conn.commit()
        return int(record_id)
    finally:
        conn.close()


def get_month(*, period: str, is_simulated: bool = False) -> Optional[DarfMonth]:
    p = _parse_period(period)
    conn = _connect()
    try:
        if not _table_exists(conn, "darf_months"):
            return None
        row = conn.execute(
            "SELECT * FROM darf_months WHERE period = ? AND COALESCE(is_simulated, 0) = ?",
            (p, 1 if is_simulated else 0),
        ).fetchone()
        if not row:
            return None
        return DarfMonth(
            id=int(row["id"]),
            period=str(row["period"]),
            due_date=str(row["due_date"]),
            amount=float(row["amount"]),
            paid_date=row["paid_date"],
            paid_amount=float(row["paid_amount"]) if row["paid_amount"] is not None else None,
            notes=row["notes"],
            is_simulated=bool(row["is_simulated"] or 0),
        )
    finally:
        conn.close()


def list_months(*, is_simulated: bool, limit: int = 36) -> List[DarfMonth]:
    conn = _connect()
    try:
        if not _table_exists(conn, "darf_months"):
            return []
        rows = conn.execute(
            """
            SELECT *
            FROM darf_months
            WHERE COALESCE(is_simulated, 0) = ?
            ORDER BY period DESC
            LIMIT ?
            """,
            (1 if is_simulated else 0, int(limit)),
        ).fetchall()
        out: List[DarfMonth] = []
        for r in rows:
            out.append(
                DarfMonth(
                    id=int(r["id"]),
                    period=str(r["period"]),
                    due_date=str(r["due_date"]),
                    amount=float(r["amount"]),
                    paid_date=r["paid_date"],
                    paid_amount=float(r["paid_amount"]) if r["paid_amount"] is not None else None,
                    notes=r["notes"],
                    is_simulated=bool(r["is_simulated"] or 0),
                )
            )
        return out
    finally:
        conn.close()


def mark_paid(
    *,
    period: str,
    paid_date: str,
    paid_amount: Optional[float] = None,
    is_simulated: bool = False,
) -> None:
    p = _parse_period(period)
    conn = _connect(ensure_schema=True)
    try:
        row = conn.execute(
            "SELECT id, amount FROM darf_months WHERE period = ? AND COALESCE(is_simulated, 0) = ?",
            (p, 1 if is_simulated else 0),
        ).fetchone()
        if not row:
            raise ValueError("DARF do mês não gerado.")
        amount = float(paid_amount) if paid_amount is not None else float(row["amount"])
        now = dt.datetime.now().isoformat(timespec="seconds")
        conn.execute(
            """
            UPDATE darf_months
            SET paid_date = ?,
                paid_amount = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (paid_date, float(amount), now, int(row["id"])),
        )
        conn.commit()
    finally:
        conn.close()


def get_monthly_darf_provisions(*, is_simulated: bool, limit: int = 36) -> Dict[str, float]:
    """Soma provisões de DARF (saldo limpo) por competência (YYYY-MM)."""
    conn = _connect()
    try:
        if not _table_exists(conn, "ledger"):
            return {}
        rows = conn.execute(
            """
            SELECT substr(date, 1, 7) AS period, SUM(amount) AS total
            FROM ledger
            WHERE type = 'DARF'
              AND position_id IS NOT NULL
              AND COALESCE(is_simulated, 0) = ?
            GROUP BY period
            ORDER BY period DESC
            LIMIT ?
            """,
            (1 if is_simulated else 0, int(limit)),
        ).fetchall()
        # amount no ledger é negativo; aqui devolvemos positivo
        out: Dict[str, float] = {}
        for r in rows:
            period = r["period"]
            if not period:
                continue
            total = float(r["total"] or 0.0)
            out[str(period)] = max(0.0, -total)
        return out
    finally:
        conn.close()


def list_provision_entries(*, period: str, is_simulated: bool) -> List[dict]:
    """Lista lançamentos de provisão (DARF com position_id) para auditoria."""
    p = _parse_period(period)
    conn = _connect()
    try:
        if not _table_exists(conn, "ledger"):
            return []
        rows = conn.execute(
            """
            SELECT
              l.id,
              l.date,
              l.amount,
              l.description,
              l.position_id,
              p.ticker AS position_ticker,
              p.underlying AS position_underlying
            FROM ledger l
            LEFT JOIN positions p ON p.id = l.position_id
            WHERE l.type = 'DARF'
              AND l.position_id IS NOT NULL
              AND substr(l.date, 1, 7) = ?
              AND COALESCE(l.is_simulated, 0) = ?
            ORDER BY l.date DESC, l.id DESC
            """,
            (p, 1 if is_simulated else 0),
        ).fetchall()
        out: List[dict] = []
        for r in rows:
            out.append(
                {
                    "id": int(r["id"]),
                    "date": r["date"],
                    "amount": float(r["amount"] or 0.0),
                    "description": r["description"],
                    "position_id": r["position_id"],
                    "position_ticker": r["position_ticker"],
                    "position_underlying": r["position_underlying"],
                }
            )
        return out
    finally:
        conn.close()


__all__ = [
    "DarfMonth",
    "get_month",
    "list_months",
    "get_monthly_darf_provisions",
    "list_provision_entries",
    "last_business_day_next_month",
    "upsert_month",
    "mark_paid",
]
