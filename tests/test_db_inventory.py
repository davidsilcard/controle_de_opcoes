from __future__ import annotations

import hashlib
import hmac
import json
import shutil
import uuid
from pathlib import Path

import pytest

from opcoes.db_inventory import (
    collect_postgres_inventory,
    sign_inventory,
    write_inventory_report,
)


class _Cursor:
    def __init__(self) -> None:
        self.queries: list[tuple[str, object]] = []
        self._rows: list[dict[str, object]] = []

    def __enter__(self) -> "_Cursor":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, query: str, params: object = None) -> None:
        self.queries.append((query, params))
        if "server_version_num" in query:
            self._rows = [{"server_version_num": "160015"}]
        elif "FROM pg_extension" in query:
            self._rows = [{"name": "plpgsql", "version": "1.0"}]
        elif "FROM pg_namespace" in query:
            self._rows = [{"schema_name": "admin"}, {"schema_name": "auth"}]
        elif "pg_total_relation_size" in query:
            self._rows = [
                {"schema_name": "admin", "table_name": "positions", "total_bytes": 8192}
            ]
        elif query.startswith("SELECT COUNT(*)"):
            self._rows = [{"row_count": 3}]
        elif "FROM pg_constraint" in query:
            self._rows = [
                {
                    "schema_name": "admin",
                    "table_name": "positions",
                    "constraint_name": "positions_pkey",
                    "constraint_type": "p",
                    "definition": "PRIMARY KEY (id)",
                }
            ]
        else:
            raise AssertionError(f"Consulta inesperada: {query}")

    def fetchall(self) -> list[dict[str, object]]:
        return self._rows

    def fetchone(self) -> dict[str, object]:
        return self._rows[0]


class _Connection:
    def __init__(self) -> None:
        self.cursor_instance = _Cursor()

    def __enter__(self) -> "_Connection":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def cursor(self) -> _Cursor:
        return self.cursor_instance


def test_inventory_is_read_only_and_signed() -> None:
    connection = _Connection()
    report = collect_postgres_inventory(
        dsn="postgresql://example",
        hmac_key="external-key",
        connect_factory=lambda _dsn: connection,
    )

    inventory = report["inventory"]
    assert inventory["postgres_server_version"] == "160015"
    assert inventory["schemas"] == ["admin", "auth"]
    assert inventory["tables"] == [
        {"schema": "admin", "table": "positions", "row_count": 3, "total_bytes": 8192}
    ]
    assert report["integrity"]["signature"] == sign_inventory(
        inventory, hmac_key="external-key"
    )
    assert all(
        query.lstrip().upper().startswith(("SELECT", "SHOW"))
        for query, _params in connection.cursor_instance.queries
    )


def test_inventory_signature_uses_canonical_json() -> None:
    inventory = {"tables": [{"table": "positions", "row_count": 3}]}
    expected = hmac.new(
        b"key",
        json.dumps(
            inventory,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode(),
        hashlib.sha256,
    ).hexdigest()
    assert sign_inventory(inventory, hmac_key="key") == expected


def test_report_refuses_overwrite_without_explicit_flag() -> None:
    temporary_dir = Path("tests/.tmp_inventory") / uuid.uuid4().hex
    output = temporary_dir / "inventory.json"
    report = {"inventory": {"tables": []}}
    try:
        write_inventory_report(report, output=output)

        with pytest.raises(FileExistsError):
            write_inventory_report(report, output=output)

        write_inventory_report(report, output=output, overwrite=True)
        assert json.loads(output.read_text(encoding="utf-8")) == report
    finally:
        shutil.rmtree(temporary_dir, ignore_errors=True)
