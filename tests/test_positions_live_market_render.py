from __future__ import annotations

from opcoes.web import create_app


def test_positions_route_renders_live_market_status(monkeypatch) -> None:
    monkeypatch.setattr(
        "opcoes.web._hide_replaced_legacy_stock_positions",
        lambda positions: positions,
        raising=False,
    )
    monkeypatch.setattr(
        "opcoes.web._build_inventory_overview",
        lambda _positions: [],
        raising=False,
    )
    monkeypatch.setattr(
        "opcoes.web.list_positions",
        lambda **_kwargs: [
            {
                "id": 7,
                "ticker": "PETRD999",
                "underlying": "PETR4",
                "status": "open",
                "trade_type": "swing",
                "side": "short",
                "strategy_tag": "covered_call",
                "parent_position_id": "",
                "is_simulated": False,
                "trade_date": "2026-04-14",
                "vencimento": "17/04/2026",
                "dias_uteis": 3,
                "qty": 100,
                "entry_price": 0.2,
                "last_price": 0.05,
                "pl": 14.0,
                "pl_pct": 70.0,
                "breakeven_price": 0.19,
                "score_total": 1.0,
                "trend_flag": "1",
                "realized_pl": None,
                "partial_qty": 0,
                "partial_price": None,
                "partial_date": None,
                "exit_reason": None,
                "fees": 1.0,
                "open_qty": 100,
                "notes": "",
                "irrf": None,
            }
        ],
    )
    monkeypatch.setattr(
        "opcoes.web.finance.get_premium_position_ids",
        lambda _position_ids: set(),
    )
    monkeypatch.setattr(
        "opcoes.web.finance.get_ledger_sums_by_position",
        lambda **_kwargs: {},
    )
    monkeypatch.setattr("opcoes.web.list_holding_snapshots", lambda **_kwargs: [])
    monkeypatch.setattr("opcoes.web.list_holding_events", lambda **_kwargs: [])
    monkeypatch.setattr(
        "opcoes.web.summarize_realized_positions",
        lambda **_kwargs: {
            "available_years": [],
            "available_months": [],
            "selected_year": None,
            "selected_month": None,
            "overall_totals": {
                "count": 0,
                "total_gross": 0.0,
                "total_fees": 0.0,
                "total_net": 0.0,
                "total_profit": 0.0,
                "total_loss": 0.0,
                "profit_count": 0,
                "loss_count": 0,
                "breakeven_count": 0,
            },
            "period_totals": {
                "count": 0,
                "total_gross": 0.0,
                "total_fees": 0.0,
                "total_net": 0.0,
                "total_profit": 0.0,
                "total_loss": 0.0,
                "profit_count": 0,
                "loss_count": 0,
                "breakeven_count": 0,
            },
            "by_year": [],
            "by_month": [],
            "period_positions": [],
        },
    )

    app = create_app()
    app.testing = True
    client = app.test_client()

    response = client.get("/positions")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Snapshot" in html
    assert "0.05" in html
    assert 'id="positions-live"' in html
    assert 'hx-get="/positions/partial/live?' in html
    assert "live_market.js?v=" not in html
    assert 'data-live-scope="positions"' not in html
    assert "Tabela editável de posições" in html
    assert 'action="/positions/update/7"' in html


def test_positions_partial_live_renders_table(monkeypatch) -> None:
    monkeypatch.setattr(
        "opcoes.web._hide_replaced_legacy_stock_positions",
        lambda positions: positions,
        raising=False,
    )
    monkeypatch.setattr(
        "opcoes.web._build_inventory_overview",
        lambda _positions: [],
        raising=False,
    )
    monkeypatch.setattr(
        "opcoes.web.list_positions",
        lambda **_kwargs: [
            {
                "id": 8,
                "ticker": "PETRE111",
                "underlying": "PETR4",
                "status": "open",
                "trade_type": "swing",
                "side": "short",
                "strategy_tag": "covered_call",
                "parent_position_id": "",
                "is_simulated": False,
                "trade_date": "2026-04-14",
                "vencimento": "17/04/2026",
                "dias_uteis": 3,
                "qty": 100,
                "entry_price": 0.2,
                "last_price": 0.08,
                "pl": 10.0,
                "pl_pct": 50.0,
                "breakeven_price": 0.18,
                "score_total": 1.0,
                "trend_flag": "1",
                "realized_pl": None,
                "partial_qty": 0,
                "partial_price": None,
                "partial_date": None,
                "exit_reason": None,
                "fees": 1.0,
                "open_qty": 100,
                "notes": "",
                "irrf": None,
            }
        ],
    )
    monkeypatch.setattr(
        "opcoes.web.finance.get_premium_position_ids",
        lambda _position_ids: set(),
    )
    monkeypatch.setattr(
        "opcoes.web.finance.get_ledger_sums_by_position",
        lambda **_kwargs: {},
    )
    monkeypatch.setattr("opcoes.web.list_holding_snapshots", lambda **_kwargs: [])
    monkeypatch.setattr("opcoes.web.list_holding_events", lambda **_kwargs: [])
    monkeypatch.setattr(
        "opcoes.web.summarize_realized_positions",
        lambda **_kwargs: {
            "available_years": [],
            "available_months": [],
            "selected_year": None,
            "selected_month": None,
            "overall_totals": {
                "count": 0,
                "total_gross": 0.0,
                "total_fees": 0.0,
                "total_net": 0.0,
                "total_profit": 0.0,
                "total_loss": 0.0,
                "profit_count": 0,
                "loss_count": 0,
                "breakeven_count": 0,
            },
            "period_totals": {
                "count": 0,
                "total_gross": 0.0,
                "total_fees": 0.0,
                "total_net": 0.0,
                "total_profit": 0.0,
                "total_loss": 0.0,
                "profit_count": 0,
                "loss_count": 0,
                "breakeven_count": 0,
            },
            "by_year": [],
            "by_month": [],
            "period_positions": [],
        },
    )

    app = create_app()
    app.testing = True
    client = app.test_client()

    response = client.get("/positions/partial/live?ticker=PETR")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Resultados realizados" in html
    assert "PETRE111" in html
    assert "Monitor por snapshot das posições" in html
    assert "Conectando" not in html
    assert "Snapshot" in html
    assert 'action="/positions/update/8"' not in html
