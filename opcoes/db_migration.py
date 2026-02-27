from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Optional

from .auth import user_db_path
from .db_health import resolve_postgres_target


@dataclass(frozen=True)
class SourceDatabase:
    label: str
    path: Path
    required: bool


@dataclass(frozen=True)
class ColumnSpec:
    name: str
    declared_type: str
    not_null: bool
    default_sql: Optional[str]
    pk_ordinal: int


@dataclass(frozen=True)
class TableSpec:
    name: str
    columns: tuple[ColumnSpec, ...]
    row_count: int


def sanitize_schema_name(value: str) -> str:
    text = (value or "").strip().lower()
    text = re.sub(r"[^a-z0-9_]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    if not text:
        return "public"
    if text[0].isdigit():
        text = f"u_{text}"
    return text[:63]


def _fallback_legacy_path(filename: str) -> Path:
    return Path("data") / filename


def resolve_user_source_databases(
    *,
    username: str,
    source_dir: Optional[Path] = None,
    source_main: Optional[Path] = None,
    source_iv: Optional[Path] = None,
    source_flow: Optional[Path] = None,
    include_aux: bool = True,
) -> list[SourceDatabase]:
    if source_dir is not None:
        base = Path(source_dir).expanduser()
    else:
        base = user_db_path(username).parent

    explicit_main = Path(source_main).expanduser() if source_main is not None else None
    explicit_iv = Path(source_iv).expanduser() if source_iv is not None else None
    explicit_flow = Path(source_flow).expanduser() if source_flow is not None else None

    main_path = explicit_main or (base / "opcoes_snapshots.db")
    iv_path = explicit_iv or (base / "iv_history.db")
    flow_path = explicit_flow or (base / "flow_history.db")

    if explicit_main is None and not main_path.exists():
        legacy = _fallback_legacy_path("opcoes_snapshots.db")
        if legacy.exists():
            main_path = legacy
    if explicit_iv is None and not iv_path.exists():
        legacy = _fallback_legacy_path("iv_history.db")
        if legacy.exists():
            iv_path = legacy
    if explicit_flow is None and not flow_path.exists():
        legacy = _fallback_legacy_path("flow_history.db")
        if legacy.exists():
            flow_path = legacy

    sources = [SourceDatabase(label="main", path=main_path, required=True)]
    if include_aux:
        sources.append(SourceDatabase(label="iv_history", path=iv_path, required=False))
        sources.append(
            SourceDatabase(label="flow_history", path=flow_path, required=False)
        )
    return sources


def _map_sqlite_type(declared_type: str) -> str:
    text = (declared_type or "").strip().upper()
    if "INT" in text:
        return "BIGINT"
    if "CHAR" in text or "CLOB" in text or "TEXT" in text:
        return "TEXT"
    if "BLOB" in text:
        return "BYTEA"
    if "REAL" in text or "FLOA" in text or "DOUB" in text:
        return "DOUBLE PRECISION"
    if "NUM" in text or "DEC" in text:
        return "NUMERIC"
    if "BOOL" in text:
        return "BOOLEAN"
    if "DATE" in text or "TIME" in text:
        return "TEXT"
    return "TEXT"


def _quote_ident(value: str) -> str:
    return '"' + str(value).replace('"', '""') + '"'


def _normalize_default(default_sql: Optional[str]) -> Optional[str]:
    if default_sql is None:
        return None
    text = str(default_sql).strip()
    if not text:
        return None
    return text


def inspect_sqlite_tables(path: Path) -> list[TableSpec]:
    resolved = Path(path).expanduser()
    conn = sqlite3.connect(resolved)
    try:
        table_names = [
            str(r[0])
            for r in conn.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
                ORDER BY name
                """
            ).fetchall()
        ]
        tables: list[TableSpec] = []
        for table in table_names:
            info_rows = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
            columns = tuple(
                ColumnSpec(
                    name=str(r[1]),
                    declared_type=str(r[2] or ""),
                    not_null=bool(r[3]),
                    default_sql=(str(r[4]) if r[4] is not None else None),
                    pk_ordinal=int(r[5] or 0),
                )
                for r in info_rows
            )
            row_count = int(
                conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0] or 0
            )
            tables.append(TableSpec(name=table, columns=columns, row_count=row_count))
        return tables
    finally:
        conn.close()


def _ensure_schema(pg_cur, schema: str) -> None:
    schema_q = _quote_ident(schema)
    pg_cur.execute(f"CREATE SCHEMA IF NOT EXISTS {schema_q}")


def _table_exists(pg_cur, schema: str, table: str) -> bool:
    pg_cur.execute("SELECT to_regclass(%s)", (f"{schema}.{table}",))
    row = pg_cur.fetchone()
    return bool(row and row[0])


def _build_create_table_sql(schema: str, table: TableSpec) -> str:
    pk_columns = [
        col.name
        for col in sorted(table.columns, key=lambda c: c.pk_ordinal)
        if col.pk_ordinal > 0
    ]
    pk_single = len(pk_columns) == 1
    pk_single_name = pk_columns[0] if pk_single else None

    column_defs: list[str] = []
    for col in table.columns:
        col_q = _quote_ident(col.name)
        mapped_type = _map_sqlite_type(col.declared_type)
        is_identity = (
            pk_single and col.name == pk_single_name and mapped_type == "BIGINT"
        )
        part = f"{col_q} {mapped_type}"
        if is_identity:
            part += " GENERATED BY DEFAULT AS IDENTITY"
        if col.not_null:
            part += " NOT NULL"
        default_sql = _normalize_default(col.default_sql)
        if default_sql is not None:
            part += f" DEFAULT {default_sql}"
        column_defs.append(part)

    if pk_columns:
        pk_sql = ", ".join(_quote_ident(name) for name in pk_columns)
        column_defs.append(f"PRIMARY KEY ({pk_sql})")

    schema_q = _quote_ident(schema)
    table_q = _quote_ident(table.name)
    cols_sql = ",\n    ".join(column_defs)
    return f"CREATE TABLE {schema_q}.{table_q} (\n" f"    {cols_sql}\n" f")"


def _set_identity_sequence(pg_cur, schema: str, table: TableSpec) -> None:
    pk_int_cols = [
        col
        for col in table.columns
        if col.pk_ordinal > 0 and _map_sqlite_type(col.declared_type) == "BIGINT"
    ]
    if len(pk_int_cols) != 1:
        return
    col_name = pk_int_cols[0].name
    schema_q = _quote_ident(schema)
    table_q = _quote_ident(table.name)
    col_q = _quote_ident(col_name)
    full_name = f"{schema_q}.{table_q}"
    pg_cur.execute(
        f"""
        SELECT setval(
            pg_get_serial_sequence(%s, %s),
            COALESCE((SELECT MAX({col_q}) FROM {full_name}), 1),
            true
        )
        """,
        (f"{schema}.{table.name}", col_name),
    )


def _copy_table_rows(
    *,
    sqlite_conn: sqlite3.Connection,
    pg_cur,
    schema: str,
    table: TableSpec,
    batch_size: int,
) -> int:
    if not table.columns:
        return 0

    column_names = [col.name for col in table.columns]
    select_cols = ", ".join(_quote_ident(c) for c in column_names)
    select_sql = f"SELECT {select_cols} FROM {_quote_ident(table.name)}"
    src_cur = sqlite_conn.execute(select_sql)

    schema_q = _quote_ident(schema)
    table_q = _quote_ident(table.name)
    copy_cols = ", ".join(_quote_ident(c) for c in column_names)
    copy_sql = f"COPY {schema_q}.{table_q} ({copy_cols}) FROM STDIN"

    total = 0
    with pg_cur.copy(copy_sql) as copy_ctx:
        while True:
            rows = src_cur.fetchmany(batch_size)
            if not rows:
                break
            for row in rows:
                copy_ctx.write_row(tuple(row))
            total += len(rows)
    return total


def migrate_sqlite_sources_to_postgres(
    *,
    schema: str,
    sources: Iterable[SourceDatabase],
    replace: bool = False,
    batch_size: int = 5000,
    dry_run: bool = False,
    log: Optional[Callable[[str], None]] = None,
) -> dict:
    logger = log or (lambda _msg: None)
    schema_name = sanitize_schema_name(schema)

    target, errors = resolve_postgres_target()
    if target is None:
        reasons = "; ".join(errors) if errors else "configuração ausente"
        raise RuntimeError(f"PostgreSQL não configurado: {reasons}")

    report = {
        "schema": schema_name,
        "postgres_source": target.source,
        "postgres_target": target.redacted_dsn,
        "dry_run": bool(dry_run),
        "sources": [],
        "tables": [],
        "rows_copied": 0,
    }

    source_list = list(sources)
    for src in source_list:
        exists = src.path.exists()
        report["sources"].append(
            {
                "label": src.label,
                "path": str(src.path),
                "exists": exists,
                "required": src.required,
            }
        )
        if not exists and src.required:
            raise FileNotFoundError(
                f"Fonte obrigatória não encontrada para '{src.label}': {src.path}"
            )

    for src in source_list:
        if not src.path.exists():
            logger(f"Fonte opcional ausente: {src.path} (pulando)")
            continue
        tables = inspect_sqlite_tables(src.path)
        for table in tables:
            report["tables"].append(
                {
                    "source": src.label,
                    "name": table.name,
                    "rows": table.row_count,
                }
            )

    if dry_run:
        return report

    try:
        import psycopg
    except Exception as exc:
        raise RuntimeError(
            "Driver psycopg não encontrado. Instale com: uv add psycopg[binary]"
        ) from exc

    with psycopg.connect(target.dsn) as pg_conn:
        with pg_conn.cursor() as pg_cur:
            _ensure_schema(pg_cur, schema_name)
        pg_conn.commit()

        for src in source_list:
            if not src.path.exists():
                continue

            sqlite_conn = sqlite3.connect(src.path)
            try:
                sqlite_conn.row_factory = sqlite3.Row
                tables = inspect_sqlite_tables(src.path)
                for table in tables:
                    schema_q = _quote_ident(schema_name)
                    table_q = _quote_ident(table.name)

                    with pg_conn.cursor() as pg_cur:
                        exists = _table_exists(pg_cur, schema_name, table.name)
                        if exists and not replace:
                            raise RuntimeError(
                                f"Tabela já existe no PostgreSQL: {schema_name}.{table.name}. "
                                f"Use --replace para sobrescrever."
                            )
                        if exists and replace:
                            pg_cur.execute(f"DROP TABLE {schema_q}.{table_q} CASCADE")

                        create_sql = _build_create_table_sql(schema_name, table)
                        pg_cur.execute(create_sql)
                        copied = _copy_table_rows(
                            sqlite_conn=sqlite_conn,
                            pg_cur=pg_cur,
                            schema=schema_name,
                            table=table,
                            batch_size=max(int(batch_size), 1),
                        )
                        _set_identity_sequence(pg_cur, schema_name, table)
                    pg_conn.commit()

                    report["rows_copied"] += int(copied)
                    logger(f"Migrado {src.label}.{table.name}: {copied} linha(s)")
            finally:
                sqlite_conn.close()

    return report


def verify_sqlite_sources_in_postgres(
    *,
    schema: str,
    sources: Iterable[SourceDatabase],
) -> dict:
    schema_name = sanitize_schema_name(schema)
    target, errors = resolve_postgres_target()
    if target is None:
        reasons = "; ".join(errors) if errors else "configuração ausente"
        raise RuntimeError(f"PostgreSQL não configurado: {reasons}")

    source_list = list(sources)
    table_rows: list[dict] = []
    for src in source_list:
        if not src.path.exists():
            if src.required:
                raise FileNotFoundError(
                    f"Fonte obrigatória não encontrada para '{src.label}': {src.path}"
                )
            continue
        for table in inspect_sqlite_tables(src.path):
            table_rows.append(
                {
                    "source": src.label,
                    "table": table.name,
                    "sqlite_rows": int(table.row_count),
                    "postgres_rows": None,
                    "status": "pending",
                }
            )

    try:
        import psycopg
    except Exception as exc:
        raise RuntimeError(
            "Driver psycopg não encontrado. Instale com: uv add psycopg[binary]"
        ) from exc

    with psycopg.connect(target.dsn) as pg_conn:
        with pg_conn.cursor() as pg_cur:
            for row in table_rows:
                table_name = str(row["table"])
                pg_cur.execute("SELECT to_regclass(%s)", (f"{schema_name}.{table_name}",))
                found = pg_cur.fetchone()
                if not found or found[0] is None:
                    row["status"] = "missing_in_postgres"
                    continue
                schema_q = _quote_ident(schema_name)
                table_q = _quote_ident(table_name)
                pg_cur.execute(f"SELECT COUNT(*) FROM {schema_q}.{table_q}")
                pg_count = int(pg_cur.fetchone()[0] or 0)
                row["postgres_rows"] = pg_count
                row["status"] = (
                    "ok" if pg_count == int(row["sqlite_rows"]) else "count_mismatch"
                )

    mismatches = [
        r for r in table_rows if r["status"] in {"missing_in_postgres", "count_mismatch"}
    ]
    return {
        "schema": schema_name,
        "postgres_target": target.redacted_dsn,
        "tables": table_rows,
        "ok": len(mismatches) == 0,
        "mismatches": mismatches,
    }


__all__ = [
    "SourceDatabase",
    "ColumnSpec",
    "TableSpec",
    "sanitize_schema_name",
    "resolve_user_source_databases",
    "inspect_sqlite_tables",
    "migrate_sqlite_sources_to_postgres",
    "verify_sqlite_sources_in_postgres",
]
