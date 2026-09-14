from __future__ import annotations

import datetime as dt
import hashlib
import os
import re
import secrets
from dataclasses import dataclass
from typing import Any, List, Mapping, Optional

from werkzeug.security import check_password_hash, generate_password_hash

from .config import (
    reset_pg_schema_override,
    sanitize_pg_schema_name,
    set_pg_schema_override,
)
from .db import open_db
from .db_health import resolve_postgres_target
from .db_migrate import clone_postgres_schema

DEFAULT_AUTH_SCHEMA = "auth"
_AUTH_TABLE = "web_users"
_LOGIN_ATTEMPTS_TABLE = "web_login_attempts"
_USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{2,63}$")
_TEMP_PASSWORD_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789"


@dataclass(frozen=True)
class AuthenticatedUser:
    username: str
    must_change_password: bool
    app_schema: str


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
    raw = (os.getenv("OPCOES_AUTH_SCHEMA") or "").strip()
    if not raw:
        return DEFAULT_AUTH_SCHEMA
    return sanitize_pg_schema_name(raw)


def _temp_password_ttl_seconds() -> int:
    raw = (os.getenv("OPCOES_TEMP_PASSWORD_TTL_SECONDS") or "10800").strip()
    try:
        value = int(raw)
    except ValueError:
        value = 10800
    return max(value, 60)


def _normalize_app_schema(value: str | None) -> str | None:
    text = (value or "").strip()
    if not text:
        return None
    return sanitize_pg_schema_name(text)


def _legacy_app_schema(username: str) -> str:
    safe_username = validate_username(username)
    return sanitize_pg_schema_name(safe_username)


