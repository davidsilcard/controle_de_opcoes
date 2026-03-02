from __future__ import annotations

import pytest

from opcoes.settings import (
    get_strategy_settings,
    update_strategy_settings,
)


def test_settings_postgres_backend_prefers_postgres_values(monkeypatch) -> None:
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


def test_settings_write_fails_fast_when_postgres_is_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(
        "opcoes.settings._upsert_settings_postgres",
        lambda _params: (_ for _ in ()).throw(RuntimeError("pg down")),
    )

    with pytest.raises(RuntimeError, match="pg down"):
        update_strategy_settings(min_score=7, limit_opportunities=22, recurring_days=19)
