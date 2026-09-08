from __future__ import annotations

import sys
import shutil
import uuid
from pathlib import Path

from opcoes import cli
from opcoes.db_health import PostgresTarget


def test_cli_db_inventory_requires_external_hmac_key(monkeypatch) -> None:
    monkeypatch.setattr(cli, "load_dotenv_once", lambda: None)
    monkeypatch.setattr(
        cli,
        "resolve_postgres_target",
        lambda: (
            PostgresTarget(
                dsn="postgresql://user:secret@db:5432/opcoes",
                redacted_dsn="postgresql://user:***@db:5432/opcoes",
                source="DATABASE_URL",
                host="db",
                port=5432,
            ),
            [],
        ),
    )
    monkeypatch.delenv("OPCOES_BASELINE_HMAC_KEY", raising=False)
    monkeypatch.setattr(
        sys,
        "argv",
        ["opcoes", "db", "inventory", "--output", "inventory.json"],
    )

    try:
        cli.main()
    except SystemExit as exc:
        assert "OPCOES_BASELINE_HMAC_KEY" in str(exc)
    else:
        raise AssertionError("O inventário deveria exigir chave HMAC externa.")


def test_cli_db_inventory_writes_explicit_path(monkeypatch, capsys) -> None:
    temporary_dir = Path("tests/.tmp_inventory") / uuid.uuid4().hex
    output = temporary_dir / "inventory.json"
    captured: dict[str, object] = {}
    monkeypatch.setattr(cli, "load_dotenv_once", lambda: None)
    monkeypatch.setattr(
        cli,
        "resolve_postgres_target",
        lambda: (
            PostgresTarget(
                dsn="postgresql://user:secret@db:5432/opcoes",
                redacted_dsn="postgresql://user:***@db:5432/opcoes",
                source="DATABASE_URL",
                host="db",
                port=5432,
            ),
            [],
        ),
    )
    monkeypatch.setenv("OPCOES_BASELINE_HMAC_KEY", "external-key")
    monkeypatch.setattr(
        cli,
        "collect_postgres_inventory",
        lambda **kwargs: captured.setdefault(
            "report",
            {
                "inventory": {"schemas": ["admin"], "tables": [], "constraints": []},
                "integrity": {"signature": "abc"},
            },
        ),
    )
    monkeypatch.setattr(
        cli,
        "write_inventory_report",
        lambda report, *, output, overwrite: captured.update(
            {"output": output, "overwrite": overwrite, "written": report}
        ),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["opcoes", "db", "inventory", "--output", str(output)],
    )

    try:
        cli.main()

        assert captured["output"] == output
        assert captured["overwrite"] is False
        assert (
            "Inventário concluído: 1 schemas, 0 tabelas, 0 constraints."
            in capsys.readouterr().out
        )
    finally:
        shutil.rmtree(temporary_dir, ignore_errors=True)
