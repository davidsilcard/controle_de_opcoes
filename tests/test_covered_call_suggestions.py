from __future__ import annotations

from opcoes.strategies.covered_call import calculate_covered_call_strategy


def test_covered_call_suggestions_exclude_strike_below_highest_free_cost() -> None:
    positions_open = [
        {
            "id": 1,
            "ticker": "GGBR4",
            "underlying": "GGBR4",
            "trade_date": "2026-03-23",
            "qty": 800,
            "open_qty": 800,
            "entry_price": 21.46,
            "side": "long",
            "trade_type": "stock",
            "strategy_tag": "covered_call",
            "is_simulated": 0,
        }
    ]
    options_rows = [
        {
            "ticker": "GGBRG196",
            "underlying": "GGBR4",
            "option_type": "CALL",
            "vencimento": "17/07/2026",
            "dias_uteis": 80,
            "strike": 19.53,
            "underlying_price": 17.45,
            "dist_perc_strike": 11.92,
            "ultimo": 4.71,
            "pct_2x": 4.60,
            "score_total": 0.0,
        },
        {
            "ticker": "GGBRE238",
            "underlying": "GGBR4",
            "option_type": "CALL",
            "vencimento": "15/05/2026",
            "dias_uteis": 36,
            "strike": 23.75,
            "underlying_price": 17.45,
            "dist_perc_strike": 36.10,
            "ultimo": 0.46,
            "pct_2x": 4.10,
            "score_total": 0.0,
        },
    ]
    quote = {"price": 17.45, "price_date": "2026-03-20"}

    ctx = calculate_covered_call_strategy(
        underlying="GGBR4",
        positions_open=positions_open,
        options_rows=options_rows,
        quote=quote,
        min_extrinsic=0.5,
        min_days=2,
        max_days=90,
        min_dist_strike=2.0,
        buyback_target_pct=70.0,
        target_upside_pct=12.0,
        only_target_hits=False,
    )

    tickers = [item["ticker"] for item in ctx["suggestions"]]
    assert "GGBRG196" not in tickers
    assert "GGBRE238" in tickers
    assert ctx["sell_target"]["strike_floor_price"] == 21.46
