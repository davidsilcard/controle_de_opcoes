import sqlite3
import sys
from pathlib import Path

import pytest

from opcoes import cli
from opcoes.db_backup import create_sqlite_backup, read_backup_manifest, restore_sqlite_backup


def _create_sqlite(path: Path, *, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.execute("DROP TABLE IF EXISTS sample")
        conn.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY, name TEXT)")
        conn.execute("INSERT INTO sample (id, name) VALUES (1, ?)", (value,))
        conn.commit()
    finally:
        conn.close()


def _read_sample_value(path: Path) -> str:
    conn = sqlite3.connect(path)
    try:
        row = conn.execute("SELECT name FROM sample WHERE id = 1").fetchone()
        return str(row[0]) if row else ""
    finally:
        conn.close()


def test_create_backup_and_restore_roundtrip(tmp_path: Path) -> None:
    source_dir = tmp_path / "src"
    main = source_dir / "opcoes_snapshots.db"
    iv = source_dir / "iv_history.db"
    flow = source_dir / "flow_history.db"
    _create_sqlite(main, value="main-v1")
    _create_sqlite(iv, value="iv-v1")
    _create_sqlite(flow, value="flow-v1")

    report = create_sqlite_backup(
        username="admin",
        source_dir=source_dir,
        backup_root=tmp_path / "backups",
        include_aux=True,
    )
    backup_dir = Path(report["backup_dir"])
    assert backup_dir.exists()
    manifest = read_backup_manifest(backup_dir=backup_dir)
    assert manifest["username"] == "admin"
    assert len(manifest["files"]) == 3

    _create_sqlite(main, value="main-v2")
    _create_sqlite(iv, value="iv-v2")
    _create_sqlite(flow, value="flow-v2")

    restore_report = restore_sqlite_backup(
        backup_dir=backup_dir,
        username="admin",
        target_dir=source_dir,
        include_aux=True,
        create_restore_point=True,
        dry_run=False,
    )
    assert any(item.get("restore_point") for item in restore_report["files"])
    assert _read_sample_value(main) == "main-v1"
    assert _read_sample_value(iv) == "iv-v1"
    assert _read_sample_value(flow) == "flow-v1"


def test_create_backup_dry_run_does_not_write(tmp_path: Path) -> None:
    source_dir = tmp_path / "src"
    main = source_dir / "opcoes_snapshots.db"
    _create_sqlite(main, value="main-v1")

    report = create_sqlite_backup(
        username="admin",
        source_dir=source_dir,
        backup_root=tmp_path / "backups",
        include_aux=False,
        dry_run=True,
    )
    backup_dir = Path(report["backup_dir"])
    assert not backup_dir.exists()
    assert report["dry_run"] is True
    assert report["files"][0]["label"] == "main"


def test_restore_fails_without_manifest(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        restore_sqlite_backup(
            backup_dir=tmp_path / "missing",
            username="admin",
        )


def test_cli_db_backup_dry_run(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "load_dotenv_once", lambda: None)
    monkeypatch.setattr(
        cli,
        "create_sqlite_backup",
        lambda **kwargs: {
            "dry_run": True,
            "backup_dir": "/tmp/backup",
            "manifest_path": "/tmp/backup/manifest.json",
            "files": [
                {
                    "label": "main",
                    "source_path": "/src/opcoes_snapshots.db",
                    "exists": True,
                    "copied": False,
                    "size_bytes": 123,
                }
            ],
        },
    )
    monkeypatch.setattr(sys, "argv", ["opcoes", "db", "backup", "--dry-run"])

    cli.main()
    out = capsys.readouterr().out
    assert "Backup dir:" in out
    assert "Dry-run concluído" in out


def test_cli_db_rollback_dry_run(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "load_dotenv_once", lambda: None)
    monkeypatch.setattr(
        cli,
        "restore_sqlite_backup",
        lambda **kwargs: {
            "dry_run": True,
            "backup_dir": "/tmp/backup",
            "target_dir": "/dst",
            "files": [
                {
                    "label": "main",
                    "status": "planned",
                    "backup_file": "/tmp/backup/sqlite/opcoes_snapshots.db",
                    "target_file": "/dst/opcoes_snapshots.db",
                    "restore_point": None,
                }
            ],
        },
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["opcoes", "db", "rollback", "--backup-dir", "/tmp/backup", "--dry-run"],
    )

    cli.main()
    out = capsys.readouterr().out
    assert "Backup origem:" in out
    assert "Dry-run concluído" in out
