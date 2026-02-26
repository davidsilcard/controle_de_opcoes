from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional

_LOADED = False
_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _parse_env_line(line: str) -> tuple[str, str] | None:
    text = line.strip()
    if not text or text.startswith("#"):
        return None
    if text.startswith("export "):
        text = text[len("export ") :].strip()
    if "=" not in text:
        return None
    key, raw_value = text.split("=", 1)
    key = key.strip()
    if not _KEY_RE.fullmatch(key):
        return None
    value = raw_value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    return key, value


def _load_env_file(path: Path) -> None:
    for line in path.read_text(encoding="utf-8").splitlines():
        parsed = _parse_env_line(line)
        if not parsed:
            continue
        key, value = parsed
        if key not in os.environ:
            os.environ[key] = value


def load_dotenv_once(path: Optional[Path] = None) -> Optional[Path]:
    global _LOADED
    if _LOADED:
        return None
    _LOADED = True

    candidates: list[Path] = []
    if path is not None:
        candidates.append(Path(path).expanduser())
    else:
        cwd_env = Path.cwd() / ".env"
        candidates.append(cwd_env)
        project_env = Path(__file__).resolve().parents[1] / ".env"
        if project_env != cwd_env:
            candidates.append(project_env)

    for candidate in candidates:
        if candidate.is_file():
            _load_env_file(candidate)
            return candidate
    return None


__all__ = ["load_dotenv_once"]
