from __future__ import annotations

from opcoes import finance
from opcoes.strategies.cash_covered_put import get_cash_covered_put_context
from opcoes.web import create_app


def test_normalize_month_label_pads_single_digit_month() -> None:
    assert finance.normalize_month_label("2026-4") == "2026-04"
    assert finance.normalize_month_label("2026-04") == "2026-04"
    assert finance.normalize_month_label("2026-04-22") == "2026-04"
    assert finance.normalize_month_label("2026-0") == "2026-0"


def test_cash_covered_put_context_builds_open_put_quick_filter(monkeypatch) -> None:
    monkeypatch.setattr(
        "opcoes.strategies.cash_covered_put.get_cash_put_settings",
        lambda: type(
            "Settings",
            (),
            {
                "underlying": "PETR4",
                "min_yield_pct": 1.5,
                "min_buffer_pct": 5.0,
                "min_days": 7,
                "max_days": 60,
                "contract_size": 100,
                "limit": 20,
                "cash_mode": "real",
                "buyback_target_pct": 70.0,
            },
        )(),
    )
    monkeypatch.setattr(
        "opcoes.strategies.cash_covered_put.list_positions",
        lambda include_closed=True: [
            {
                "id": 1,
                "ticker": "PETRP470",
                "underlying": "PETR4",
                "qty": 200,
                "open_qty": 200,
                "entry_price": 1.2,
                "fees": 0.1,
                "trade_date": "2026-04-20",
                "side": "short",
                "strategy_tag": "cash_put",
                "is_simulated": 0,
                "status": "open",
            },
            {
                "id": 2,
                "ticker": "VALEP440",
                "underlying": "VALE3",
                "qty": 100,
                "open_qty": 0,
                "entry_price": 0.9,
                "fees": 0.1,
                "trade_date": "2026-04-20",
                "side": "short",
                "strategy_tag": "cash_put",
                "is_simulated": 0,
                "status": "closed",
            },
            {
                "id": 3,
                "ticker": "PETR4",
                "underlying": "PETR4",
                "qty": 100,
                "open_qty": 100,
                "entry_price": 30.0,
                "fees": 0.0,
                "trade_date": "2026-04-20",
                "side": "long",
                "strategy_tag": "estoque",
                "is_simulated": 0,
                "status": "open",
            },
        ],
    )
    monkeypatch.setattr(
        "opcoes.strategies.cash_covered_put.fetch_latest_underlying_options",
        lambda underlying: [],
    )
    monkeypatch.setattr(
        "opcoes.strategies.cash_covered_put.fetch_latest_underlying_quote",
        lambda underlying: {"price": 30.0, "price_date": "2026-04-22"},
    )
    monkeypatch.setattr(
        "opcoes.strategies.cash_covered_put.update_cash_put_settings",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr("opcoes.strategies.cash_covered_put.finance.get_balance", lambda mode="real": 0.0)
    monkeypatch.setattr(
        "opcoes.strategies.cash_covered_put.finance.get_monthly_premiums",
        lambda **_kwargs: [{"month": "2026-4", "total": 12.34}],
    )
    monkeypatch.setattr(
        "opcoes.strategies.cash_covered_put.finance.get_transactions",
        lambda **_kwargs: [],
    )
    monkeypatch.setattr(
        "opcoes.strategies.cash_covered_put.finance.get_ledger_sums_by_position",
        lambda **_kwargs: {},
    )

    ctx = get_cash_covered_put_context({"underlying": "PETR4"})

    assert ctx["monthly_premiums"][0]["month"] == "2026-04"
    assert [item["ticker"] for item in ctx["open_put_quick_filter"]] == ["PETR4"]
    assert ctx["open_put_quick_filter"][0]["has_open_puts"] is True
    assert ctx["open_put_quick_filter"][0]["qty_total"] == 200


def test_cash_covered_put_route_renders_quick_filter_and_empty_state(monkeypatch) -> None:
    contexts = iter(
        [
            {
                "underlying": "PETR4",
                "filters": {
                    "min_yield_pct": 1.5,
                    "min_buffer_pct": 5.0,
                    "min_days": 7,
                    "max_days": 60,
                    "contract_size": 100,
                    "limit": 20,
                    "buyback_target_pct": 70.0,
                },
                "cash_mode": "real",
                "finance": {"available_cash": 0.0, "total_cash": 0.0, "collateral_locked": 0.0, "max_lots": 0},
                "finance_breakdown": {
                    "real": {"available_cash": 0.0, "total_cash": 0.0, "collateral_locked": 0.0},
                    "simulated": {"available_cash": 0.0, "total_cash": 0.0, "collateral_locked": 0.0},
                },
                "monthly_premiums": [],
                "simulated_monthly_premiums": [],
                "underlying_quote": {"price": 30.0, "price_date": "2026-04-22"},
                "recent_transactions": [],
                "latest_assignment_summary": None,
                "puts_real": [],
                "puts_simulated": [],
                "buyback_candidates_real": [],
                "buyback_candidates_simulated": [],
                "suggestions": [],
                "open_put_quick_filter": [
                    {"ticker": "PETR4", "qty_total": 200, "has_open_puts": True},
                ],
            },
            {
                "underlying": "PETR4",
                "filters": {
                    "min_yield_pct": 1.5,
                    "min_buffer_pct": 5.0,
                    "min_days": 7,
                    "max_days": 60,
                    "contract_size": 100,
                    "limit": 20,
                    "buyback_target_pct": 70.0,
                },
                "cash_mode": "real",
                "finance": {"available_cash": 0.0, "total_cash": 0.0, "collateral_locked": 0.0, "max_lots": 0},
                "finance_breakdown": {
                    "real": {"available_cash": 0.0, "total_cash": 0.0, "collateral_locked": 0.0},
                    "simulated": {"available_cash": 0.0, "total_cash": 0.0, "collateral_locked": 0.0},
                },
                "monthly_premiums": [],
                "simulated_monthly_premiums": [],
                "underlying_quote": {"price": 30.0, "price_date": "2026-04-22"},
                "recent_transactions": [],
                "latest_assignment_summary": None,
                "puts_real": [],
                "puts_simulated": [],
                "buyback_candidates_real": [],
                "buyback_candidates_simulated": [],
                "suggestions": [],
                "open_put_quick_filter": [],
            },
        ]
    )
    monkeypatch.setattr("opcoes.web.get_cash_covered_put_context", lambda _args: next(contexts))

    app = create_app()
    app.testing = True
    client = app.test_client()

    first = client.get("/cash-covered-put?underlying=PETR4")
    second = client.get("/cash-covered-put?underlying=PETR4&limit=10")

    assert first.status_code == 200
    first_html = first.get_data(as_text=True)
    assert "Filtro rápido" in first_html
    assert "Aberta" in first_html
    assert "PETR4" in first_html

    assert second.status_code == 200
    second_html = second.get_data(as_text=True)
    assert "Nenhuma put aberta para acompanhar no momento." in second_html
