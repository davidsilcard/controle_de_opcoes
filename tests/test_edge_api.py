from __future__ import annotations

from fastapi.testclient import TestClient

from opcoes.edge import EdgeSettings, create_app


class FakeGatewayClient:
    def __init__(self) -> None:
        self.batch_calls = 0
        self.quote_calls = 0
        self.send_calls = 0

    def close(self) -> None:
        return None

    def get_quote(self, symbol: str, *, include_raw: bool = False) -> dict:
        self.quote_calls += 1
        return {
            "requested_symbol": symbol,
            "symbol": symbol,
            "bid": 10.0,
            "ask": 10.1,
            "last": 10.05,
        }

    def get_quotes_batch(self, symbols: list[str], *, include_raw: bool = False) -> dict:
        self.batch_calls += 1
        items: list[dict] = []
        for symbol in symbols:
            if symbol == "FAIL3":
                items.append(
                    {
                        "requested_symbol": symbol,
                        "symbol": symbol,
                        "ok": False,
                        "error": {"code": "symbol_not_found", "message": "Simbolo nao encontrado."},
                    }
                )
            else:
                items.append(
                    {
                        "requested_symbol": symbol,
                        "symbol": symbol,
                        "bid": 10.0,
                        "ask": 10.1,
                        "last": 10.05,
                        "ok": True,
                    }
                )
        return {
            "count": len(items),
            "success_count": sum(1 for item in items if item.get("ok", True)),
            "error_count": sum(1 for item in items if not item.get("ok", True)),
            "partial": any(not item.get("ok", True) for item in items) and any(
                item.get("ok", True) for item in items
            ),
            "items": items,
        }

    def search_symbols(self, query: str, *, limit: int = 20) -> dict:
        return {
            "query": query,
            "count": 1,
            "items": [{"requested_query": query, "symbol": "PETR4"}],
        }

    def metrics(self) -> dict:
        return {
            "provider": "btg_trader_desk",
            "connected": True,
            "state": "connected",
            "quotes": {"requests_total": 10, "errors_total": 0},
        }

    def preview_order(self, payload: dict) -> dict:
        return {"requested_symbol": payload["symbol"], "check_completed": True}

    def send_order(self, payload: dict) -> dict:
        self.send_calls += 1
        return {"requested_symbol": payload["symbol"], "accepted": True}


class FakeAsyncGatewayClient:
    def __init__(self) -> None:
        self.batch_calls = 0

    async def aclose(self) -> None:
        return None

    async def get_quotes_batch(self, symbols: list[str], *, include_raw: bool = False) -> dict:
        self.batch_calls += 1
        return {
            "count": len(symbols),
            "success_count": len(symbols),
            "error_count": 0,
            "partial": False,
            "items": [
                {
                    "requested_symbol": symbol,
                    "symbol": symbol,
                    "bid": 20.0,
                    "ask": 20.1,
                    "last": 20.05,
                    "ok": True,
                }
                for symbol in symbols
            ],
        }


def build_app() -> tuple[TestClient, FakeGatewayClient, FakeAsyncGatewayClient]:
    gateway_client = FakeGatewayClient()
    async_gateway_client = FakeAsyncGatewayClient()
    app = create_app(
        settings=EdgeSettings(
            api_tokens={"excel": "token-123"},
            quote_cache_ms=500,
            ws_token_secret="ws-secret",
            ws_token_ttl_seconds=60,
            ws_poll_interval_ms=100,
            app_host="127.0.0.1",
            app_port=8001,
        ),
        gateway_client=gateway_client,
        async_gateway_client=async_gateway_client,
    )
    return TestClient(app), gateway_client, async_gateway_client


def test_edge_quotes_require_bearer_token() -> None:
    client, _gateway_client, _async_gateway_client = build_app()
    response = client.get("/v1/quotes/PETR4")
    assert response.status_code == 401


def test_edge_single_quote_uses_gateway_and_cache() -> None:
    client, gateway_client, _async_gateway_client = build_app()
    headers = {"Authorization": "Bearer token-123"}

    first = client.get("/v1/quotes/PETR4", headers=headers)
    second = client.get("/v1/quotes/PETR4", headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert gateway_client.quote_calls == 1
    assert gateway_client.batch_calls == 0


def test_edge_batch_keeps_partial_items_and_caches_only_successes() -> None:
    client, gateway_client, _async_gateway_client = build_app()
    headers = {"Authorization": "Bearer token-123"}

    response = client.post(
        "/v1/quotes/batch",
        headers=headers,
        json={"symbols": ["PETR4", "FAIL3"]},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 2
    assert payload["success_count"] == 1
    assert payload["error_count"] == 1
    assert payload["partial"] is True
    assert payload["items"][0]["requested_symbol"] == "PETR4"
    assert payload["items"][1]["requested_symbol"] == "FAIL3"
    assert payload["items"][1]["ok"] is False

    single = client.get("/v1/quotes/PETR4", headers=headers)
    assert single.status_code == 200
    assert gateway_client.batch_calls == 1
    assert gateway_client.quote_calls == 0


def test_edge_metrics_proxies_gateway_payload() -> None:
    client, _gateway_client, _async_gateway_client = build_app()
    headers = {"Authorization": "Bearer token-123"}

    response = client.get("/v1/metrics", headers=headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "btg_trader_desk"
    assert payload["connected"] is True
    assert payload["quotes"]["requests_total"] == 10


def test_edge_websocket_streams_snapshot() -> None:
    client, _gateway_client, async_gateway_client = build_app()
    headers = {"Authorization": "Bearer token-123"}
    token_response = client.post("/v1/ws/token", headers=headers)
    token = token_response.json()["token"]

    with client.websocket_connect(f"/v1/ws/quotes?token={token}") as websocket:
        websocket.send_json({"action": "subscribe", "symbols": ["PETR4"]})
        subscribed = websocket.receive_json()
        snapshot = websocket.receive_json()

    assert subscribed["type"] == "subscribed"
    assert subscribed["symbols"] == ["PETR4"]
    assert snapshot["type"] == "snapshot"
    assert snapshot["count"] == 1
    assert async_gateway_client.batch_calls >= 1
