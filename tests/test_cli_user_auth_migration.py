from __future__ import annotations

import sys

from opcoes import cli


def test_cli_user_migrate_auth_sqlite_prints_report(monkeypatch, capsys, tmp_path) -> None:
    monkeypatch.setattr(
        cli,
        "migrate_auth_from_legacy_sqlite",
        lambda source_db, replace: {
            "status": "ok",
            "source": str(source_db),
            "total": 3,
            "inserted": 2,
            "updated": 1 if replace else 0,
            "skipped_existing": 0,
            "skipped_invalid": 0,
        },
    )
    monkeypatch.setattr(cli, "load_dotenv_once", lambda: None)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "opcoes",
            "user",
            "migrate-auth-sqlite",
            "--source-db",
            str(tmp_path / "auth.db"),
            "--replace",
        ],
    )

    cli.main()
    out = capsys.readouterr().out
    assert "Migração de auth legado: ok" in out
    assert "inseridos" in out
    assert "atualizados" in out
