from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_ci_runs_postgres_tests_and_docker_smoke() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )

    assert "image: postgres:16" in workflow
    assert "DATABASE_URL: postgresql://opcoes:opcoes@localhost:5432/opcoes" in workflow
    assert "uv run pytest -q -ra" in workflow
    assert "A suíte PostgreSQL foi ignorada indevidamente." in workflow
    assert "git diff --diff-filter=A --name-only" in workflow
    assert "docker build --tag" in workflow
    assert "curl --fail --silent --show-error --head http://127.0.0.1:8000/login" in workflow
