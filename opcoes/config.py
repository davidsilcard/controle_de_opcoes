from __future__ import annotations

import os
from contextvars import ContextVar, Token
from pathlib import Path

# Caminho padrão do banco. Pode ser sobrescrito via variável OPCOES_DB_PATH.
DEFAULT_DB_PATH = Path("data/opcoes_snapshots.db")
_db_path_override: ContextVar[Path | None] = ContextVar("opcoes_db_path_override", default=None)


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
        return override_ctx

    override = os.getenv("OPCOES_DB_PATH")
    if override:
        return Path(override).expanduser()
    return DEFAULT_DB_PATH


__all__ = [
    "get_db_path",
    "DEFAULT_DB_PATH",
    "set_db_path_override",
    "reset_db_path_override",
]
