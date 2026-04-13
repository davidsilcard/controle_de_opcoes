from __future__ import annotations

from opcoes.config import (
    get_data_backend,
    get_postgres_schema,
    get_postgres_shared_schema,
    is_postgres_strict_mode,
    reset_pg_schema_override,
    sanitize_pg_schema_name,
    set_pg_schema_override,
)


def test_get_data_backend_is_postgres_only(monkeypatch) -> None:
    monkeypatch.delenv("OPCOES_DB_BACKEND", raising=False)
    assert get_data_backend() == "postgres"
    monkeypatch.setenv("OPCOES_DB_BACKEND", "mysql")
    assert get_data_backend() == "postgres"


def test_is_postgres_strict_mode_always_enabled(monkeypatch) -> None:
    monkeypatch.delenv("OPCOES_POSTGRES_STRICT", raising=False)
    assert is_postgres_strict_mode() is True
    monkeypatch.setenv("OPCOES_POSTGRES_STRICT", "0")
    assert is_postgres_strict_mode() is True


def test_get_postgres_schema_uses_override(monkeypatch) -> None:
    monkeypatch.setenv("OPCOES_PG_SCHEMA", "public")
    token = set_pg_schema_override("Admin.User")
    try:
        assert get_postgres_schema() == "admin_user"
    finally:
        reset_pg_schema_override(token)


def test_get_postgres_shared_schema_ignores_session_override(monkeypatch) -> None:
    monkeypatch.setenv("OPCOES_PG_SCHEMA", "admin")
    monkeypatch.delenv("OPCOES_SHARED_SCHEMA", raising=False)
    monkeypatch.delenv("OPCOES_AUTOMATION_SCHEMA", raising=False)
    token = set_pg_schema_override("cliente_novo")
    try:
        assert get_postgres_shared_schema() == "admin"
    finally:
        reset_pg_schema_override(token)


def test_get_postgres_shared_schema_prefers_explicit_env(monkeypatch) -> None:
    monkeypatch.setenv("OPCOES_PG_SCHEMA", "admin")
    monkeypatch.setenv("OPCOES_AUTOMATION_SCHEMA", "automation")
    monkeypatch.setenv("OPCOES_SHARED_SCHEMA", "mercado.comum")
    assert get_postgres_shared_schema() == "mercado_comum"


def test_sanitize_pg_schema_name_normalizes_symbols_and_prefixes_digits() -> None:
    assert sanitize_pg_schema_name("Cliente.Novo") == "cliente_novo"
    assert sanitize_pg_schema_name("123abc") == "u_123abc"
