from __future__ import annotations

from opcoes.holdings import HoldingValidationError
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
    assert "Salvar operação" in html
    assert "Notas isoladas não recalculam mais o ledger." in html
    assert 'name="strategy_tag" value="covered_call"' in html
    assert 'title="Campo protegido pela estrategia."' in html
    assert "Estoque consolidado" in html
    assert "+ Novo estoque" in html
    assert 'action="/holdings/upsert"' in html


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


def test_positions_inventory_summary_has_edit_action(monkeypatch) -> None:
    monkeypatch.setattr("opcoes.web.list_positions", lambda **_kwargs: [])
    monkeypatch.setattr(
        "opcoes.web.finance.get_premium_position_ids",
        lambda _position_ids: set(),
    )
    monkeypatch.setattr(
        "opcoes.web.finance.get_ledger_sums_by_position",
        lambda **_kwargs: {},
    )
    monkeypatch.setattr("opcoes.web.list_holding_events", lambda **_kwargs: [])
    monkeypatch.setattr(
        "opcoes.web.list_holding_snapshots",
        lambda **_kwargs: [
            {
                "ticker": "SOJA3",
                "is_simulated": False,
                "shares_total": 314,
                "shares_reserved": 0,
                "shares_free": 314,
                "avg_price": 12.16,
                "coverage_status": "ok",
                "price_status": "ok",
            }
        ],
    )
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
    assert "SOJA3" in html
    assert 'data-holding-ticker="SOJA3"' in html
    assert 'data-holding-quantity="314"' in html
    assert 'data-holding-avg-price="12.16"' in html
    assert "Informe somente o saldo final da corretora" in html


def test_holdings_upsert_can_return_to_positions(monkeypatch) -> None:
    calls = {}

    def fake_upsert_holding(**kwargs):
        calls.update(kwargs)
        return {"shares_total": 1000, "avg_price": 6.31}

    monkeypatch.setattr("opcoes.web.upsert_holding", fake_upsert_holding)

    app = create_app()
    app.testing = True
    client = app.test_client()

    response = client.post(
        "/holdings/upsert",
        data={
            "next": "/positions?underlying=SOJA3",
            "underlying": "SOJA3",
            "quantity": "1000",
            "avg_price": "6.31",
            "event_date": "2026-05-22",
            "is_simulated": "0",
            "notes": "Saldo consolidado conforme corretora.",
        },
    )

    assert response.status_code == 302
    assert response.headers["Location"].startswith("/positions?underlying=SOJA3")
    assert "holding_notice=" in response.headers["Location"]
    assert calls["ticker"] == "SOJA3"
    assert calls["quantity"] == 1000
    assert calls["avg_price"] == 6.31
    assert calls["event_date"] == "2026-05-22"
    assert calls["is_simulated"] is False


def test_holdings_upsert_error_can_return_to_positions(monkeypatch) -> None:
    def fake_upsert_holding(**_kwargs):
        raise HoldingValidationError(
            "Nao foi possivel salvar o estoque de SOJA3.",
            ticker="SOJA3",
        )

    monkeypatch.setattr("opcoes.web.upsert_holding", fake_upsert_holding)

    app = create_app()
    app.testing = True
    client = app.test_client()

    response = client.post(
        "/holdings/upsert",
        data={
            "next": "/positions",
            "underlying": "SOJA3",
            "quantity": "1000",
            "avg_price": "6.31",
            "is_simulated": "0",
        },
    )

    assert response.status_code == 302
    assert response.headers["Location"].startswith("/positions?")
    assert "holding_error=" in response.headers["Location"]
