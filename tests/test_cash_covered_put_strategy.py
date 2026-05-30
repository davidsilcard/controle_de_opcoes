from __future__ import annotations

from opcoes.strategies.cash_covered_put import calculate_cash_covered_put_strategy


def test_cash_covered_put_does_not_list_stock_lot_as_sold_put() -> None:
    positions_open = [
        {
            "id": 1,
            "ticker": "BBASP226",
            "underlying": "BBAS3",
            "trade_date": "2026-03-23",
            "qty": 400,
            "open_qty": 400,
            "entry_price": 0.20,
            "fees": 0.19,
            "side": "short",
            "trade_type": "swing",
            "strategy_tag": "cash_put",
            "strike": 22.27,
            "underlying_price": 23.39,
            "last_price": 0.23,
            "is_simulated": 0,
        },
        {
            "id": 2,
            "ticker": "BBAS3",
            "underlying": "BBAS3",
            "trade_date": "2026-02-19",
            "qty": 1000,
            "open_qty": 1000,
            "entry_price": 25.92,
            "fees": 0.0,
            "side": "long",
            "trade_type": "swing",
            "strategy_tag": "estoque",
            "is_simulated": 0,
        },
    ]

    ctx = calculate_cash_covered_put_strategy(
        underlying="BBAS3",
        positions_open=positions_open,
        options_rows=[],
        quote={"price": 23.39, "price_date": "2026-04-02"},
        min_yield_pct=1.5,
        min_buffer_pct=5.0,
        min_days=7,
        max_days=300,
        contract_size=100,
        limit=50,
        cash_mode="real",
        total_balance=10000.0,
        buyback_target_pct=70.0,
    )

    assert [pos["ticker"] for pos in ctx["puts_real"]] == ["BBASP226"]
    assert ctx["puts_simulated"] == []


def test_cash_covered_put_uses_canonical_snapshot_for_collateral() -> None:
    positions_open = [
        {
            "id": 56,
            "ticker": "BBASR210ON",
            "underlying": "BBAS3",
            "trade_date": "2026-05-18",
            "qty": 800,
            "open_qty": 800,
            "entry_price": 0.71,
            "fees": 0.75,
            "side": "short",
            "trade_type": "swing",
            "strategy_tag": "cash_put",
            "is_simulated": 0,
        }
    ]
    options_rows = [
        {
            "ticker": "BBASR210",
            "underlying": "BBAS3",
            "option_type": "PUT",
            "strike": "20,85",
            "ultimo": "0,36",
            "underlying_price": "21,07",
            "vencimento": "19/06/2026",
            "dias_uteis": "15",
        }
    ]

    ctx = calculate_cash_covered_put_strategy(
        underlying="BBAS3",
        positions_open=positions_open,
        options_rows=options_rows,
        quote={"price": 21.07, "price_date": "2026-05-27"},
        min_yield_pct=1.5,
        min_buffer_pct=5.0,
        min_days=7,
        max_days=300,
        contract_size=100,
        limit=50,
        cash_mode="real",
        total_balance=18778.65,
        buyback_target_pct=70.0,
    )

    assert ctx["puts_real"][0]["strike"] == 20.85
    assert ctx["puts_real"][0]["market_ticker"] == "BBASR210"
    assert ctx["finance"]["collateral_locked"] == 16680.0
    assert round(ctx["finance"]["available_cash"], 2) == 2098.65
