from __future__ import annotations

from opcoes.settings import (
    get_strategy_settings,
    update_strategy_settings,
)


def test_settings_sqlite_default_roundtrip(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("OPCOES_DB_BACKEND", raising=False)
    monkeypatch.setenv("OPCOES_DB_PATH", str(tmp_path / "settings.db"))

    update_strategy_settings(min_score=9, limit_opportunities=31, recurring_days=11)
    cfg = get_strategy_settings()

    assert cfg.min_score == 9
    assert cfg.limit_opportunities == 31
    assert cfg.recurring_days == 11


def test_settings_postgres_backend_falls_back_to_sqlite_on_write_and_read(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("OPCOES_DB_BACKEND", "postgres")
    monkeypatch.setenv("OPCOES_DB_PATH", str(tmp_path / "settings.db"))

    monkeypatch.setattr(
        "opcoes.settings._upsert_settings_postgres",
        lambda _params: (_ for _ in ()).throw(RuntimeError("pg down")),
    )
    monkeypatch.setattr(
        "opcoes.settings._load_raw_settings_postgres",
        lambda: (_ for _ in ()).throw(RuntimeError("pg down")),
    )

    update_strategy_settings(min_score=7, limit_opportunities=22, recurring_days=19)
    cfg = get_strategy_settings()

    assert cfg.min_score == 7
    assert cfg.limit_opportunities == 22
    assert cfg.recurring_days == 19


def test_settings_postgres_backend_prefers_postgres_values(monkeypatch) -> None:
    monkeypatch.setenv("OPCOES_DB_BACKEND", "postgres")
    monkeypatch.setattr(
        "opcoes.settings._load_raw_settings_postgres",
        lambda: {
            "strat_min_score": "10",
            "strat_limit_opportunities": "40",
            "strat_recurring_days": "50",
        },
    )

    cfg = get_strategy_settings()

    assert cfg.min_score == 10
    assert cfg.limit_opportunities == 40
    assert cfg.recurring_days == 50
