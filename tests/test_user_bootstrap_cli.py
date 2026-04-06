import sys

from opcoes import cli


def test_cli_user_bootstrap_market_mode(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "load_dotenv_once", lambda: None)
    monkeypatch.setattr(
        cli,
        "create_user",
        lambda **kwargs: True,
    )
    monkeypatch.setattr(
        cli,
        "resolve_postgres_target",
        lambda: (type("Target", (), {"dsn": "postgresql://demo:secret@host:5432/opcoes"})(), []),
    )

    captured: dict[str, object] = {}

    def _clone_postgres_schema(**kwargs):
        captured.update(kwargs)
        return {
            "tables": [
                {
                    "source_schema": "admin",
                    "target_schema": "alice",
                    "table": "option_snapshots",
                    "rows": 123,
                }
            ],
            "total_rows": 123,
        }

    monkeypatch.setattr(cli, "clone_postgres_schema", _clone_postgres_schema)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "opcoes",
            "user",
            "bootstrap",
            "--username",
            "alice",
            "--password",
            "SenhaForte123!",
        ],
    )

    cli.main()
    out = capsys.readouterr().out
    assert "Bootstrap do usuário 'alice'" in out
    assert "base de mercado/configuração" in out
    assert "Bootstrap concluído." in out
    assert captured["source_schema"] == "admin"
    assert captured["target_schema"] == "alice"
    assert captured["include_tables"] == cli.USER_BOOTSTRAP_MARKET_TABLES


def test_cli_user_bootstrap_full_mode(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "load_dotenv_once", lambda: None)
    monkeypatch.setattr(cli, "create_user", lambda **kwargs: True)
    monkeypatch.setattr(
        cli,
        "resolve_postgres_target",
        lambda: (type("Target", (), {"dsn": "postgresql://demo:secret@host:5432/opcoes"})(), []),
    )

    captured: dict[str, object] = {}

    def _clone_postgres_schema(**kwargs):
        captured.update(kwargs)
        return {"tables": [], "total_rows": 0}

    monkeypatch.setattr(cli, "clone_postgres_schema", _clone_postgres_schema)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "opcoes",
            "user",
            "bootstrap",
            "--username",
            "bob",
            "--password",
            "SenhaForte123!",
            "--mode",
            "full",
            "--from-schema",
            "admin",
            "--target-schema",
            "cliente_bob",
        ],
    )

    cli.main()
    out = capsys.readouterr().out
    assert "cópia integral do schema operacional de origem" in out
    assert "cópia integral do schema operacional." in out
    assert captured["source_schema"] == "admin"
    assert captured["target_schema"] == "cliente_bob"
    assert captured["include_tables"] is None


def test_cli_user_invite_prints_temporary_password(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "load_dotenv_once", lambda: None)
    monkeypatch.setattr(
        cli,
        "issue_temporary_password",
        lambda **kwargs: "TempPass123",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "opcoes",
            "user",
            "invite",
            "--username",
            "alice",
        ],
    )

    cli.main()
    out = capsys.readouterr().out
    assert "Usuário temporário preparado: alice" in out
    assert "Senha de primeiro acesso: TempPass123" in out


def test_cli_user_invite_can_bootstrap_schema(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "load_dotenv_once", lambda: None)
    monkeypatch.setattr(cli, "issue_temporary_password", lambda **kwargs: "TempPass123")
    monkeypatch.setattr(
        cli,
        "resolve_postgres_target",
        lambda: (type("Target", (), {"dsn": "postgresql://demo:secret@host:5432/opcoes"})(), []),
    )

    captured: dict[str, object] = {}

    def _clone_postgres_schema(**kwargs):
        captured.update(kwargs)
        return {"tables": [], "total_rows": 0}

    monkeypatch.setattr(cli, "clone_postgres_schema", _clone_postgres_schema)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "opcoes",
            "user",
            "invite",
            "--username",
            "alice",
            "--bootstrap",
            "--from-schema",
            "admin",
        ],
    )

    cli.main()
    out = capsys.readouterr().out
    assert "Usuário temporário preparado: alice" in out
    assert "Bootstrap do schema alice a partir de admin" in out
    assert captured["source_schema"] == "admin"
    assert captured["target_schema"] == "alice"
