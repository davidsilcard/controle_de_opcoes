from __future__ import annotations

import json

import httpx

from opcoes.market_data import (
    MarketDataClient,
    MarketDataConfig,
    enrich_option_rows_with_live_market_data,
    enrich_positions_with_live_market_data,
    enrich_underlying_quote_with_live_market_data,
    format_market_timestamp_label,
    load_market_data_config_from_env,
    market_price_for_position,
    market_source_label,
)


class FakeMarketClient:
    def __init__(self, payload: dict[str, dict]) -> None:
        self.payload = payload

    def fetch_quotes(self, _symbols) -> dict[str, dict]:
        return dict(self.payload)


def test_load_market_data_config_prefers_app_token(monkeypatch) -> None:
    monkeypatch.setenv("OPCOES_EDGE_BASE_URL", "http://127.0.0.1:8011")
    monkeypatch.setenv("OPCOES_EDGE_API_TOKENS", "excel=abc,app=token-app")

    config = load_market_data_config_from_env()

    assert config.base_url == "http://127.0.0.1:8011"
    assert config.bearer_token == "token-app"


def test_market_price_for_position_uses_hybrid_reference() -> None:
    stock_position = {"ticker": "PETR4", "side": "long"}
    short_call = {"ticker": "PETRD999", "side": "short"}

    stock_price, stock_source = market_price_for_position(
        stock_position,
        {"ok": True, "last": 48.7, "bid": 48.69, "ask": 48.71},
    )
    option_price, option_source = market_price_for_position(
        short_call,
        {"ok": True, "last": 0.11, "bid": 0.1, "ask": 0.12},
    )

    assert stock_price == 48.7
    assert stock_source == "last"
    assert option_price == 0.12
    assert option_source == "ask"


def test_enrich_positions_with_live_market_data_recomputes_metrics() -> None:
    positions = [
        {
            "id": 1,
            "ticker": "PETRD999",
            "underlying": "PETR4",
            "status": "open",
            "side": "short",
            "qty": 100,
            "open_qty": 100,
            "entry_price": 0.2,
            "fees": 1.0,
            "realized_pl": None,
            "last_price": 0.05,
            "pl": 14.0,
            "pl_pct": 70.0,
            "strike": 49.0,
            "underlying_price": 48.0,
        }
    ]
    client = FakeMarketClient(
        {
            "PETRD999": {
                "symbol": "PETRD999",
                "ok": True,
                "bid": 0.1,
                "ask": 0.12,
                "last": 0.11,
                "time_utc": "2026-04-14T13:00:00Z",
                "market_status": "live",
                "stale_seconds": 3,
            },
            "PETR4": {
                "symbol": "PETR4",
                "ok": True,
                "last": 48.8,
                "time_utc": "2026-04-14T13:00:00Z",
                "market_status": "live",
                "stale_seconds": 3,
            },
        }
    )

    enriched = enrich_positions_with_live_market_data(positions, client=client)
    pos = enriched[0]

    assert pos["last_price"] == 0.12
    assert pos["market_price_source"] == "ask"
    assert pos["underlying_price"] == 48.8
    assert pos["market_status"] == "live"
    assert round(float(pos["pl"]), 2) == 7.0
    assert round(float(pos["pl_pct"]), 2) == 35.0
    assert pos["extrinsic_pct_spot"] is not None


def test_enrich_option_rows_with_live_market_data_updates_premium_and_underlying() -> None:
    rows = [
        {
            "ticker": "PETRD999",
            "underlying": "PETR4",
            "ultimo": 0.09,
            "best_bid": 0.08,
            "underlying_price": 47.5,
        }
    ]
    client = FakeMarketClient(
        {
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
            "PETR4": {
                "symbol": "PETR4",
                "ok": True,
                "last": 48.9,
                "time_utc": "2026-04-14T13:00:00Z",
                "market_status": "live",
                "stale_seconds": 1,
            },
        }
    )

    enriched = enrich_option_rows_with_live_market_data(rows, underlying="PETR4", client=client)

    assert enriched[0]["market_premium_ref"] == 0.1
    assert enriched[0]["market_premium_source"] == "bid"
    assert enriched[0]["underlying_price"] == 48.9
    assert enriched[0]["market_status"] == "live"


def test_enrich_positions_with_live_market_data_marks_snapshot_fallbacks() -> None:
    positions = [
        {
            "id": 1,
            "ticker": "GGBRD221",
            "underlying": "GGBR4",
            "status": "open",
            "side": "short",
            "qty": 800,
            "open_qty": 800,
            "entry_price": 0.05,
            "fees": 0.04,
            "realized_pl": None,
            "last_price": 0.1,
            "underlying_price": 21.6,
            "last_snapshot_date": "2026-04-15",
        }
    ]

    enriched = enrich_positions_with_live_market_data(positions, client=FakeMarketClient({}))
    pos = enriched[0]

    assert pos["market_status"] == "snapshot"
    assert pos["market_price_source"] == "snapshot"
    assert pos["market_time_utc"] == "2026-04-15"
    assert pos["underlying_market_status"] == "snapshot"
    assert pos["underlying_market_time_utc"] == "2026-04-15"


def test_enrich_underlying_quote_with_live_market_data_preserves_snapshot_metadata() -> None:
    quote = {
        "underlying": "GGBR4",
        "price": 21.6,
        "price_date": "2026-04-15",
        "snapshot_date": "2026-04-15",
    }

    enriched = enrich_underlying_quote_with_live_market_data(
        quote,
        underlying="GGBR4",
        client=FakeMarketClient({}),
    )

    assert enriched is not None
    assert enriched["market_status"] == "snapshot"
    assert enriched["market_price_source"] == "snapshot"
    assert enriched["market_time_utc"] == "2026-04-15"


def test_market_display_helpers_format_source_and_timestamp() -> None:
    assert market_source_label("last") == "Ultimo"
    assert market_source_label("ask") == "Ask"
    assert format_market_timestamp_label("2026-04-15T13:59:24Z") == "15/04 13:59:24"
    assert format_market_timestamp_label("2026-04-15") == "15/04/2026"


def test_market_data_client_batch_posts_json_body() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["content_type"] = request.headers.get("Content-Type")
        captured["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "requested_symbol": "GGBR4",
                        "symbol": "GGBR4",
                        "last": 21.84,
                        "time_utc": "2026-04-15T15:40:34.615000Z",
                        "ok": True,
                    }
                ]
            },
        )

    client = MarketDataClient(
        config=MarketDataConfig(
            base_url="http://edge-test",
            bearer_token="token-app",
            timeout_seconds=5.0,
            stale_after_seconds=60,
        ),
        http_client=httpx.Client(base_url="http://edge-test", transport=httpx.MockTransport(handler)),
    )

    payload = client.fetch_quotes(["GGBR4"])

    assert captured["content_type"] == "application/json"
    assert captured["body"] == {"symbols": ["GGBR4"], "include_raw": False}
    assert payload["GGBR4"]["ok"] is True
