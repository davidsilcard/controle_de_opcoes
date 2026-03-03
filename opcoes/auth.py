from __future__ import annotations

import datetime as dt
import os
import re
from typing import List

from werkzeug.security import check_password_hash, generate_password_hash

from .config import reset_pg_schema_override, set_pg_schema_override
from .db import open_db

DEFAULT_AUTH_SCHEMA = "auth"
_AUTH_TABLE = "web_users"
_USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{2,63}$")


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
    "list_users",
    "normalize_username",
    "validate_password",
    "validate_username",
]
