from __future__ import annotations

import uuid

import pytest

from opcoes.db_health import resolve_postgres_target


@pytest.fixture(autouse=True)
def _isolated_pg_schema(monkeypatch):
    """Isola estado de banco por teste em schema PostgreSQL temporário."""

    monkeypatch.setenv("OPCOES_PG_SCHEMA", f"t_{uuid.uuid4().hex[:12]}")


def pytest_configure(config) -> None:
    config.addinivalue_line(
        "markers",
        "requires_postgres: requer configuração de conexão PostgreSQL para execução",
    )


def pytest_runtest_setup(item) -> None:
    if "requires_postgres" not in item.keywords:
        return
    target, _errors = resolve_postgres_target()
    if target is None:
        pytest.skip("Teste requer PostgreSQL configurado (DATABASE_URL ou POSTGRES_*).")
