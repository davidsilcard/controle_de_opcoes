from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Mapping, Optional

from .config import (
    get_postgres_shared_schema,
    reset_pg_schema_override,
    set_pg_schema_override,
)
from .db import open_db
from .scraper.storage import CSV_FIELDS, CSV_WRITER_KWARGS, _ensure_parent, normalize_csv_row


def _pg_safe(query: str) -> str:
    # Escapa '%' em nomes de colunas sem quebrar placeholders '%s'.
    return query.replace("%", "%%").replace("%%s", "%s")


def _row_get(row: Any, key: str, default: Any = None) -> Any:
    if row is None:
        return default
    if isinstance(row, Mapping):
        return row.get(key, default)
    try:
        return row[key]
    except Exception:
        return default


def _has_option_snapshots_table(conn) -> bool:
    row = conn.execute(
        "SELECT to_regclass(current_schema() || '.option_snapshots') AS reg"
    ).fetchone()
    return bool(_row_get(row, "reg"))


def _ensure_snapshot_columns(conn) -> None:
    if not _has_option_snapshots_table(conn):
        return

    rows = conn.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'option_snapshots'
        """
    ).fetchall()
    existing = {str(_row_get(r, "column_name", "") or "") for r in rows}
    missing = [col for col in CSV_FIELDS if col not in existing]
    if not missing:
        return
    for col in missing:
        sql = f'ALTER TABLE "option_snapshots" ADD COLUMN IF NOT EXISTS "{col}" TEXT'
        conn.execute(_pg_safe(sql))
    conn.commit()


def export_snapshot(
    *,
    output_csv: Path,
    snapshot_date: Optional[str] = None,
) -> Path:
    """Exporta um snapshot PostgreSQL para CSV (sem deduplicar por ticker)."""

    output_csv = Path(output_csv)
    _ensure_parent(output_csv)

    token = set_pg_schema_override(get_postgres_shared_schema())
    try:
        conn = open_db()
    finally:
        reset_pg_schema_override(token)
    try:
        _ensure_snapshot_columns(conn)
        if not _has_option_snapshots_table(conn):
            raise RuntimeError("Nenhum snapshot encontrado em option_snapshots.")

        if snapshot_date is None:
            row = conn.execute(
                "SELECT MAX(snapshot_date) AS snapshot_date FROM option_snapshots"
            ).fetchone()
            latest = _row_get(row, "snapshot_date")
            if not latest:
                raise RuntimeError("Nenhum snapshot encontrado em option_snapshots.")
            snapshot_date = str(latest)

        cols_clause = ", ".join(f'"{c}"' for c in CSV_FIELDS)
        query = f"""
            SELECT {cols_clause}
            FROM option_snapshots
            WHERE snapshot_date = %s
            ORDER BY underlying, ticker
        """
        rows = conn.execute(_pg_safe(query), (snapshot_date,)).fetchall()
    finally:
        conn.close()

    with output_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, **CSV_WRITER_KWARGS)
        writer.writeheader()
        for r in rows:
            out_row = {}
            for col in CSV_FIELDS:
                value = _row_get(r, col)
                out_row[col] = value if value is not None else ""
            writer.writerow(normalize_csv_row(out_row))

    return output_csv


__all__ = ["export_snapshot"]
