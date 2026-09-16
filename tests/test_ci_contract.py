from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_ci_runs_the_suite_with_a_disposable_postgres_service() -> None:
    workflow = (ROOT / ".github" / "workflows" / "tests.yml").read_text(
        encoding="utf-8"
    )

    assert "postgres:16-alpine" in workflow
    assert "DATABASE_URL: postgresql://opcoes_test:opcoes_test@localhost:5432/opcoes_test" in workflow
    assert "uv run pytest -q" in workflow
    assert "OPCOES_SKIP_PRODUCTION_CHECKS" in workflow
