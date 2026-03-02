import sys

import pytest

from opcoes import cli


def test_cli_db_cutover_check_success(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "load_dotenv_once", lambda: None)
    monkeypatch.setattr(
        cli,
        "run_cutover_ready_check",
        lambda **kwargs: {
            "ok": True,
            "schema": "admin",
            "errors": [],
            "db_check": {
                "postgres_configured": True,
                "postgres_source": "DATABASE_URL",
                "postgres_target": "postgresql://demo:***@host:5432/opcoes",
                "tcp_ok": True,
                "tcp_message": "OK",
                "sql_ok": True,
                "sql_message": "OK",
            },
            "verify": {
                "postgres_target": "postgresql://demo:***@host:5432/opcoes",
                "tables": [
                    {
                        "source": "main",
                        "table": "positions",
                        "source_rows": 10,
                        "postgres_rows": 10,
                        "status": "ok",
                    }
                ],
            },
            "smoke": [
                {"name": "portfolio", "ok": True, "detail": "connect + query OK"},
                {"name": "finance", "ok": True, "detail": "ledger acessível"},
            ],
        },
    )
    monkeypatch.setattr(
        sys, "argv", ["opcoes", "db", "cutover-check", "--username", "admin"]
    )

    cli.main()
    out = capsys.readouterr().out
    assert "Executando checklist de cutover..." in out
    assert "3) Smoke do runtime no PostgreSQL" in out
    assert "Checklist concluído: ambiente pronto para ativar runtime PostgreSQL." in out


def test_cli_db_cutover_check_failure_exits(monkeypatch) -> None:
    monkeypatch.setattr(cli, "load_dotenv_once", lambda: None)
    monkeypatch.setattr(
        cli,
        "run_cutover_ready_check",
        lambda **kwargs: {
            "ok": False,
            "schema": "admin",
            "errors": ["Falha no smoke de runtime (portfolio): timeout"],
            "db_check": {
                "postgres_configured": True,
                "postgres_source": "DATABASE_URL",
                "postgres_target": "postgresql://demo:***@host:5432/opcoes",
                "tcp_ok": True,
                "tcp_message": "OK",
                "sql_ok": True,
                "sql_message": "OK",
            },
            "verify": None,
            "smoke": [
                {"name": "portfolio", "ok": False, "detail": "timeout"},
            ],
        },
    )
    monkeypatch.setattr(
        sys, "argv", ["opcoes", "db", "cutover-check", "--username", "admin"]
    )

    with pytest.raises(SystemExit):
        cli.main()
