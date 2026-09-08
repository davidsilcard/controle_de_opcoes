from __future__ import annotations

import re
import shutil
import uuid
from pathlib import Path
from typing import Callable, Iterable

import pytest

from opcoes.db_health import resolve_postgres_target


_TEST_SCHEMA_NAME = re.compile(
    r"^(?:t_[0-9a-f]{12}|auth_[0-9a-f]{10})(?:_[a-z0-9_]+)?$"
)
_POSTGRES_TEST_DSN: str | None = None


def _cleanup_test_schemas(
    *,
    dsn: str,
    schema_names: Iterable[str],
    connect_factory: Callable[..., object] | None = None,
) -> None:
    """Remove somente schemas aleatórios criados por esta suíte de testes."""

    schemas = tuple(dict.fromkeys(schema_names))
    if not schemas:
        return
    if any(_TEST_SCHEMA_NAME.fullmatch(schema) is None for schema in schemas):
        raise RuntimeError("Recusa de limpeza: schema de teste inválido.")

    if connect_factory is None:
        import psycopg

        connect_factory = psycopg.connect

    with connect_factory(dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            schemas_to_drop: set[str] = set()
            for schema in schemas:
                cur.execute(
                    "SELECT nspname FROM pg_namespace "
                    "WHERE nspname = %s OR nspname LIKE %s ESCAPE '\\'",
                    (schema, f"{schema}\\_%"),
                )
                schemas_to_drop.update(str(row[0]) for row in cur.fetchall())

            if any(
                _TEST_SCHEMA_NAME.fullmatch(schema) is None
                for schema in schemas_to_drop
            ):
                raise RuntimeError("Recusa de limpeza: schema descendente inválido.")
            for schema in sorted(schemas_to_drop, reverse=True):
                cur.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')


def _prepare_test_schemas(
    *,
    dsn: str,
    schema_names: Iterable[str],
    connect_factory: Callable[..., object] | None = None,
) -> None:
    """Reproduz o bootstrap dos schemas somente no banco de testes."""

    schemas = tuple(dict.fromkeys(schema_names))
    if any(_TEST_SCHEMA_NAME.fullmatch(schema) is None for schema in schemas):
        raise RuntimeError("Recusa de preparo: schema de teste inválido.")
    if not schemas:
        return
    if connect_factory is None:
        import psycopg

        connect_factory = psycopg.connect
    with connect_factory(dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            for schema in schemas:
                cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')


@pytest.fixture(autouse=True)
def _isolated_pg_schema(monkeypatch, request):
    """Isola estado de banco por teste em schema PostgreSQL temporário."""

    app_schema = f"t_{uuid.uuid4().hex[:12]}"
    auth_schema = f"auth_{uuid.uuid4().hex[:10]}"

    monkeypatch.setenv("OPCOES_PG_SCHEMA", app_schema)
    monkeypatch.setenv("OPCOES_AUTH_SCHEMA", auth_schema)
    monkeypatch.setenv("OPCOES_SHARED_SCHEMA", app_schema)
    monkeypatch.setenv("OPCOES_AUTOMATION_SCHEMA", app_schema)
    monkeypatch.setenv("OPCOES_SKIP_PRODUCTION_CHECKS", "1")
    try:
        if _POSTGRES_TEST_DSN and "requires_postgres" in request.keywords:
            _prepare_test_schemas(
                dsn=_POSTGRES_TEST_DSN,
                schema_names=(app_schema, auth_schema),
            )
        yield
    finally:
        if _POSTGRES_TEST_DSN:
            _cleanup_test_schemas(
                dsn=_POSTGRES_TEST_DSN,
                schema_names=(app_schema, auth_schema),
            )


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


def pytest_sessionstart(session) -> None:
    """Captura o banco real antes que testes alterem variáveis de ambiente."""

    del session
    global _POSTGRES_TEST_DSN
    target, _errors = resolve_postgres_target()
    _POSTGRES_TEST_DSN = target.dsn if target is not None else None


def pytest_runtest_setup(item) -> None:
    if "requires_postgres" not in item.keywords:
        return
    target, _errors = resolve_postgres_target()
    if target is None:
        pytest.skip("Teste requer PostgreSQL configurado (DATABASE_URL ou POSTGRES_*).")
