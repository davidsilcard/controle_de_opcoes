from __future__ import annotations

import datetime as dt
import os
import re
import secrets
from dataclasses import dataclass
from typing import List, Optional

from werkzeug.security import check_password_hash, generate_password_hash

from .config import reset_pg_schema_override, set_pg_schema_override
from .db import open_db

DEFAULT_AUTH_SCHEMA = "auth"
_AUTH_TABLE = "web_users"
_USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{2,63}$")
_TEMP_PASSWORD_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789"


@dataclass(frozen=True)
class AuthenticatedUser:
    username: str
    must_change_password: bool


@dataclass(frozen=True)
class AuthenticationResult:
    user: Optional[AuthenticatedUser]
    error_code: str | None = None


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


def _temp_password_ttl_seconds() -> int:
    raw = (os.getenv("OPCOES_TEMP_PASSWORD_TTL_SECONDS") or "10800").strip()
    try:
        value = int(raw)
    except ValueError:
        value = 10800
    return max(value, 60)


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
            must_change_password BOOLEAN NOT NULL DEFAULT FALSE,
            temp_password_issued_at TIMESTAMPTZ NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    conn.execute(
        f"""
        ALTER TABLE {_AUTH_TABLE}
        ADD COLUMN IF NOT EXISTS must_change_password BOOLEAN NOT NULL DEFAULT FALSE
        """
    )
    conn.execute(
        f"""
        ALTER TABLE {_AUTH_TABLE}
        ADD COLUMN IF NOT EXISTS temp_password_issued_at TIMESTAMPTZ NULL
        """
    )
    conn.commit()


def create_user(
    *,
    username: str,
    password: str,
    replace: bool = False,
    must_change_password: bool = False,
    temp_password_issued_at: Optional[dt.datetime] = None,
) -> bool:
    safe_username = validate_username(username)
    safe_password = validate_password(password)
    now = dt.datetime.now(dt.UTC)
    pwd_hash = generate_password_hash(safe_password)
    temp_issued_at = temp_password_issued_at if must_change_password else None

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
                SET password_hash = %s,
                    is_active = TRUE,
                    must_change_password = %s,
                    temp_password_issued_at = %s,
                    updated_at = %s
                WHERE username = %s
                """,
                (pwd_hash, bool(must_change_password), temp_issued_at, now, safe_username),
            )
            conn.commit()
            return True

        conn.execute(
            f"""
            INSERT INTO {_AUTH_TABLE} (
                username,
                password_hash,
                is_active,
                must_change_password,
                temp_password_issued_at,
                created_at,
                updated_at
            )
            VALUES (%s, %s, TRUE, %s, %s, %s, %s)
            """,
            (
                safe_username,
                pwd_hash,
                bool(must_change_password),
                temp_issued_at,
                now,
                now,
            ),
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


def _load_user_row(*, username: str) -> Optional[object]:
    safe_username = normalize_username(username)
    if not safe_username:
        return None

    conn = _connect()
    try:
        return conn.execute(
            f"""
            SELECT username, password_hash, is_active, must_change_password, temp_password_issued_at
            FROM {_AUTH_TABLE}
            WHERE username = %s
            LIMIT 1
            """,
            (safe_username,),
        ).fetchone()
    finally:
        conn.close()


def authenticate_login(*, username: str, password: str) -> AuthenticationResult:
    row = _load_user_row(username=username)
    if not row:
        return AuthenticationResult(user=None, error_code="invalid_credentials")
    if not bool(row["is_active"]):
        return AuthenticationResult(user=None, error_code="inactive_user")
    if not check_password_hash(str(row["password_hash"]), str(password or "")):
        return AuthenticationResult(user=None, error_code="invalid_credentials")

    must_change_password = bool(row.get("must_change_password"))
    issued_at = row.get("temp_password_issued_at")
    if must_change_password and issued_at is not None:
        if getattr(issued_at, "tzinfo", None) is None:
            issued_at = issued_at.replace(tzinfo=dt.UTC)
        age_seconds = (dt.datetime.now(dt.UTC) - issued_at).total_seconds()
        if age_seconds > _temp_password_ttl_seconds():
            return AuthenticationResult(user=None, error_code="temp_password_expired")

    return AuthenticationResult(
        user=AuthenticatedUser(
            username=str(row["username"]),
            must_change_password=must_change_password,
        ),
        error_code=None,
    )


def authenticate_user(*, username: str, password: str) -> bool:
    return authenticate_login(username=username, password=password).user is not None


def issue_temporary_password(*, username: str, replace: bool = False, length: int = 12) -> str:
    safe_username = validate_username(username)
    size = max(int(length or 0), 10)
    password = "".join(secrets.choice(_TEMP_PASSWORD_ALPHABET) for _ in range(size))
    created = create_user(
        username=safe_username,
        password=password,
        replace=replace,
        must_change_password=True,
        temp_password_issued_at=dt.datetime.now(dt.UTC),
    )
    if not created:
        raise ValueError(
            f"Usuário '{safe_username}' já existe. Use replace=True para emitir nova senha temporária."
        )
    return password


def change_password(*, username: str, password: str) -> bool:
    safe_username = validate_username(username)
    safe_password = validate_password(password)
    now = dt.datetime.now(dt.UTC)
    pwd_hash = generate_password_hash(safe_password)

    conn = _connect()
    try:
        existing = conn.execute(
            f"SELECT id FROM {_AUTH_TABLE} WHERE username = %s LIMIT 1",
            (safe_username,),
        ).fetchone()
        if not existing:
            return False
        conn.execute(
            f"""
            UPDATE {_AUTH_TABLE}
            SET password_hash = %s,
                is_active = TRUE,
                must_change_password = FALSE,
                temp_password_issued_at = NULL,
                updated_at = %s
            WHERE username = %s
            """,
            (pwd_hash, now, safe_username),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def ensure_bootstrap_user_from_env() -> bool:
    username = os.getenv("OPCOES_ADMIN_USER")
    password = os.getenv("OPCOES_ADMIN_PASSWORD")
    if not username or not password:
        return False
    replace = os.getenv("OPCOES_ADMIN_REPLACE_PASSWORD", "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
        "sim",
    }
    return create_user(username=username, password=password, replace=replace)


__all__ = [
    "AuthenticatedUser",
    "AuthenticationResult",
    "authenticate_login",
    "authenticate_user",
    "change_password",
    "create_user",
    "ensure_bootstrap_user_from_env",
    "issue_temporary_password",
    "list_users",
    "normalize_username",
    "validate_password",
    "validate_username",
]
