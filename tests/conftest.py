from __future__ import annotations

import shutil
import uuid
from pathlib import Path

import pytest

from opcoes.db_health import resolve_postgres_target


@pytest.fixture(autouse=True)
def _isolated_pg_schema(monkeypatch):
    """Isola estado de banco por teste em schema PostgreSQL temporário."""

    monkeypatch.setenv("OPCOES_PG_SCHEMA", f"t_{uuid.uuid4().hex[:12]}")
    monkeypatch.setenv("OPCOES_AUTH_SCHEMA", f"auth_{uuid.uuid4().hex[:10]}")
    monkeypatch.setenv("OPCOES_SKIP_PRODUCTION_CHECKS", "1")


@pytest.fixture
def workspace_tmp_path():
    """Usa diretório temporário local ao workspace para evitar ACL do temp global."""

    base_dir = Path(__file__).resolve().parents[1] / "codex_test_tmp"
    base_dir.mkdir(parents=True, exist_ok=True)
    path = base_dir / uuid.uuid4().hex
    path.mkdir()
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


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
