import sys

import pytest

from opcoes import cli
from opcoes.db_health import resolve_postgres_target, run_db_check


_POSTGRES_ENV_KEYS = [
    "DATABASE_URL",
    "POSTGRES_DB",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "DB_HOST",
    "DB_PORT",
    "POSTGRES_HOST",
    "POSTGRES_PORT",
    "PGHOST",
    "PGPORT",
    "PGDATABASE",
    "PGUSER",
    "PGPASSWORD",
    "POSTGRES_SSLMODE",
    "PGSSLMODE",
]


def _clear_postgres_env(monkeypatch) -> None:
    for key in _POSTGRES_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_resolve_postgres_target_from_database_url(monkeypatch) -> None:
    _clear_postgres_env(monkeypatch)
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://demo:segredo@db.example.com:5433/opcoes",
    )

    target, errors = resolve_postgres_target()

    assert errors == []
    assert target is not None
    assert target.source == "DATABASE_URL"
    assert target.host == "db.example.com"
    assert target.port == 5433
    assert "segredo" not in target.redacted_dsn
    assert "***" in target.redacted_dsn


def test_resolve_postgres_target_with_invalid_database_url_port(monkeypatch) -> None:
    _clear_postgres_env(monkeypatch)
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql://demo:segredo@db.example.com:abc/opcoes"
    )

    target, errors = resolve_postgres_target()

    assert target is None
    assert any("porta não numérica" in err for err in errors)


def test_resolve_postgres_target_from_legacy_env(monkeypatch) -> None:
    _clear_postgres_env(monkeypatch)
    monkeypatch.setenv("POSTGRES_DB", "opcoes")
    monkeypatch.setenv("POSTGRES_USER", "demo")
    monkeypatch.setenv("POSTGRES_PASSWORD", "segredo")
    monkeypatch.setenv("DB_HOST", "10.0.0.2")
    monkeypatch.setenv("DB_PORT", "5434")

    target, errors = resolve_postgres_target()

    assert errors == []
    assert target is not None
    assert target.source == "POSTGRES_* / DB_*"
    assert target.host == "10.0.0.2"
    assert target.port == 5434
    assert "***" in target.redacted_dsn


def test_run_db_check_without_postgres_configuration(monkeypatch, tmp_path) -> None:
    _clear_postgres_env(monkeypatch)
    monkeypatch.setenv("OPCOES_DB_PATH", str(tmp_path / "app.db"))

    report = run_db_check(timeout_seconds=0.1)

    assert report["runtime_backend"] == "postgres"
    assert report["postgres_configured"] is False
    assert report["sql_ok"] is None
    assert any(
        "Nenhuma configuração PostgreSQL encontrada" in err for err in report["errors"]
    )


def test_cli_db_check_success_output(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        cli,
        "run_db_check",
        lambda timeout_seconds=5.0: {
            "runtime_target": "postgresql://user:***@host:5432/opcoes",
            "postgres_configured": True,
            "postgres_source": "DATABASE_URL",
            "postgres_target": "postgresql://user:***@host:5432/opcoes",
            "tcp_ok": True,
            "tcp_message": "OK",
            "sql_ok": True,
            "sql_message": "OK",
            "errors": [],
        },
    )
    monkeypatch.setattr(cli, "is_postgres_ready", lambda _report: True)
    monkeypatch.setattr(cli, "load_dotenv_once", lambda: None)
    monkeypatch.setattr(sys, "argv", ["opcoes", "db", "check"])

    cli.main()
    out = capsys.readouterr().out

    assert "Runtime atual: PostgreSQL" in out
    assert "Teste SQL (SELECT 1): OK" in out


def test_cli_db_check_failure_exits(monkeypatch) -> None:
    monkeypatch.setattr(
        cli,
        "run_db_check",
        lambda timeout_seconds=5.0: {
            "runtime_target": "postgresql://user:***@host:5432/opcoes",
            "postgres_configured": True,
            "postgres_source": "DATABASE_URL",
            "postgres_target": "postgresql://user:***@host:5432/opcoes",
            "tcp_ok": True,
            "tcp_message": "OK",
            "sql_ok": False,
            "sql_message": "timeout",
            "errors": ["Falha de conexão SQL: timeout"],
        },
    )
    monkeypatch.setattr(cli, "is_postgres_ready", lambda _report: False)
    monkeypatch.setattr(cli, "load_dotenv_once", lambda: None)
    monkeypatch.setattr(sys, "argv", ["opcoes", "db", "check"])

    with pytest.raises(SystemExit):
        cli.main()
