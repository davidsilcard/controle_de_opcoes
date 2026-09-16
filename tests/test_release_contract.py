from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_release_script_requires_clean_main_ci_and_official_vps_deploy() -> None:
    script = (ROOT / "deploy/scripts/release.ps1").read_text(encoding="utf-8")

    assert "Invoke-Git status --porcelain" in script
    assert 'branch -ne "main"' in script
    assert "Invoke-Git fetch origin main" in script
    assert "Invoke-Git rev-parse origin/main" in script
    assert "gh run list --workflow tests.yml" in script
    assert "gh run watch $run.databaseId --exit-status" in script
    assert "bash deploy/scripts/update-vps.sh" in script
    assert "curl -fsSI --max-time 10 http://127.0.0.1:8000/login" in script
    assert "curl -fsS --max-time 10 http://127.0.0.1:8011/health" in script
    assert "docker compose" not in script
    assert "SkipCi" not in script
