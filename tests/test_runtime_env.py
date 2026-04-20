from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from opcoes import runtime_env


def _make_env_test_dir(name: str) -> Path:
    base_dir = Path(__file__).resolve().parent / ".tmp_runtime_env"
    target = base_dir / f"{name}_{uuid.uuid4().hex}"
    target.mkdir(parents=True, exist_ok=True)
    return target


def test_load_dotenv_once_prefers_opcoes_app_env_file(monkeypatch) -> None:
    test_dir = _make_env_test_dir("configured_first")
    configured_env = test_dir / "configured.env"
    cwd_env = test_dir / ".env"

    configured_env.write_text("DATABASE_URL=postgresql://configured\n", encoding="utf-8")
    cwd_env.write_text("DATABASE_URL=postgresql://cwd\n", encoding="utf-8")

    monkeypatch.chdir(test_dir)
    monkeypatch.setenv("OPCOES_APP_ENV_FILE", str(configured_env))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(runtime_env, "_LOADED", False)

    loaded = runtime_env.load_dotenv_once()

    assert loaded == configured_env
    assert runtime_env.os.environ["DATABASE_URL"] == "postgresql://configured"


def test_load_dotenv_once_falls_back_to_cwd_dotenv(monkeypatch) -> None:
    test_dir = _make_env_test_dir("cwd_fallback")
    cwd_env = test_dir / ".env"
    cwd_env.write_text("DATABASE_URL=postgresql://cwd\n", encoding="utf-8")

    monkeypatch.chdir(test_dir)
    monkeypatch.delenv("OPCOES_APP_ENV_FILE", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(runtime_env, "_LOADED", False)

    loaded = runtime_env.load_dotenv_once()

    assert loaded == cwd_env
    assert runtime_env.os.environ["DATABASE_URL"] == "postgresql://cwd"