def _schema_hash_suffix(username: str) -> str:
    return hashlib.sha1(normalize_username(username).encode("utf-8")).hexdigest()[:8]


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
            app_schema TEXT NULL,
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
        ADD COLUMN IF NOT EXISTS app_schema TEXT NULL
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
    conn.execute(
        f"""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_web_users_app_schema_unique
        ON {_AUTH_TABLE} (app_schema)
        WHERE app_schema IS NOT NULL
        """
    )
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_LOGIN_ATTEMPTS_TABLE} (
            client_key TEXT PRIMARY KEY,
            failed_count INTEGER NOT NULL DEFAULT 0,
            first_failure_at TIMESTAMPTZ NOT NULL,
            blocked_until TIMESTAMPTZ NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    conn.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_web_login_attempts_blocked_until
        ON {_LOGIN_ATTEMPTS_TABLE} (blocked_until)
        """
    )
    conn.commit()


def _load_all_user_rows_conn(conn: object) -> list[Mapping[str, Any]]:
    return conn.execute(
        f"""
        SELECT username, app_schema
        FROM {_AUTH_TABLE}
        ORDER BY username ASC
        """
    ).fetchall()


def _load_user_row_conn(*, conn: object, username: str) -> Optional[Mapping[str, Any]]:
    safe_username = normalize_username(username)
    if not safe_username:
        return None
    return conn.execute(
        f"""
        SELECT username, password_hash, app_schema, is_active, must_change_password, temp_password_issued_at
        FROM {_AUTH_TABLE}
        WHERE username = %s
        LIMIT 1
        """,
        (safe_username,),
    ).fetchone()


def _schema_exists_conn(conn: object, schema_name: str) -> bool:
    row = conn.execute(
        """
        SELECT 1
        FROM information_schema.schemata
        WHERE schema_name = %s
        LIMIT 1
        """,
        (sanitize_pg_schema_name(schema_name),),
    ).fetchone()
    return row is not None


def _build_unique_app_schema(
    existing_schemas: set[str],
    *,
    username: str,
    preferred_schema: str,
) -> str:
    candidate = sanitize_pg_schema_name(preferred_schema)
    if candidate not in existing_schemas:
        return candidate

    suffix = _schema_hash_suffix(username)
    stem_limit = max(1, 63 - len(suffix) - 1)
    stem = candidate[:stem_limit]
    candidate = f"{stem}_{suffix}"
    if candidate not in existing_schemas:
        return candidate

    counter = 2
    while True:
        extra = f"_{counter}"
        stem_limit = max(1, 63 - len(suffix) - len(extra) - 1)
        stem = sanitize_pg_schema_name(preferred_schema)[:stem_limit]
        candidate = f"{stem}_{suffix}{extra}"
        if candidate not in existing_schemas:
            return candidate
        counter += 1


def _resolve_app_schema_for_write(
    conn: object,
    *,
    username: str,
    requested_schema: str | None,
    current_schema: str | None,
) -> str:
    safe_username = validate_username(username)
    current_schema = _normalize_app_schema(current_schema)
    if requested_schema is None:
        if current_schema:
            return current_schema
        rows = _load_all_user_rows_conn(conn)
        existing_schemas = {
            normalized
            for row in rows
            if (normalized := _normalize_app_schema(row.get("app_schema")))
        }
        return _build_unique_app_schema(
            existing_schemas,
            username=safe_username,
            preferred_schema=_legacy_app_schema(safe_username),
        )

    candidate = sanitize_pg_schema_name(requested_schema)
    row = conn.execute(
        f"""
        SELECT username
        FROM {_AUTH_TABLE}
        WHERE app_schema = %s
        LIMIT 1
        """,
        (candidate,),
    ).fetchone()
    owner = normalize_username((row or {}).get("username") or "")
    if owner and owner != safe_username:
        raise ValueError(
            f"Schema '{candidate}' já está em uso por outro usuário. Escolha outro valor em --target-schema."
        )
    return candidate


def _resolve_row_app_schema(
    conn: object,
    row: Mapping[str, Any],
    *,
    fail_on_collision: bool = True,
) -> str:
    stored = _normalize_app_schema(row.get("app_schema"))
    if stored:
        return stored

    username = validate_username(str(row.get("username") or ""))
    legacy_schema = _legacy_app_schema(username)
    if not fail_on_collision:
        return legacy_schema

    for other in _load_all_user_rows_conn(conn):
        other_username = normalize_username(str(other.get("username") or ""))
        if not other_username or other_username == username:
            continue
        other_schema = _normalize_app_schema(other.get("app_schema"))
        if other_schema == legacy_schema:
            raise RuntimeError(
                f"Usuário '{username}' compartilha o schema legado '{legacy_schema}' com outro cadastro. "
                "Execute `opcoes user migrate-schemas` para isolar os dados."
            )
        if (
            other_schema is None
            and _legacy_app_schema(other_username) == legacy_schema
        ):
            raise RuntimeError(
                f"Usuário '{username}' colide com outro cadastro no schema legado '{legacy_schema}'. "
                "Execute `opcoes user migrate-schemas` para isolar os dados."
            )
    return legacy_schema


def create_user(
    *,
    username: str,
    password: str,
    replace: bool = False,
    must_change_password: bool = False,
    temp_password_issued_at: Optional[dt.datetime] = None,
    app_schema: Optional[str] = None,
) -> bool:
    safe_username = validate_username(username)
    safe_password = validate_password(password)
    now = dt.datetime.now(dt.UTC)
    pwd_hash = generate_password_hash(safe_password)
    temp_issued_at = temp_password_issued_at if must_change_password else None

    conn = _connect()
    try:
        existing = conn.execute(
            f"SELECT id, app_schema FROM {_AUTH_TABLE} WHERE username = %s",
            (safe_username,),
        ).fetchone()
        current_schema = _normalize_app_schema((existing or {}).get("app_schema"))
        target_schema = _resolve_app_schema_for_write(
            conn,
            username=safe_username,
            requested_schema=app_schema,
            current_schema=current_schema,
        )
        if existing:
            if not replace:
                return False
            conn.execute(
                f"""
                UPDATE {_AUTH_TABLE}
                SET password_hash = %s,
                    app_schema = %s,
                    is_active = TRUE,
                    must_change_password = %s,
                    temp_password_issued_at = %s,
                    updated_at = %s
                WHERE username = %s
                """,
                (
                    pwd_hash,
                    target_schema,
                    bool(must_change_password),
                    temp_issued_at,
                    now,
                    safe_username,
                ),
            )
            conn.commit()
            return True

        conn.execute(
            f"""
            INSERT INTO {_AUTH_TABLE} (
                username,
                password_hash,
                app_schema,
                is_active,
                must_change_password,
                temp_password_issued_at,
                created_at,
                updated_at
            )
            VALUES (%s, %s, %s, TRUE, %s, %s, %s, %s)
            """,
            (
                safe_username,
                pwd_hash,
                target_schema,
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


def list_user_schema_mappings() -> List[dict[str, object]]:
    conn = _connect()
    try:
        rows = _load_all_user_rows_conn(conn)
        mappings: list[dict[str, object]] = []
        planned = {}
        existing_schemas = {
            normalized
            for row in rows
            if (normalized := _normalize_app_schema(row.get("app_schema")))
        }
        reserved = set(existing_schemas)
        for row in rows:
            username = validate_username(str(row.get("username") or ""))
            current_schema = _normalize_app_schema(row.get("app_schema"))
            legacy_schema = _legacy_app_schema(username)
            if current_schema:
                target_schema = current_schema
                action = "keep"
            else:
                target_schema = _build_unique_app_schema(
                    reserved,
                    username=username,
                    preferred_schema=legacy_schema,
                )
                reserved.add(target_schema)
                action = "assign_legacy" if target_schema == legacy_schema else "assign_unique"
            planned[username] = target_schema
            mappings.append(
                {
                    "username": username,
                    "app_schema": current_schema,
                    "planned_schema": target_schema,
                    "legacy_schema": legacy_schema,
                    "action": action,
                    "legacy_schema_exists": _schema_exists_conn(conn, legacy_schema),
                    "planned_schema_exists": _schema_exists_conn(conn, target_schema),
                }
            )
        return mappings
    finally:
        conn.close()


def migrate_user_app_schemas(
    *,
    dry_run: bool = False,
    clone_legacy_schema: bool = True,
) -> dict[str, object]:
    target, errors = resolve_postgres_target()
    if target is None:
        reasons = "; ".join(errors) if errors else "configuração ausente"
        raise RuntimeError(f"PostgreSQL não configurado: {reasons}")

    mappings = list_user_schema_mappings()
    pending = [item for item in mappings if item["action"] != "keep"]
    cloned: list[dict[str, str]] = []
    updated_users: list[dict[str, str]] = []

    if not dry_run and pending:
        conn = _connect()
        try:
            for item in pending:
                conn.execute(
                    f"UPDATE {_AUTH_TABLE} SET app_schema = %s, updated_at = %s WHERE username = %s",
                    (
                        str(item["planned_schema"]),
                        dt.datetime.now(dt.UTC),
                        str(item["username"]),
                    ),
                )
                updated_users.append(
                    {
                        "username": str(item["username"]),
                        "app_schema": str(item["planned_schema"]),
                    }
                )
            conn.commit()
        finally:
            conn.close()

    for item in pending:
        legacy_schema = str(item["legacy_schema"])
        target_schema = str(item["planned_schema"])
        needs_clone = (
            clone_legacy_schema
            and target_schema != legacy_schema
            and bool(item["legacy_schema_exists"])
            and not bool(item["planned_schema_exists"])
        )
        if not needs_clone:
            continue
        if dry_run:
            cloned.append(
                {
                    "source_schema": legacy_schema,
                    "target_schema": target_schema,
                }
            )
            continue
        clone_postgres_schema(
            dsn=target.dsn,
            source_schema=legacy_schema,
            target_schema=target_schema,
            truncate_target=True,
        )
        cloned.append(
            {
                "source_schema": legacy_schema,
                "target_schema": target_schema,
            }
        )

    return {
        "dry_run": dry_run,
        "mappings": mappings,
        "updated_users": updated_users,
        "cloned_schemas": cloned,
    }


def get_user_app_schema(
    username: str,
    *,
    fail_on_collision: bool = True,
) -> Optional[str]:
    conn = _connect()
    try:
        row = _load_user_row_conn(conn=conn, username=username)
        if not row:
            return None
        return _resolve_row_app_schema(
            conn,
            row,
            fail_on_collision=fail_on_collision,
        )
    finally:
        conn.close()


def _load_user_row(*, username: str) -> Optional[Mapping[str, Any]]:
    conn = _connect()
    try:
        return _load_user_row_conn(conn=conn, username=username)
    finally:
        conn.close()


def authenticate_login(*, username: str, password: str) -> AuthenticationResult:
    conn = _connect()
    try:
        row = _load_user_row_conn(conn=conn, username=username)
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

        try:
            app_schema = _resolve_row_app_schema(conn, row, fail_on_collision=True)
        except RuntimeError:
            return AuthenticationResult(user=None, error_code="schema_migration_required")

        return AuthenticationResult(
            user=AuthenticatedUser(
                username=str(row["username"]),
                must_change_password=must_change_password,
                app_schema=app_schema,
            ),
            error_code=None,
        )
    finally:
        conn.close()


def authenticate_user(*, username: str, password: str) -> bool:
    return authenticate_login(username=username, password=password).user is not None


def issue_temporary_password(
    *,
    username: str,
    replace: bool = False,
    length: int = 12,
    app_schema: Optional[str] = None,
) -> str:
    safe_username = validate_username(username)
    size = max(int(length or 0), 10)
    password = "".join(secrets.choice(_TEMP_PASSWORD_ALPHABET) for _ in range(size))
    created = create_user(
        username=safe_username,
        password=password,
        replace=replace,
        must_change_password=True,
        temp_password_issued_at=dt.datetime.now(dt.UTC),
        app_schema=app_schema,
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
            f"SELECT id, app_schema FROM {_AUTH_TABLE} WHERE username = %s LIMIT 1",
            (safe_username,),
        ).fetchone()
        if not existing:
            return False
        target_schema = _resolve_app_schema_for_write(
            conn,
            username=safe_username,
            requested_schema=None,
            current_schema=(existing or {}).get("app_schema"),
        )
        conn.execute(
            f"""
            UPDATE {_AUTH_TABLE}
            SET password_hash = %s,
                app_schema = %s,
                is_active = TRUE,
                must_change_password = FALSE,
                temp_password_issued_at = NULL,
                updated_at = %s
            WHERE username = %s
            """,
            (pwd_hash, target_schema, now, safe_username),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def _coerce_utc(value: dt.datetime | None) -> dt.datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=dt.UTC)
    return value.astimezone(dt.UTC)


def _prune_login_attempts(conn: object, *, now: dt.datetime, window_seconds: int) -> None:
    cutoff = now - dt.timedelta(seconds=max(int(window_seconds or 0), 60))
    conn.execute(
        f"""
        DELETE FROM {_LOGIN_ATTEMPTS_TABLE}
        WHERE first_failure_at <= %s
          AND (blocked_until IS NULL OR blocked_until <= %s)
        """,
        (cutoff, now),
    )


def get_login_block_remaining_seconds(
    *,
    client_key: str,
    window_seconds: int,
) -> int | None:
    safe_client_key = (client_key or "").strip() or "unknown"
    now = dt.datetime.now(dt.UTC)
    conn = _connect()
    try:
        _prune_login_attempts(conn, now=now, window_seconds=window_seconds)
        row = conn.execute(
            f"""
            SELECT blocked_until
            FROM {_LOGIN_ATTEMPTS_TABLE}
            WHERE client_key = %s
            LIMIT 1
            """,
            (safe_client_key,),
        ).fetchone()
        conn.commit()
        if not row:
            return None
        blocked_until = _coerce_utc(row.get("blocked_until"))
        if blocked_until is None or blocked_until <= now:
            return None
        return max(1, int((blocked_until - now).total_seconds() + 0.999))
    finally:
        conn.close()


def record_failed_login_attempt(
    *,
    client_key: str,
    window_seconds: int,
    block_seconds: int,
    max_attempts: int,
) -> int | None:
    safe_client_key = (client_key or "").strip() or "unknown"
    now = dt.datetime.now(dt.UTC)
    max_attempts = max(int(max_attempts or 0), 1)
    conn = _connect()
    try:
        _prune_login_attempts(conn, now=now, window_seconds=window_seconds)
        row = conn.execute(
            f"""
            SELECT failed_count, first_failure_at, blocked_until
            FROM {_LOGIN_ATTEMPTS_TABLE}
            WHERE client_key = %s
            LIMIT 1
            """,
            (safe_client_key,),
        ).fetchone()
        first_failure_at = _coerce_utc((row or {}).get("first_failure_at"))
        blocked_until = _coerce_utc((row or {}).get("blocked_until"))
        failed_count = int((row or {}).get("failed_count") or 0)

        if blocked_until is not None and blocked_until > now:
            conn.commit()
            return max(1, int((blocked_until - now).total_seconds() + 0.999))

        if (
            first_failure_at is None
            or (first_failure_at + dt.timedelta(seconds=window_seconds)) <= now
        ):
            failed_count = 1
            first_failure_at = now
            blocked_until = None
        else:
            failed_count += 1
            if failed_count >= max_attempts:
                failed_count = 0
                first_failure_at = now
                blocked_until = now + dt.timedelta(seconds=max(int(block_seconds or 0), 60))

        conn.execute(
            f"""
            INSERT INTO {_LOGIN_ATTEMPTS_TABLE} (
                client_key,
                failed_count,
                first_failure_at,
                blocked_until,
                updated_at
            )
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (client_key)
            DO UPDATE
               SET failed_count = EXCLUDED.failed_count,
                   first_failure_at = EXCLUDED.first_failure_at,
                   blocked_until = EXCLUDED.blocked_until,
                   updated_at = EXCLUDED.updated_at
            """,
            (
                safe_client_key,
                failed_count,
                first_failure_at,
                blocked_until,
                now,
            ),
        )
        conn.commit()

        if blocked_until is None or blocked_until <= now:
            return None
        return max(1, int((blocked_until - now).total_seconds() + 0.999))
    finally:
        conn.close()


def clear_login_rate_limit(*, client_key: str) -> None:
    safe_client_key = (client_key or "").strip() or "unknown"
    conn = _connect()
    try:
        conn.execute(
            f"DELETE FROM {_LOGIN_ATTEMPTS_TABLE} WHERE client_key = %s",
            (safe_client_key,),
        )
        conn.commit()
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
    "clear_login_rate_limit",
    "create_user",
    "ensure_bootstrap_user_from_env",
    "get_login_block_remaining_seconds",
    "get_user_app_schema",
    "issue_temporary_password",
    "list_user_schema_mappings",
    "list_users",
    "migrate_user_app_schemas",
    "normalize_username",
    "record_failed_login_attempt",
    "validate_password",
    "validate_username",
]
