from __future__ import annotations

from pathlib import Path

import pytest

from opcoes.auth import migrate_legacy_user_data, user_db_path


def _write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def test_migrate_legacy_user_data_copies_main_and_histories(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("OPCOES_USERS_DB_DIR", str(tmp_path / "users"))

    source_dir = tmp_path / "legacy"
    source_main = source_dir / "opcoes_snapshots.db"
    source_iv = source_dir / "iv_history.db"
    source_flow = source_dir / "flow_history.db"
    _write(source_main, b"main-db")
    _write(source_iv, b"iv-db")
    _write(source_flow, b"flow-db")

    result = migrate_legacy_user_data(username="admin", source_db=source_main)

    admin_db = user_db_path("admin")
    admin_dir = admin_db.parent
    assert admin_db.read_bytes() == b"main-db"
    assert (admin_dir / "iv_history.db").read_bytes() == b"iv-db"
    assert (admin_dir / "flow_history.db").read_bytes() == b"flow-db"

    assert result["main"]["status"] == "copied"
    assert result["iv_history"]["status"] == "copied"
    assert result["flow_history"]["status"] == "copied"


def test_migrate_legacy_user_data_force_creates_backup(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("OPCOES_USERS_DB_DIR", str(tmp_path / "users"))

    source_dir = tmp_path / "legacy"
    source_main = source_dir / "opcoes_snapshots.db"
    _write(source_main, b"main-v1")

    migrate_legacy_user_data(username="admin", source_db=source_main)

    _write(source_main, b"main-v2")
    with pytest.raises(FileExistsError):
        migrate_legacy_user_data(username="admin", source_db=source_main, force=False)

    result = migrate_legacy_user_data(username="admin", source_db=source_main, force=True)
    assert result["main"]["status"] == "copied"
    backup = result["main"]["backup"]
    assert backup is not None
    backup_path = Path(backup)
    assert backup_path.exists()
    assert backup_path.read_bytes() == b"main-v1"
    assert user_db_path("admin").read_bytes() == b"main-v2"
