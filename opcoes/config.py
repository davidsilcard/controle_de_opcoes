from __future__ import annotations

import os
import re
from contextvars import ContextVar, Token
from pathlib import Path

# Caminho padrão do banco. Pode ser sobrescrito via variável OPCOES_DB_PATH.
DEFAULT_DB_PATH = Path("data/opcoes_snapshots.db")
_db_path_override: ContextVar[Path | None] = ContextVar("opcoes_db_path_override", default=None)
_pg_schema_override: ContextVar[str | None] = ContextVar(
    "opcoes_pg_schema_override", default=None
)


def set_db_path_override(path: Path | str) -> Token[Path | None]:
    """Define override de caminho do DB para o contexto atual."""

    return _db_path_override.set(Path(path).expanduser())


def reset_db_path_override(token: Token[Path | None]) -> None:
    """Restaura override anterior de caminho do DB para o contexto atual."""

    _db_path_override.reset(token)


def get_db_path() -> Path:
    """Retorna o caminho do banco, permitindo override por env."""

    override_ctx = _db_path_override.get()
    if override_ctx is not None:
        path = override_ctx
    else:
        override = os.getenv("OPCOES_DB_PATH")
        if override:
            path = Path(override).expanduser()
        else:
            path = DEFAULT_DB_PATH

    # Suporte a bancos por usuário: cria diretório pai ao resolver o caminho.
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def get_data_backend() -> str:
    raw = os.getenv("OPCOES_DB_BACKEND", "sqlite").strip().lower()
    if raw in {"postgres", "postgresql", "pg"}:
        return "postgres"
    return "sqlite"


def _sanitize_pg_schema(value: str) -> str:
    text = (value or "").strip().lower()
    text = re.sub(r"[^a-z0-9_]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    if not text:
        return "public"
    if text[0].isdigit():
        text = f"u_{text}"
    return text[:63]


def set_pg_schema_override(schema: str) -> Token[str | None]:
    safe = _sanitize_pg_schema(schema)
    return _pg_schema_override.set(safe)


def reset_pg_schema_override(token: Token[str | None]) -> None:
    _pg_schema_override.reset(token)


def get_postgres_schema() -> str:
    override_ctx = _pg_schema_override.get()
    if override_ctx:
        return _sanitize_pg_schema(override_ctx)
    env_value = os.getenv("OPCOES_PG_SCHEMA", "")
    if env_value.strip():
        return _sanitize_pg_schema(env_value)
    return "public"


__all__ = [
    "get_db_path",
    "get_data_backend",
    "get_postgres_schema",
    "DEFAULT_DB_PATH",
    "set_pg_schema_override",
    "reset_pg_schema_override",
    "set_db_path_override",
    "reset_db_path_override",
]
