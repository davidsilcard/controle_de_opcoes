from __future__ import annotations

import pytest

from opcoes.report import generate_report


class _FailingPostgresConnection:
    backend = "postgres"

    def execute(self, _query, _params=()):
        raise RuntimeError("postgres query failed")

    def close(self) -> None:
        return None


def test_report_fails_fast_when_postgres_connection_fails(monkeypatch) -> None:
    monkeypatch.setattr(
        "opcoes.report._connect_postgres",
        lambda: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    with pytest.raises(RuntimeError, match="boom"):
        generate_report(min_score=8, limit=10, recurring_days=30, recurring_limit=10)


def test_report_fails_fast_when_postgres_query_fails(monkeypatch) -> None:
    monkeypatch.setattr("opcoes.report._connect_postgres", lambda: _FailingPostgresConnection())

    with pytest.raises(RuntimeError, match="postgres query failed"):
        generate_report(min_score=8, limit=10, recurring_days=30, recurring_limit=10)
