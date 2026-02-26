from __future__ import annotations

import datetime as dt
import json
import re
import shutil
from pathlib import Path
from typing import Optional

from .auth import user_db_path
from .db_migration import resolve_user_source_databases

_BACKUP_VERSION = 1
_LABEL_TO_FILENAME = {
    "main": "opcoes_snapshots.db",
    "iv_history": "iv_history.db",
    "flow_history": "flow_history.db",
}


def _utc_stamp() -> str:
    return dt.datetime.now(dt.UTC).strftime("%Y%m%d-%H%M%S")


def _safe_slug(value: str) -> str:
    text = (value or "").strip().lower()
    text = re.sub(r"[^a-z0-9_-]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text or "user"


def _default_backup_root() -> Path:
    return Path("data/backups/sqlite")


def _default_target_dir_for_user(username: str) -> Path:
    return user_db_path(username).parent


def create_sqlite_backup(
    *,
    username: str,
    backup_root: Optional[Path] = None,
    source_dir: Optional[Path] = None,
    source_main: Optional[Path] = None,
    source_iv: Optional[Path] = None,
    source_flow: Optional[Path] = None,
    include_aux: bool = True,
    dry_run: bool = False,
) -> dict:
    resolved_backup_root = (
        Path(backup_root).expanduser() if backup_root is not None else _default_backup_root()
    )
    sources = resolve_user_source_databases(
        username=username,
        source_dir=source_dir,
        source_main=source_main,
        source_iv=source_iv,
        source_flow=source_flow,
        include_aux=include_aux,
    )

    for src in sources:
        if src.required and not src.path.exists():
            raise FileNotFoundError(
                f"Fonte obrigatória não encontrada para '{src.label}': {src.path}"
            )

    backup_dir = resolved_backup_root / f"{_utc_stamp()}__{_safe_slug(username)}"
    files: list[dict] = []

    if not dry_run:
        backup_dir.mkdir(parents=True, exist_ok=False)

    for src in sources:
        filename = _LABEL_TO_FILENAME.get(src.label, src.path.name)
        relative_backup_path = Path("sqlite") / filename
        dst = backup_dir / relative_backup_path
        exists = src.path.exists()
        size_bytes = src.path.stat().st_size if exists else 0
        copied = False

        if exists and not dry_run:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src.path, dst)
            copied = True

        files.append(
            {
                "label": src.label,
                "required": bool(src.required),
                "source_path": str(src.path),
                "backup_path": str(relative_backup_path),
                "exists": exists,
                "size_bytes": int(size_bytes),
                "copied": bool(copied),
            }
        )

    manifest = {
        "version": _BACKUP_VERSION,
        "created_at_utc": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "username": username,
        "backup_dir": str(backup_dir),
        "files": files,
    }

    manifest_path = backup_dir / "manifest.json"
    if not dry_run:
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=True, indent=2) + "\n",
            encoding="utf-8",
        )

    return {
        "dry_run": bool(dry_run),
        "backup_dir": str(backup_dir),
        "manifest_path": str(manifest_path),
        "files": files,
    }


def read_backup_manifest(*, backup_dir: Path) -> dict:
    resolved_dir = Path(backup_dir).expanduser()
    manifest_path = resolved_dir / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifesto não encontrado: {manifest_path}")
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    return data


def restore_sqlite_backup(
    *,
    backup_dir: Path,
    username: str,
    target_dir: Optional[Path] = None,
    include_aux: bool = True,
    create_restore_point: bool = True,
    dry_run: bool = False,
) -> dict:
    resolved_backup_dir = Path(backup_dir).expanduser()
    manifest = read_backup_manifest(backup_dir=resolved_backup_dir)
    files = list(manifest.get("files") or [])
    target_base = (
        Path(target_dir).expanduser()
        if target_dir is not None
        else _default_target_dir_for_user(username)
    )

    restored_files: list[dict] = []
    stamp = _utc_stamp()
    allowed_labels = {"main"} if not include_aux else {"main", "iv_history", "flow_history"}

    for item in files:
        label = str(item.get("label") or "").strip()
        if label not in allowed_labels:
            continue

        required = bool(item.get("required"))
        relative_backup_path = Path(str(item.get("backup_path") or ""))
        src = resolved_backup_dir / relative_backup_path
        if not src.exists():
            if required:
                raise FileNotFoundError(
                    f"Arquivo obrigatório ausente no backup ({label}): {src}"
                )
            restored_files.append(
                {
                    "label": label,
                    "status": "missing_optional_backup_file",
                    "backup_file": str(src),
                }
            )
            continue

        filename = _LABEL_TO_FILENAME.get(label) or src.name
        dst = target_base / filename
        restore_point = None

        if not dry_run:
            dst.parent.mkdir(parents=True, exist_ok=True)
            if dst.exists() and create_restore_point:
                restore_point = dst.with_name(f"{dst.name}.before-restore-{stamp}.bak")
                shutil.copy2(dst, restore_point)
            shutil.copy2(src, dst)

        restored_files.append(
            {
                "label": label,
                "status": "restored" if not dry_run else "planned",
                "backup_file": str(src),
                "target_file": str(dst),
                "restore_point": str(restore_point) if restore_point else None,
            }
        )

    return {
        "dry_run": bool(dry_run),
        "backup_dir": str(resolved_backup_dir),
        "target_dir": str(target_base),
        "files": restored_files,
    }


__all__ = [
    "create_sqlite_backup",
    "read_backup_manifest",
    "restore_sqlite_backup",
]
