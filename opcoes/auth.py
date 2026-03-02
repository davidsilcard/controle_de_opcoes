from __future__ import annotations

import datetime as dt
import os
import re
import shutil
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional

from werkzeug.security import check_password_hash, generate_password_hash

from .config import reset_pg_schema_override, set_pg_schema_override
from .db import open_db

DEFAULT_AUTH_DB_PATH = Path("data/auth.db")
DEFAULT_USERS_DB_DIR = Path("data/users")
DEFAULT_AUTH_SCHEMA = "auth"
_AUTH_TABLE = "web_users"
_USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{2,63}$")


def get_auth_db_path() -> Path:
    override_legacy = os.getenv("OPCOES_AUTH_LEGACY_DB_PATH")
    if override_legacy:
        return Path(override_legacy).expanduser()
    override = os.getenv("OPCOES_AUTH_DB_PATH")
    if override:
        return Path(override).expanduser()
    return DEFAULT_AUTH_DB_PATH


def get_users_db_dir() -> Path:
    override = os.getenv("OPCOES_USERS_DB_DIR")
    if override:
        return Path(override).expanduser()
    return DEFAULT_USERS_DB_DIR


def normalize_username(value: str) -> str:
    return (value or "").strip().lower()


def validate_username(value: str) -> str:
    username = normalize_username(value)
    if not _USERNAME_RE.fullmatch(username):
        raise ValueError(
            "Usuário inválido. Use 3-64 chars com letras minúsculas, números, ponto, hífen ou underscore."
        )
    return username


def validate_password(value: str) -> str:
    password = str(value or "")
    if len(password) < 8:
        raise ValueError("Senha inválida. Use ao menos 8 caracteres.")
    return password


def user_db_path(username: str) -> Path:
    safe_username = validate_username(username)
    return get_users_db_dir() / safe_username / "opcoes_snapshots.db"


def _auth_schema() -> str:
    raw = os.getenv("OPCOES_AUTH_SCHEMA", DEFAULT_AUTH_SCHEMA)
    text = (raw or "").strip().lower()
    text = re.sub(r"[^a-z0-9_]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    if not text:
        return DEFAULT_AUTH_SCHEMA
    if text[0].isdigit():
        text = f"u_{text}"
    return text[:63]


def _connect() -> object:
    # Autenticação roda sempre no schema dedicado de auth, sem depender do schema
    # operacional da sessão de usuário.
    token = set_pg_schema_override(_auth_schema())
    try:
        conn = open_db()
    finally:
        reset_pg_schema_override(token)
    _ensure_tables(conn)
    return conn


def _ensure_tables(conn: object) -> None:
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_AUTH_TABLE} (
            id BIGSERIAL PRIMARY KEY,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    conn.commit()


def _coerce_timestamp(value: object, fallback: dt.datetime) -> dt.datetime:
    if isinstance(value, dt.datetime):
        parsed = value
    else:
        text = str(value or "").strip()
        if not text:
            return fallback
        norm = text.replace("Z", "+00:00")
        try:
            parsed = dt.datetime.fromisoformat(norm)
        except ValueError:
            return fallback
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=dt.timezone.utc)
    return parsed


