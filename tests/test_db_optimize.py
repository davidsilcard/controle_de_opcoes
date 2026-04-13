import sys

from opcoes import cli


def test_cli_db_optimize_success(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "load_dotenv_once", lambda: None)
    monkeypatch.setattr(cli, "get_user_app_schema", lambda *args, **kwargs: "admin")
    monkeypatch.setattr(
        cli,
        "optimize_postgres_schema",
        lambda **kwargs: {
            "schema": "admin",
            "postgres_target": "postgresql://demo:***@host:5432/opcoes",
            "applied": [
                "CREATE INDEX IF NOT EXISTS idx_option_snapshots_ticker_snapshot_date ON admin.option_snapshots (ticker, snapshot_date DESC)"
            ],
            "analyzed": ["option_snapshots"],
            "skipped": [],
        },
    )
    monkeypatch.setattr(
        sys, "argv", ["opcoes", "db", "optimize", "--username", "admin"]
    )

    cli.main()
    out = capsys.readouterr().out
    assert "Aplicando índices recomendados..." in out
    assert "Optimize concluído." in out

