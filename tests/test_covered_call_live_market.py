from __future__ import annotations

from opcoes.strategies.covered_call import get_covered_call_context


class FakeMarketClient:
    def __init__(self, payload: dict[str, dict]) -> None:
        self.payload = payload

    def fetch_quotes(self, _symbols) -> dict[str, dict]:
        return dict(self.payload)


def test_covered_call_context_prefers_live_market_data(monkeypatch) -> None:
    monkeypatch.setattr(
        "opcoes.strategies.covered_call.list_positions",
        lambda include_closed=False: [
            {
                "id": 1,
                "ticker": "PETRD999",
                "underlying": "PETR4",
                "trade_date": "2026-04-14",
                "qty": 100,
                "open_qty": 100,
                "entry_price": 0.2,
                "last_price": 0.05,
                "underlying_price": 47.0,
                "status": "open",
                "side": "short",
                "trade_type": "swing",
                "strategy_tag": "covered_call",
                "is_simulated": 0,
                "fees": 1.0,
                "realized_pl": None,
                "dias_uteis": 3,
                "vencimento": "17/04/2026",
                "strike": 49.0,
                "pct_2x": None,
                "extrinsic_pct_spot": None,
            },
            {
                "id": 2,
                "ticker": "PETR4",
                "underlying": "PETR4",
                "trade_date": "2026-04-01",
                "qty": 100,
                "open_qty": 100,
                "entry_price": 45.0,
                "status": "open",
                "side": "long",
                "trade_type": "stock",
                "strategy_tag": "estoque",
                "is_simulated": 0,
                "fees": 0.0,
                "realized_pl": None,
                "last_price": 47.0,
            },
        ],
    )
    monkeypatch.setattr(
        "opcoes.strategies.covered_call.list_holding_snapshots",
        lambda **_kwargs: [],
    )
    monkeypatch.setattr(
        "opcoes.strategies.covered_call.fetch_latest_underlying_options",
        lambda underlying: [
            {
                "ticker": "PETRD999",
                "underlying": underlying,
                "option_type": "CALL",
                "vencimento": "17/04/2026",
                "dias_uteis": 3,
                "strike": 49.0,
                "underlying_price": 47.0,
                "dist_perc_strike": 4.25,
                "ultimo": 0.09,
                "best_bid": 0.08,
                "pct_2x": 5.0,
                "score_total": 1.2,
                "extrinsic_pct_spot": 0.1,
            }
        ],
    )
    monkeypatch.setattr(
        "opcoes.strategies.covered_call.fetch_latest_underlying_quote",
        lambda underlying: {"underlying": underlying, "price": 47.0, "price_date": "2026-04-14"},
    )
    monkeypatch.setattr(
        "opcoes.strategies.covered_call.get_covered_call_settings",
        lambda: type(
            "Settings",
            (),
            {
                "underlying": "PETR4",
                "min_extrinsic": 0.0,
                "min_days": 1,
                "max_days": 30,
                "min_dist_strike": 0.0,
                "buyback_target_pct": 70.0,
                "only_target_hits": False,
            },
        )(),
    )
    monkeypatch.setattr(
        "opcoes.strategies.covered_call.finance.get_monthly_premiums",
        lambda **_kwargs: [],
    )
    monkeypatch.setattr(
        "opcoes.strategies.covered_call.update_covered_call_settings",
        lambda **_kwargs: None,
    )

    client = FakeMarketClient(
        {
            "PETR4": {
                "symbol": "PETR4",
                "ok": True,
                "last": 48.9,
                "time_utc": "2026-04-14T13:00:00Z",
                "market_status": "live",
                "stale_seconds": 1,
            },
            "PETRD999": {
                "symbol": "PETRD999",
                "ok": True,
                "bid": 0.1,
                "ask": 0.12,
                "last": 0.11,
                "time_utc": "2026-04-14T13:00:00Z",
                "market_status": "live",
                "stale_seconds": 1,
            },
        }
    )

    ctx = get_covered_call_context({"underlying": "PETR4"}, market_data_client=client)

    assert ctx["underlying_quote"]["price"] == 48.9
    assert ctx["underlying_quote"]["market_status_label"] == "Ao vivo"
    assert ctx["covered_real"][0]["last_price"] == 0.12
    assert ctx["covered_real"][0]["market_price_source"] == "ask"
    assert ctx["covered_real"][0]["underlying_price"] == 48.9
    assert ctx["suggestions"][0]["premium_ref"] == 0.1
    assert ctx["suggestions"][0]["market_status_label"] == "Ao vivo"
