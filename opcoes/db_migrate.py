from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence
from urllib.parse import urlparse, urlunparse


_DEFAULT_APP_SCHEMA = "admin"
_DEFAULT_AUTH_SCHEMA = "auth"
_DEFAULT_TABLE_ORDER = [
    "web_users",
    "settings",
    "service_runs",
    "positions",
    "ledger",
    "darf_months",
    "option_snapshots",
    "underlying_snapshots",
    "flow_history",
    "iv_history",
    "ranking_runs",
    "ranking_entries",
    "decisions",
    "fundamentus_runs",
    "fundamentus_snapshots",
    "fundamentus_filter_runs",
    "fundamentus_signals",
    "ticker_metadata",
]
_TABLE_PRIORITY = {name: idx for idx, name in enumerate(_DEFAULT_TABLE_ORDER)}


@dataclass(frozen=True)
class ColumnDef:
    name: str
    type_sql: str
    not_null: bool
    default_expr: Optional[str]
    identity_kind: str


@dataclass(frozen=True)
class ConstraintDef:
    name: str
    definition: str


@dataclass(frozen=True)
class IndexDef:
    name: str
    definition: str


@dataclass(frozen=True)
class TableBlueprint:
    schema: str
    table: str
    columns: List[ColumnDef]
    constraints: List[ConstraintDef]
    indexes: List[IndexDef]


def _quote_ident(value: str) -> str:
    return '"' + str(value).replace('"', '""') + '"'


def _qualify(schema: str, table: str) -> str:
    return f"{_quote_ident(schema)}.{_quote_ident(table)}"


def _redact_dsn(dsn: str) -> str:
    parsed = urlparse(dsn)
    username = parsed.username or ""
    host = parsed.hostname or ""
    port = parsed.port
    if port:
        host = f"{host}:{port}"
    password = "***" if parsed.password else ""
    auth = username
    if password:
        auth = f"{username}:{password}" if username else password
    netloc = f"{auth}@{host}" if auth else host
    return urlunparse(
        (
            parsed.scheme,
            netloc,
            parsed.path,
            parsed.params,
            parsed.query,
            parsed.fragment,
        )
    )


def _connect(dsn: str):
    try:
        import psycopg
        from psycopg.rows import dict_row
    except Exception as exc:
        raise RuntimeError(
            "Driver psycopg não encontrado. Instale com: uv add psycopg[binary]"
        ) from exc
    return psycopg.connect(dsn, row_factory=dict_row)


def _rewrite_schema_refs(sql: str, *, source_schema: str, target_schema: str) -> str:
    if source_schema == target_schema:
        return sql

    replacements = [
        (f'"{source_schema}"."', f'"{target_schema}".'),
        (f'"{source_schema}".', f'"{target_schema}".'),
        (f"'{source_schema}.", f"'{target_schema}."),
        (f" {source_schema}.", f" {target_schema}."),
        (f"({source_schema}.", f"({target_schema}."),
        (f",{source_schema}.", f",{target_schema}."),
        (f"={source_schema}.", f"={target_schema}."),
    ]
    out = sql
    for old, new in replacements:
        out = out.replace(old, new)
    return out


def _table_sort_key(item: tuple[str, str]) -> tuple[int, str, str]:
    schema, table = item
    schema_rank = 0 if table == "web_users" or schema == _DEFAULT_AUTH_SCHEMA else 1
    return (schema_rank, _TABLE_PRIORITY.get(table, 10_000), schema, table)


def _list_tables(conn, schemas: Sequence[str]) -> List[tuple[str, str]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT table_schema, table_name
            FROM information_schema.tables
            WHERE table_schema = ANY(%s)
              AND table_type = 'BASE TABLE'
            ORDER BY table_schema, table_name
            """,
            (list(schemas),),
        )
        rows = cur.fetchall()
    tables = [(str(row["table_schema"]), str(row["table_name"])) for row in rows]
    tables.sort(key=_table_sort_key)
    return tables


def _normalize_table_names(values: Sequence[str] | None) -> set[str]:
    names: set[str] = set()
    for value in values or ():
        text = str(value or "").strip()
        if text:
            names.add(text)
    return names


def _fetch_columns(conn, schema: str, table: str) -> List[ColumnDef]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                a.attname AS column_name,
                pg_catalog.format_type(a.atttypid, a.atttypmod) AS type_sql,
                a.attnotnull AS not_null,
                pg_get_expr(ad.adbin, ad.adrelid) AS default_expr,
                a.attidentity AS identity_kind
            FROM pg_attribute a
            JOIN pg_class c ON c.oid = a.attrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            LEFT JOIN pg_attrdef ad ON ad.adrelid = a.attrelid AND ad.adnum = a.attnum
            WHERE n.nspname = %s
              AND c.relname = %s
              AND a.attnum > 0
              AND NOT a.attisdropped
            ORDER BY a.attnum
            """,
            (schema, table),
        )
        rows = cur.fetchall()
    return [
        ColumnDef(
            name=str(row["column_name"]),
            type_sql=str(row["type_sql"]),
            not_null=bool(row["not_null"]),
            default_expr=(
                str(row["default_expr"]) if row["default_expr"] not in (None, "") else None
            ),
            identity_kind=str(row["identity_kind"] or ""),
        )
        for row in rows
    ]