def create_user(*, username: str, password: str, replace: bool = False) -> bool:
    safe_username = validate_username(username)
    safe_password = validate_password(password)
    now = dt.datetime.now(dt.UTC)
    pwd_hash = generate_password_hash(safe_password)

    conn = _connect()
    try:
        existing = conn.execute(
            f"SELECT id FROM {_AUTH_TABLE} WHERE username = %s",
            (safe_username,),
        ).fetchone()
        if existing:
            if not replace:
                return False
            conn.execute(
                f"""
                UPDATE {_AUTH_TABLE}
                SET password_hash = %s, is_active = TRUE, updated_at = %s
                WHERE username = %s
                """,
                (pwd_hash, now, safe_username),
            )
            conn.commit()
            return True

        conn.execute(
            f"""
            INSERT INTO {_AUTH_TABLE} (username, password_hash, is_active, created_at, updated_at)
            VALUES (%s, %s, TRUE, %s, %s)
            """,
            (safe_username, pwd_hash, now, now),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def list_users(*, active_only: bool = True) -> List[str]:
    conn = _connect()
    try:
        where = "WHERE is_active = TRUE" if active_only else ""
        rows = conn.execute(
            f"SELECT username FROM {_AUTH_TABLE} {where} ORDER BY username ASC"
        ).fetchall()
        return [str(r["username"]) for r in rows]
    finally:
        conn.close()


def authenticate_user(*, username: str, password: str) -> bool:
    safe_username = normalize_username(username)
    if not safe_username:
        return False

    conn = _connect()
    try:
        row = conn.execute(
            f"""
            SELECT password_hash, is_active
            FROM {_AUTH_TABLE}
            WHERE username = %s
            LIMIT 1
            """,
            (safe_username,),
        ).fetchone()
    finally:
        conn.close()

    if not row:
        return False
    if not bool(row["is_active"]):
        return False
    return check_password_hash(str(row["password_hash"]), str(password or ""))


def migrate_auth_from_legacy_sqlite(
    *,
    source_db: Optional[Path] = None,
    replace: bool = False,
) -> Dict[str, object]:
    source = Path(source_db).expanduser() if source_db is not None else get_auth_db_path()
    if not source.exists():
        return {
            "status": "missing_source",
            "source": str(source),
            "total": 0,
            "inserted": 0,
            "updated": 0,
            "skipped_existing": 0,
            "skipped_invalid": 0,
        }

    src = sqlite3.connect(source)
    src.row_factory = sqlite3.Row
    try:
        has_table = src.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='users' LIMIT 1"
        ).fetchone()
        if not has_table:
            return {
                "status": "missing_users_table",
                "source": str(source),
                "total": 0,
                "inserted": 0,
                "updated": 0,
                "skipped_existing": 0,
                "skipped_invalid": 0,
            }
        rows = src.execute(
            """
            SELECT username, password_hash, is_active, created_at, updated_at
            FROM users
            ORDER BY id ASC
            """
        ).fetchall()
    finally:
        src.close()

    now = dt.datetime.now(dt.UTC)
    inserted = 0
    updated = 0
    skipped_existing = 0
    skipped_invalid = 0

    conn = _connect()
    try:
        for row in rows:
            raw_username = normalize_username(str(row["username"] or ""))
            pwd_hash = str(row["password_hash"] or "").strip()
            if not raw_username or not pwd_hash:
                skipped_invalid += 1
                continue
            try:
                safe_username = validate_username(raw_username)
            except ValueError:
                skipped_invalid += 1
                continue

            is_active = int(row["is_active"] or 0) == 1
            created_at = _coerce_timestamp(row["created_at"], fallback=now)
            updated_at = _coerce_timestamp(row["updated_at"], fallback=created_at)
            existing = conn.execute(
                f"SELECT id FROM {_AUTH_TABLE} WHERE username = %s LIMIT 1",
                (safe_username,),
            ).fetchone()
            if existing:
                if not replace:
                    skipped_existing += 1
                    continue
                conn.execute(
                    f"""
                    UPDATE {_AUTH_TABLE}
                    SET password_hash = %s, is_active = %s, updated_at = %s
                    WHERE username = %s
                    """,
                    (pwd_hash, is_active, updated_at, safe_username),
                )
                updated += 1
                continue

            conn.execute(
                f"""
                INSERT INTO {_AUTH_TABLE}
                (username, password_hash, is_active, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (safe_username, pwd_hash, is_active, created_at, updated_at),
            )
            inserted += 1
        conn.commit()
    finally:
        conn.close()

    return {
        "status": "ok",
        "source": str(source),
        "total": int(len(rows)),
        "inserted": int(inserted),
        "updated": int(updated),
        "skipped_existing": int(skipped_existing),
        "skipped_invalid": int(skipped_invalid),
    }


def ensure_bootstrap_user_from_env() -> bool:
    username = os.getenv("OPCOES_ADMIN_USER")
    password = os.getenv("OPCOES_ADMIN_PASSWORD")
    if not username or not password:
        return False
    replace = os.getenv("OPCOES_ADMIN_REPLACE_PASSWORD", "0").strip().lower() in {"1", "true", "yes", "on", "sim"}
    return create_user(username=username, password=password, replace=replace)


def _default_legacy_sources(source_db: Optional[Path]) -> tuple[Path, Path, Path]:
    main = Path(source_db).expanduser() if source_db is not None else Path("data/opcoes_snapshots.db")
    base = main.parent
    return main, base / "iv_history.db", base / "flow_history.db"


def _copy_with_optional_backup(
    *,
    src: Path,
    dst: Path,
    force: bool,
    keep_backup: bool,
) -> Dict[str, Optional[str]]:
    src = src.expanduser()
    dst = dst.expanduser()
    dst.parent.mkdir(parents=True, exist_ok=True)

    if not src.exists():
        return {"status": "missing_source", "src": str(src), "dst": str(dst), "backup": None}

    if src.resolve() == dst.resolve():
        return {"status": "same_path", "src": str(src), "dst": str(dst), "backup": None}

    backup_path: Optional[Path] = None
    if dst.exists() and dst.stat().st_size > 0:
        if not force:
            raise FileExistsError(
                f"Destino já possui dados: {dst}. Use force=True para sobrescrever."
            )
        if keep_backup:
            stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%d-%H%M%S")
            backup_path = dst.with_suffix(f"{dst.suffix}.backup-{stamp}")
            shutil.copy2(dst, backup_path)

    shutil.copy2(src, dst)
    return {
        "status": "copied",
        "src": str(src),
        "dst": str(dst),
        "backup": str(backup_path) if backup_path else None,
    }


def migrate_legacy_user_data(
    *,
    username: str,
    source_db: Optional[Path] = None,
    source_iv_db: Optional[Path] = None,
    source_flow_db: Optional[Path] = None,
    force: bool = False,
    keep_backup: bool = True,
) -> Dict[str, Dict[str, Optional[str]]]:
    """
    Migra dados legados (single-user) para o contexto de um usuário.

    Copia:
    - banco principal (opcoes_snapshots.db)
    - iv_history.db
    - flow_history.db
    """

    safe_username = validate_username(username)
    src_main_default, src_iv_default, src_flow_default = _default_legacy_sources(source_db)
    src_main = src_main_default
    src_iv = Path(source_iv_db).expanduser() if source_iv_db is not None else src_iv_default
    src_flow = Path(source_flow_db).expanduser() if source_flow_db is not None else src_flow_default

    dst_main = user_db_path(safe_username)
    dst_base = dst_main.parent
    dst_iv = dst_base / "iv_history.db"
    dst_flow = dst_base / "flow_history.db"

    results = {
        "main": _copy_with_optional_backup(src=src_main, dst=dst_main, force=force, keep_backup=keep_backup),
        "iv_history": _copy_with_optional_backup(src=src_iv, dst=dst_iv, force=force, keep_backup=keep_backup),
        "flow_history": _copy_with_optional_backup(src=src_flow, dst=dst_flow, force=force, keep_backup=keep_backup),
    }
    return results


__all__ = [
    "authenticate_user",
    "create_user",
    "ensure_bootstrap_user_from_env",
    "get_auth_db_path",
    "get_users_db_dir",
    "list_users",
    "migrate_auth_from_legacy_sqlite",
    "migrate_legacy_user_data",
    "normalize_username",
    "user_db_path",
    "validate_password",
    "validate_username",
]
