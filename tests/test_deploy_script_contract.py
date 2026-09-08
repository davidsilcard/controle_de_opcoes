from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_update_vps_serializes_concurrent_deploys() -> None:
    script = (ROOT / "deploy" / "scripts" / "update-vps.sh").read_text(encoding="utf-8")

    expected_lock = (
        'DEPLOY_LOCK_FILE="${OPCOES_DEPLOY_LOCK_FILE:-'
        '/tmp/controle_de_opcoes-deploy.lock}"'
    )
    assert expected_lock in script
    assert 'exec 9>"$DEPLOY_LOCK_FILE"' in script
    assert "flock -n 9" in script
    assert "Outro deploy já está em execução." in script
