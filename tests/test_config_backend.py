from __future__ import annotations

from opcoes.config import (
    get_data_backend,
    get_postgres_schema,
    is_postgres_strict_mode,
    reset_pg_schema_override,
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
