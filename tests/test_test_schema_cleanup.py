from __future__ import annotations

import pytest

from tests import conftest


class _FakeCursor:
    def __init__(self, schema_rows: list[tuple[str]]) -> None:
        self.queries: list[tuple[str, tuple[str, ...] | None]] = []
        self.schema_rows = schema_rows

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, query: str, params: tuple[str, ...] | None = None) -> None:
        self.queries.append((query, params))

    def fetchall(self) -> list[tuple[str]]:
        return self.schema_rows


class _FakeConnection:
    def __init__(self, schema_rows: list[tuple[str]]) -> None:
        self.cursor_instance = _FakeCursor(schema_rows)

    def __enter__(self) -> "_FakeConnection":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def cursor(self) -> _FakeCursor:
        return self.cursor_instance


def test_cleanup_test_schemas_only_drops_generated_names() -> None:
    connection = _FakeConnection(
        [
            ("t_0123456789ab",),
            ("t_0123456789ab_alice",),
            ("auth_0123456789",),
        ]
    )
    received: list[tuple[str, bool]] = []

    def connect_factory(dsn: str, *, autocommit: bool) -> _FakeConnection:
        received.append((dsn, autocommit))
        return connection

    conftest._cleanup_test_schemas(
        dsn="postgresql://test",
        schema_names=("t_0123456789ab", "auth_0123456789"),
        connect_factory=connect_factory,
    )

    assert received == [("postgresql://test", True)]
    assert connection.cursor_instance.queries[-3:] == [
        ('DROP SCHEMA IF EXISTS "t_0123456789ab_alice" CASCADE', None),
        ('DROP SCHEMA IF EXISTS "t_0123456789ab" CASCADE', None),
        ('DROP SCHEMA IF EXISTS "auth_0123456789" CASCADE', None),
    ]


@pytest.mark.parametrize("schema", ("public", "admin", "t_invalid", "auth_bad"))
def test_cleanup_test_schemas_refuses_non_test_schema(schema: str) -> None:
    with pytest.raises(RuntimeError, match="schema de teste inválido"):
        conftest._cleanup_test_schemas(
            dsn="postgresql://test",
            schema_names=(schema,),
            connect_factory=lambda *_args, **_kwargs: _FakeConnection([]),
        )