def _fetch_constraints(conn, schema: str, table: str) -> List[ConstraintDef]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                c.conname AS name,
                pg_get_constraintdef(c.oid, true) AS definition
            FROM pg_constraint c
            JOIN pg_class t ON t.oid = c.conrelid
            JOIN pg_namespace n ON n.oid = t.relnamespace
            WHERE n.nspname = %s
              AND t.relname = %s
              AND c.contype IN ('p', 'u', 'c', 'f')
            ORDER BY c.contype, c.conname
            """,
            (schema, table),
        )
        rows = cur.fetchall()
    return [
        ConstraintDef(name=str(row["name"]), definition=str(row["definition"]))
        for row in rows
    ]


def _fetch_indexes(
    conn,
    schema: str,
    table: str,
    *,
    constraint_names: Sequence[str],
) -> List[IndexDef]:
    constraint_index_names = set(constraint_names)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT indexname AS name, indexdef AS definition
            FROM pg_indexes
            WHERE schemaname = %s
              AND tablename = %s
            ORDER BY indexname
            """,
            (schema, table),
        )
        rows = cur.fetchall()
    indexes: List[IndexDef] = []
    for row in rows:
        name = str(row["name"])
        if name in constraint_index_names:
            continue
        indexes.append(IndexDef(name=name, definition=str(row["definition"])))
    return indexes


def _fetch_blueprint(conn, schema: str, table: str) -> TableBlueprint:
    constraints = _fetch_constraints(conn, schema, table)
    return TableBlueprint(
        schema=schema,
        table=table,
        columns=_fetch_columns(conn, schema, table),
        constraints=constraints,
        indexes=_fetch_indexes(
            conn,
            schema,
            table,
            constraint_names=[item.name for item in constraints],
        ),
    )


def _build_column_sql(
    column: ColumnDef,
    *,
    source_schema: str,
    target_schema: str,
) -> str:
    parts = [f"{_quote_ident(column.name)} {column.type_sql}"]
    if column.identity_kind == "a":
        parts.append("GENERATED ALWAYS AS IDENTITY")
    elif column.identity_kind == "d":
        parts.append("GENERATED BY DEFAULT AS IDENTITY")
    elif column.default_expr:
        default_expr = _rewrite_schema_refs(
            column.default_expr,
            source_schema=source_schema,
            target_schema=target_schema,
        )
        parts.append(f"DEFAULT {default_expr}")
    if column.not_null:
        parts.append("NOT NULL")
    return " ".join(parts)


def _build_create_table_sql(blueprint: TableBlueprint, *, target_schema: str) -> str:
    pieces = [
        _build_column_sql(
            column,
            source_schema=blueprint.schema,
            target_schema=target_schema,
        )
        for column in blueprint.columns
    ]
    for constraint in blueprint.constraints:
        definition = _rewrite_schema_refs(
            constraint.definition,
            source_schema=blueprint.schema,
            target_schema=target_schema,
        )
        pieces.append(f'CONSTRAINT {_quote_ident(constraint.name)} {definition}')
    inner = ",\n    ".join(pieces)
    return (
        f"CREATE TABLE IF NOT EXISTS {_qualify(target_schema, blueprint.table)} (\n"
        f"    {inner}\n"
        f")"
    )


def _existing_column_names(conn, schema: str, table: str) -> set[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = %s
              AND table_name = %s
            """,
            (schema, table),
        )
        rows = cur.fetchall()
    return {str(row["column_name"]) for row in rows}


def _existing_constraint_names(conn, schema: str, table: str) -> set[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT c.conname AS name
            FROM pg_constraint c
            JOIN pg_class t ON t.oid = c.conrelid
            JOIN pg_namespace n ON n.oid = t.relnamespace
            WHERE n.nspname = %s
              AND t.relname = %s
            """,
            (schema, table),
        )
        rows = cur.fetchall()
    return {str(row["name"]) for row in rows}


