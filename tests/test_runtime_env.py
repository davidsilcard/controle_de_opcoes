from __future__ import annotations

from opcoes import runtime_env


def test_load_dotenv_once_prefers_opcoes_app_env_file(monkeypatch, workspace_tmp_path) -> None:
    # dotenv writes directly to environ; delenv alone does not restore a key
    # that did not exist before the test, leaking the fake DSN to later tests.
    monkeypatch.setattr(runtime_env.os, "environ", runtime_env.os.environ.copy())
    test_dir = workspace_tmp_path
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


def test_load_dotenv_once_falls_back_to_cwd_dotenv(monkeypatch, workspace_tmp_path) -> None:
    monkeypatch.setattr(runtime_env.os, "environ", runtime_env.os.environ.copy())
    test_dir = workspace_tmp_path
    cwd_env = test_dir / ".env"
    cwd_env.write_text("DATABASE_URL=postgresql://cwd\n", encoding="utf-8")

    monkeypatch.chdir(test_dir)
    monkeypatch.delenv("OPCOES_APP_ENV_FILE", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(runtime_env, "_LOADED", False)

    loaded = runtime_env.load_dotenv_once()

    assert loaded == cwd_env
    assert runtime_env.os.environ["DATABASE_URL"] == "postgresql://cwd"
