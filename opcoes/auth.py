from __future__ import annotations

import datetime as dt
import os
import re
import sqlite3
from pathlib import Path
from typing import List

from werkzeug.security import check_password_hash, generate_password_hash


DEFAULT_AUTH_DB_PATH = Path("data/auth.db")
DEFAULT_USERS_DB_DIR = Path("data/users")
_USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{2,63}$")


def get_auth_db_path() -> Path:
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


def _connect() -> sqlite3.Connection:
    path = get_auth_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    _ensure_tables(conn)
    return conn


def _ensure_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.commit()


def create_user(*, username: str, password: str, replace: bool = False) -> bool:
    safe_username = validate_username(username)
    safe_password = validate_password(password)
    now = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
    pwd_hash = generate_password_hash(safe_password)

    conn = _connect()
    try:
        existing = conn.execute("SELECT id FROM users WHERE username = ?", (safe_username,)).fetchone()
        if existing:
            if not replace:
                return False
            conn.execute(
                """
                UPDATE users
                SET password_hash = ?, is_active = 1, updated_at = ?
                WHERE username = ?
                """,
                (pwd_hash, now, safe_username),
            )
            conn.commit()
            return True

        conn.execute(
            """
            INSERT INTO users (username, password_hash, is_active, created_at, updated_at)
            VALUES (?, ?, 1, ?, ?)
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
        where = "WHERE is_active = 1" if active_only else ""
        rows = conn.execute(f"SELECT username FROM users {where} ORDER BY username ASC").fetchall()
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
            """
            SELECT password_hash, is_active
            FROM users
            WHERE username = ?
            LIMIT 1
            """,
            (safe_username,),
        ).fetchone()
    finally:
        conn.close()

    if not row:
        return False
    if int(row["is_active"] or 0) != 1:
        return False
    return check_password_hash(str(row["password_hash"]), str(password or ""))


def ensure_bootstrap_user_from_env() -> bool:
    username = os.getenv("OPCOES_ADMIN_USER")
    password = os.getenv("OPCOES_ADMIN_PASSWORD")
    if not username or not password:
        return False
    replace = os.getenv("OPCOES_ADMIN_REPLACE_PASSWORD", "0").strip().lower() in {"1", "true", "yes", "on", "sim"}
    return create_user(username=username, password=password, replace=replace)


__all__ = [
    "authenticate_user",
    "create_user",
    "ensure_bootstrap_user_from_env",
    "get_auth_db_path",
    "get_users_db_dir",
    "list_users",
    "normalize_username",
    "user_db_path",
    "validate_password",
    "validate_username",
]