def _existing_index_names(conn, schema: str, table: str) -> set[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT indexname AS name
            FROM pg_indexes
            WHERE schemaname = %s
              AND tablename = %s
            """,
            (schema, table),
        )
        rows = cur.fetchall()
    return {str(row["name"]) for row in rows}


def _index_sql_for_target(index: IndexDef, *, source_schema: str, target_schema: str) -> str:
    sql = _rewrite_schema_refs(
        index.definition,
        source_schema=source_schema,
        target_schema=target_schema,
    )
    return re.sub(r"^CREATE\s+(UNIQUE\s+)?INDEX\s+", r"CREATE \1INDEX IF NOT EXISTS ", sql, count=1)


def _ensure_schema_and_table(conn, blueprint: TableBlueprint, *, target_schema: str) -> None:
    with conn.cursor() as cur:
        cur.execute(f"CREATE SCHEMA IF NOT EXISTS {_quote_ident(target_schema)}")
        cur.execute(_build_create_table_sql(blueprint, target_schema=target_schema))

    current_columns = _existing_column_names(conn, target_schema, blueprint.table)
    with conn.cursor() as cur:
        for column in blueprint.columns:
            if column.name in current_columns:
                continue
            cur.execute(
                f"ALTER TABLE {_qualify(target_schema, blueprint.table)} "
                f"ADD COLUMN IF NOT EXISTS "
                f"{_build_column_sql(column, source_schema=blueprint.schema, target_schema=target_schema)}"
            )

    current_constraints = _existing_constraint_names(conn, target_schema, blueprint.table)
    with conn.cursor() as cur:
        for constraint in blueprint.constraints:
            if constraint.name in current_constraints:
                continue
            definition = _rewrite_schema_refs(
                constraint.definition,
                source_schema=blueprint.schema,
                target_schema=target_schema,
            )
            cur.execute(
                f"ALTER TABLE {_qualify(target_schema, blueprint.table)} "
                f"ADD CONSTRAINT {_quote_ident(constraint.name)} {definition}"
            )

    current_indexes = _existing_index_names(conn, target_schema, blueprint.table)
    with conn.cursor() as cur:
        for index in blueprint.indexes:
            if index.name in current_indexes:
                continue
            cur.execute(
                _index_sql_for_target(
                    index,
                    source_schema=blueprint.schema,
                    target_schema=target_schema,
                )
            )

    conn.commit()


def _count_rows(conn, schema: str, table: str) -> int:
    with conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) AS total FROM {_qualify(schema, table)}")
        row = cur.fetchone()
    return int(row["total"] or 0)


def _truncate_table(conn, schema: str, table: str) -> None:
    with conn.cursor() as cur:
        cur.execute(f"TRUNCATE TABLE {_qualify(schema, table)} RESTART IDENTITY")


def _reset_identity_sequences(conn, schema: str, table: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = %s
              AND table_name = %s
              AND (is_identity = 'YES' OR column_default LIKE 'nextval(%')
            ORDER BY ordinal_position
            """,
            (schema, table),
        )
        columns = [str(row["column_name"]) for row in cur.fetchall()]

    for column_name in columns:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT setval(
                    pg_get_serial_sequence(%s, %s),
                    COALESCE((SELECT MAX({_quote_ident(column_name)}) FROM {_qualify(schema, table)}), 1),
                    EXISTS (SELECT 1 FROM {_qualify(schema, table)})
                )
                """,
                (f"{schema}.{table}", column_name),
            )


def _copy_table_data(
    source_conn,
    target_conn,
    *,
    source_schema: str,
    target_schema: str,
    table: str,
    columns: Sequence[ColumnDef],
) -> None:
    col_list = ", ".join(_quote_ident(column.name) for column in columns)
    copy_out_sql = (
        f"COPY {_qualify(source_schema, table)} ({col_list}) "
        f"TO STDOUT WITH (FORMAT CSV, NULL '\\\\N')"
    )
    copy_in_sql = (
        f"COPY {_qualify(target_schema, table)} ({col_list}) "
        f"FROM STDIN WITH (FORMAT CSV, NULL '\\\\N')"
    )

    with source_conn.cursor() as src_cur, target_conn.cursor() as dst_cur:
        with src_cur.copy(copy_out_sql) as reader, dst_cur.copy(copy_in_sql) as writer:
            for chunk in reader:
                writer.write(chunk)


def migrate_postgres(
    *,
    source_dsn: str,
    target_dsn: str,
    source_app_schema: str = _DEFAULT_APP_SCHEMA,
    target_app_schema: str = _DEFAULT_APP_SCHEMA,
    source_auth_schema: str = _DEFAULT_AUTH_SCHEMA,
    target_auth_schema: str = _DEFAULT_AUTH_SCHEMA,
    truncate_target: bool = True,
) -> Dict[str, Any]:
    source_conn = _connect(source_dsn)
    target_conn = _connect(target_dsn)
    try:
        source_tables = _list_tables(source_conn, [source_app_schema, source_auth_schema])
        if not source_tables:
            raise RuntimeError("Nenhuma tabela encontrada nos schemas de origem informados.")

        table_map = {
            (schema, table): (target_auth_schema if schema == source_auth_schema else target_app_schema)
            for schema, table in source_tables
        }
        blueprints = {
            (schema, table): _fetch_blueprint(source_conn, schema, table)
            for schema, table in source_tables
        }

        for (source_schema, table_name), target_schema in table_map.items():
            _ensure_schema_and_table(
                target_conn,
                blueprints[(source_schema, table_name)],
                target_schema=target_schema,
            )

        if truncate_target:
            for source_schema, table_name in reversed(source_tables):
                _truncate_table(target_conn, table_map[(source_schema, table_name)], table_name)
            target_conn.commit()

        report_tables: List[Dict[str, Any]] = []
        total_rows = 0
        for source_schema, table_name in source_tables:
            target_schema = table_map[(source_schema, table_name)]
            blueprint = blueprints[(source_schema, table_name)]
            source_count = _count_rows(source_conn, source_schema, table_name)
            if source_count > 0:
                _copy_table_data(
                    source_conn,
                    target_conn,
                    source_schema=source_schema,
                    target_schema=target_schema,
                    table=table_name,
                    columns=blueprint.columns,
                )
            _reset_identity_sequences(target_conn, target_schema, table_name)
            target_conn.commit()
            target_count = _count_rows(target_conn, target_schema, table_name)
            if target_count != source_count:
                raise RuntimeError(
                    f"Contagem divergente em {source_schema}.{table_name}: origem={source_count}, destino={target_count}."
                )
            total_rows += source_count
            report_tables.append(
                {
                    "source_schema": source_schema,
                    "target_schema": target_schema,
                    "table": table_name,
                    "rows": source_count,
                }
            )

        return {
            "source": _redact_dsn(source_dsn),
            "target": _redact_dsn(target_dsn),
            "tables": report_tables,
            "total_rows": total_rows,
            "truncate_target": bool(truncate_target),
        }
    finally:
        source_conn.close()
        target_conn.close()


def clone_postgres_schema(
    *,
    dsn: str,
    source_schema: str,
    target_schema: str,
    include_tables: Sequence[str] | None = None,
    truncate_target: bool = True,
) -> Dict[str, Any]:
    source_conn = _connect(dsn)
    target_conn = _connect(dsn)
    try:
        source_tables = _list_tables(source_conn, [source_schema])
        if not source_tables:
            raise RuntimeError("Nenhuma tabela encontrada no schema de origem informado.")

        allowed_tables = _normalize_table_names(include_tables)
        if allowed_tables:
            source_tables = [
                (schema, table)
                for schema, table in source_tables
                if table in allowed_tables
            ]
        if not source_tables:
            raise RuntimeError("Nenhuma tabela selecionada para copiar no bootstrap do usuario.")

        blueprints = {
            (schema, table): _fetch_blueprint(source_conn, schema, table)
            for schema, table in source_tables
        }

        for source_schema_name, table_name in source_tables:
            _ensure_schema_and_table(
                target_conn,
                blueprints[(source_schema_name, table_name)],
                target_schema=target_schema,
            )

        if truncate_target:
            for _source_schema_name, table_name in reversed(source_tables):
                _truncate_table(target_conn, target_schema, table_name)
            target_conn.commit()

        report_tables: List[Dict[str, Any]] = []
        total_rows = 0
        for source_schema_name, table_name in source_tables:
            blueprint = blueprints[(source_schema_name, table_name)]
            source_count = _count_rows(source_conn, source_schema_name, table_name)
            if source_count > 0:
                _copy_table_data(
                    source_conn,
                    target_conn,
                    source_schema=source_schema_name,
                    target_schema=target_schema,
                    table=table_name,
                    columns=blueprint.columns,
                )
            _reset_identity_sequences(target_conn, target_schema, table_name)
            target_conn.commit()
            target_count = _count_rows(target_conn, target_schema, table_name)
            if target_count != source_count:
                raise RuntimeError(
                    f"Contagem divergente em {source_schema_name}.{table_name}: origem={source_count}, destino={target_count}."
                )
            total_rows += source_count
            report_tables.append(
                {
                    "source_schema": source_schema_name,
                    "target_schema": target_schema,
                    "table": table_name,
                    "rows": source_count,
                }
            )

        return {
            "source": _redact_dsn(dsn),
            "target": _redact_dsn(dsn),
            "tables": report_tables,
            "total_rows": total_rows,
            "truncate_target": bool(truncate_target),
        }
    finally:
        source_conn.close()
        target_conn.close()


__all__ = [
    "clone_postgres_schema",
    "migrate_postgres",
    "_build_column_sql",
    "_build_create_table_sql",
    "_index_sql_for_target",
    "_rewrite_schema_refs",
]
