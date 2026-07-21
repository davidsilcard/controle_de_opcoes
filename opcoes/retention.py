from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence

from .config import get_postgres_shared_schema
from .db_health import resolve_postgres_target


@dataclass(frozen=True)
class RetentionPolicy:
    option_snapshot_days: int = 120
    option_expired_grace_days: int = 30
    underlying_snapshot_days: int = 400
    iv_history_days: int = 240
    iv_expired_grace_days: int = 30
    flow_history_days: int = 60
    ranking_days: int = 60
    fundamentus_days: int = 365


class _PgResult:
    def __init__(
        self,
        rows: Optional[list[Mapping[str, Any]]] = None,
        *,
        rowcount: int = 0,
    ) -> None:
        self._rows = list(rows or [])
        self.rowcount = int(rowcount or 0)

    def fetchone(self):
        if not self._rows:
            return None
        return self._rows[0]

    def fetchall(self):
        return list(self._rows)


class _DbConn:
    def __init__(self, *, raw_conn: Any, pg_row_factory: Any = None) -> None:
        self.backend = "postgres"
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

    def commit(self) -> None:
        self._raw_conn.commit()

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


def _connect_postgres() -> _DbConn:
    target, errors = resolve_postgres_target()
    if target is None:
        reasons = "; ".join(errors) if errors else "configuracao ausente"
        raise RuntimeError(f"PostgreSQL nao configurado: {reasons}")
    try:
        import psycopg
        from psycopg.rows import dict_row
    except Exception as exc:
        raise RuntimeError(
            "Driver psycopg nao encontrado. Instale com: uv add psycopg[binary]"
        ) from exc

    schema = get_postgres_shared_schema()
    raw_conn = psycopg.connect(target.dsn, row_factory=dict_row)
    with raw_conn.cursor() as cur:
        cur.execute(f"CREATE SCHEMA IF NOT EXISTS {_quote_ident(schema)}")
        cur.execute(f"SET search_path TO {_quote_ident(schema)}")
    return _DbConn(raw_conn=raw_conn, pg_row_factory=dict_row)


def _connect(db_path: Optional[Path] = None) -> _DbConn:
    if db_path is not None:
        raise RuntimeError("Parametro db_path nao e suportado no backend PostgreSQL.")
    return _connect_postgres()


def _table_exists(conn: _DbConn, table: str) -> bool:
    row = conn.execute(
        """
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = current_schema()
          AND table_name = ?
        LIMIT 1
        """,
        (table,),
    ).fetchone()
    return row is not None


def _safe_days(value: int) -> int:
    return max(int(value or 0), 0)


def _count_or_delete(
    conn: _DbConn,
    *,
    table: str,
    where_sql: str,
    params: Sequence[object],
    dry_run: bool,
) -> int:
    table_q = _quote_ident(table)
    if dry_run:
        row = conn.execute(
            f"SELECT COUNT(*) AS total FROM {table_q} WHERE {where_sql}",
            params,
        ).fetchone()
        return int(_first_col(row) or 0)
    result = conn.execute(
        f"DELETE FROM {table_q} WHERE {where_sql}",
        params,
    )
    return int(result.rowcount or 0)


