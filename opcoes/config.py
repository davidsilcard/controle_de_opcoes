from __future__ import annotations

import os
import re
from contextvars import ContextVar, Token

_pg_schema_override: ContextVar[str | None] = ContextVar(
    "opcoes_pg_schema_override", default=None
)


def get_data_backend() -> str:
    # Runtime consolidado: operação oficial apenas em PostgreSQL.
    return "postgres"


def is_postgres_strict_mode() -> bool:
    # Modo estrito permanente para evitar fallback e divergência de histórico.
    return True


def sanitize_pg_schema_name(value: str) -> str:
    text = (value or "").strip().lower()
    text = re.sub(r"[^a-z0-9_]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    if not text:
        return "public"
    if text[0].isdigit():
        text = f"u_{text}"
    return text[:63]


def set_pg_schema_override(schema: str) -> Token[str | None]:
    safe = sanitize_pg_schema_name(schema)
    return _pg_schema_override.set(safe)


def reset_pg_schema_override(token: Token[str | None]) -> None:
    _pg_schema_override.reset(token)


def get_postgres_schema() -> str:
    override_ctx = _pg_schema_override.get()
    if override_ctx:
        return sanitize_pg_schema_name(override_ctx)
    env_value = os.getenv("OPCOES_PG_SCHEMA", "")
    if env_value.strip():
        return sanitize_pg_schema_name(env_value)
    return "public"


def get_postgres_shared_schema() -> str:
    shared_value = os.getenv("OPCOES_SHARED_SCHEMA", "")
    if shared_value.strip():
        return sanitize_pg_schema_name(shared_value)
    automation_value = os.getenv("OPCOES_AUTOMATION_SCHEMA", "")
    if automation_value.strip():
        return sanitize_pg_schema_name(automation_value)
    env_value = os.getenv("OPCOES_PG_SCHEMA", "")
    if env_value.strip():
        return sanitize_pg_schema_name(env_value)
    return "public"


__all__ = [
    "get_data_backend",
    "is_postgres_strict_mode",
    "get_postgres_schema",
    "get_postgres_shared_schema",
    "set_pg_schema_override",
    "reset_pg_schema_override",
    "sanitize_pg_schema_name",
]
