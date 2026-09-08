from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping


def _quote_ident(value: str) -> str:
    return '"' + str(value).replace('"', '""') + '"'


def _canonical_json(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def sign_inventory(inventory: Mapping[str, Any], *, hmac_key: str) -> str:
    """Assina somente metadados e agregados, sem exportar valores financeiros."""

    if not hmac_key:
        raise ValueError("A chave HMAC do inventário não pode ser vazia.")
    return hmac.new(
        hmac_key.encode("utf-8"),
        _canonical_json(inventory),
        hashlib.sha256,
    ).hexdigest()


def _connect(dsn: str):
    try:
        import psycopg
        from psycopg.rows import dict_row
    except Exception as exc:
        raise RuntimeError(
            "Driver psycopg não encontrado. Instale com: uv sync --all-groups"
        ) from exc
    return psycopg.connect(dsn, row_factory=dict_row)


def _row_value(row: Mapping[str, Any] | tuple[Any, ...], key: str, index: int) -> Any:
    if isinstance(row, Mapping):
        return row[key]
    return row[index]


def _list_user_schemas(conn: Any) -> list[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT nspname AS schema_name
            FROM pg_namespace
            WHERE nspname <> 'information_schema'
              AND nspname NOT LIKE 'pg_%'
            ORDER BY nspname
            """
        )
        rows = cur.fetchall()
    return [str(_row_value(row, "schema_name", 0)) for row in rows]


def _list_tables(conn: Any, schemas: Iterable[str]) -> list[dict[str, Any]]:
    schema_list = list(schemas)
    if not schema_list:
        return []
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                n.nspname AS schema_name,
                c.relname AS table_name,
                pg_total_relation_size(c.oid) AS total_bytes
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = ANY(%s)
              AND c.relkind IN ('r', 'p')
            ORDER BY n.nspname, c.relname
            """,
            (schema_list,),
        )
        rows = cur.fetchall()

        tables: list[dict[str, Any]] = []
        for row in rows:
            schema = str(_row_value(row, "schema_name", 0))
            table = str(_row_value(row, "table_name", 1))
            cur.execute(
                "SELECT COUNT(*) AS row_count FROM "
                f"{_quote_ident(schema)}.{_quote_ident(table)}"
            )
            count_row = cur.fetchone()
            tables.append(
                {
                    "schema": schema,
                    "table": table,
                    "row_count": int(_row_value(count_row, "row_count", 0)),
                    "total_bytes": int(_row_value(row, "total_bytes", 2)),
                }
            )
    return tables


def _list_constraints(conn: Any, schemas: Iterable[str]) -> list[dict[str, str]]:
    schema_list = list(schemas)
    if not schema_list:
        return []
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                n.nspname AS schema_name,
                t.relname AS table_name,
                c.conname AS constraint_name,
                c.contype AS constraint_type,
                pg_get_constraintdef(c.oid, true) AS definition
            FROM pg_constraint c
            JOIN pg_class t ON t.oid = c.conrelid
            JOIN pg_namespace n ON n.oid = t.relnamespace
            WHERE n.nspname = ANY(%s)
            ORDER BY n.nspname, t.relname, c.contype, c.conname
            """,
            (schema_list,),
        )
        rows = cur.fetchall()
    return [
        {
            "schema": str(_row_value(row, "schema_name", 0)),
            "table": str(_row_value(row, "table_name", 1)),
            "name": str(_row_value(row, "constraint_name", 2)),
            "type": str(_row_value(row, "constraint_type", 3)),
            "definition": str(_row_value(row, "definition", 4)),
        }
        for row in rows
    ]


def collect_postgres_inventory(
    *,
    dsn: str,
    hmac_key: str,
    connect_factory: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    """Lê a estrutura e volumes do PostgreSQL sem selecionar valores de negócio."""

    connector = connect_factory or _connect
    with connector(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("SHOW server_version_num")
            server_version = str(_row_value(cur.fetchone(), "server_version_num", 0))
            cur.execute(
                "SELECT extname AS name, extversion AS version "
                "FROM pg_extension ORDER BY extname"
            )
            extensions = [
                {
                    "name": str(_row_value(row, "name", 0)),
                    "version": str(_row_value(row, "version", 1)),
                }
                for row in cur.fetchall()
            ]

        schemas = _list_user_schemas(conn)
        inventory = {
            "format_version": 1,
            "postgres_server_version": server_version,
            "extensions": extensions,
            "schemas": schemas,
            "tables": _list_tables(conn, schemas),
            "constraints": _list_constraints(conn, schemas),
        }

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "inventory": inventory,
        "integrity": {
            "algorithm": "HMAC-SHA-256",
            "signature": sign_inventory(inventory, hmac_key=hmac_key),
        },
    }


def write_inventory_report(
    report: Mapping[str, Any], *, output: Path, overwrite: bool = False
) -> None:
    """Grava o relatório explicitamente solicitado, sem sobrescrever por padrão."""

    destination = output.expanduser().resolve()
    if destination.exists() and not overwrite:
        raise FileExistsError(
            f"O relatório já existe: {destination}. Use --overwrite para substituí-lo."
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_bytes(_canonical_json(report) + b"\n")
    temporary.replace(destination)


__all__ = [
    "collect_postgres_inventory",
    "sign_inventory",
    "write_inventory_report",
]