def apply_retention(
    *,
    policy: Optional[RetentionPolicy] = None,
    today: Optional[dt.date] = None,
    dry_run: bool = False,
    db_path: Optional[Path] = None,
) -> Dict[str, Any]:
    policy = policy or RetentionPolicy()
    today = today or dt.date.today()

    option_cutoff = (
        today - dt.timedelta(days=_safe_days(policy.option_snapshot_days))
    ).isoformat()
    option_expired_cutoff = (
        today - dt.timedelta(days=_safe_days(policy.option_expired_grace_days))
    ).isoformat()
    underlying_cutoff = (
        today - dt.timedelta(days=_safe_days(policy.underlying_snapshot_days))
    ).isoformat()
    iv_cutoff = (
        today - dt.timedelta(days=_safe_days(policy.iv_history_days))
    ).isoformat()
    iv_expired_cutoff = (
        today - dt.timedelta(days=_safe_days(policy.iv_expired_grace_days))
    ).isoformat()
    flow_cutoff = (
        today - dt.timedelta(days=_safe_days(policy.flow_history_days))
    ).isoformat()
    ranking_cutoff = (
        today - dt.timedelta(days=_safe_days(policy.ranking_days))
    ).isoformat()
    fundamentus_cutoff = (
        today - dt.timedelta(days=_safe_days(policy.fundamentus_days))
    ).isoformat()
    today_iso = today.isoformat()

    removed: Dict[str, int] = {
        "ranking_entries": 0,
        "ranking_runs": 0,
        "option_snapshots_age": 0,
        "option_snapshots_expired": 0,
        "option_snapshots": 0,
        "underlying_snapshots": 0,
        "iv_history_age": 0,
        "iv_history_expired": 0,
        "iv_history": 0,
        "flow_history": 0,
        "fundamentus_snapshots": 0,
        "fundamentus_runs": 0,
        "fundamentus_signals": 0,
        "fundamentus_filter_runs": 0,
        "fundamentus_snapshot_integrity": 0,
    }

    conn = _connect(db_path)
    try:
        if _table_exists(conn, "ranking_entries"):
            removed["ranking_entries"] = _count_or_delete(
                conn,
                table="ranking_entries",
                where_sql="snapshot_date < ?",
                params=(ranking_cutoff,),
                dry_run=dry_run,
            )

        if _table_exists(conn, "ranking_runs"):
            removed["ranking_runs"] = _count_or_delete(
                conn,
                table="ranking_runs",
                where_sql="snapshot_date < ?",
                params=(ranking_cutoff,),
                dry_run=dry_run,
            )

        if _table_exists(conn, "option_snapshots"):
            removed["option_snapshots_age"] = _count_or_delete(
                conn,
                table="option_snapshots",
                where_sql="snapshot_date < ?",
                params=(option_cutoff,),
                dry_run=dry_run,
            )
            removed["option_snapshots_expired"] = _count_or_delete(
                conn,
                table="option_snapshots",
                where_sql="""
                    snapshot_date >= ?
                    AND snapshot_date < ?
                    AND vencimento IS NOT NULL
                    AND BTRIM(vencimento) <> ''
                    AND vencimento ~ '^[0-9]{2}/[0-9]{2}/[0-9]{4}$'
                    AND to_date(vencimento, 'DD/MM/YYYY') < ?
                """,
                params=(option_cutoff, today_iso, option_expired_cutoff),
                dry_run=dry_run,
            )
            removed["option_snapshots"] = (
                removed["option_snapshots_age"] + removed["option_snapshots_expired"]
            )

        if _table_exists(conn, "underlying_snapshots"):
            removed["underlying_snapshots"] = _count_or_delete(
                conn,
                table="underlying_snapshots",
                where_sql="snapshot_date < ?",
                params=(underlying_cutoff,),
                dry_run=dry_run,
            )

        if _table_exists(conn, "iv_history"):
            removed["iv_history_age"] = _count_or_delete(
                conn,
                table="iv_history",
                where_sql="snapshot_date < ?",
                params=(iv_cutoff,),
                dry_run=dry_run,
            )
            removed["iv_history_expired"] = _count_or_delete(
                conn,
                table="iv_history",
                where_sql="""
                    snapshot_date >= ?
                    AND snapshot_date < ?
                    AND vencimento IS NOT NULL
                    AND BTRIM(vencimento) <> ''
                    AND vencimento ~ '^[0-9]{2}/[0-9]{2}/[0-9]{4}$'
                    AND to_date(vencimento, 'DD/MM/YYYY') < ?
                """,
                params=(iv_cutoff, today_iso, iv_expired_cutoff),
                dry_run=dry_run,
            )
            removed["iv_history"] = (
                removed["iv_history_age"] + removed["iv_history_expired"]
            )

        if _table_exists(conn, "flow_history"):
            removed["flow_history"] = _count_or_delete(
                conn,
                table="flow_history",
                where_sql="snapshot_date < ?",
                params=(flow_cutoff,),
                dry_run=dry_run,
            )

        for table_name, key in (
            ("fundamentus_snapshots", "fundamentus_snapshots"),
            ("fundamentus_runs", "fundamentus_runs"),
            ("fundamentus_signals", "fundamentus_signals"),
            ("fundamentus_filter_runs", "fundamentus_filter_runs"),
            ("fundamentus_snapshot_integrity", "fundamentus_snapshot_integrity"),
        ):
            if _table_exists(conn, table_name):
                removed[key] = _count_or_delete(
                    conn,
                    table=table_name,
                    where_sql="snapshot_date < ?",
                    params=(fundamentus_cutoff,),
                    dry_run=dry_run,
                )

        if not dry_run:
            conn.commit()

        return {
            "dry_run": bool(dry_run),
            "today": today_iso,
            "policy": {
                "option_snapshot_days": _safe_days(policy.option_snapshot_days),
                "option_expired_grace_days": _safe_days(
                    policy.option_expired_grace_days
                ),
                "underlying_snapshot_days": _safe_days(policy.underlying_snapshot_days),
                "iv_history_days": _safe_days(policy.iv_history_days),
                "iv_expired_grace_days": _safe_days(policy.iv_expired_grace_days),
                "flow_history_days": _safe_days(policy.flow_history_days),
                "ranking_days": _safe_days(policy.ranking_days),
                "fundamentus_days": _safe_days(policy.fundamentus_days),
            },
            "cutoffs": {
                "option_snapshot_before": option_cutoff,
                "option_expired_before": option_expired_cutoff,
                "underlying_snapshot_before": underlying_cutoff,
                "iv_history_before": iv_cutoff,
                "iv_expired_before": iv_expired_cutoff,
                "flow_history_before": flow_cutoff,
                "ranking_before": ranking_cutoff,
                "fundamentus_before": fundamentus_cutoff,
            },
            "preserved_forever": [
                "positions",
                "ledger",
                "darf_months",
                "settings",
                "web_users",
                "decisions",
                "ticker_metadata",
                "service_runs",
            ],
            "removed": removed,
        }
    finally:
        conn.close()


__all__ = ["RetentionPolicy", "apply_retention"]
