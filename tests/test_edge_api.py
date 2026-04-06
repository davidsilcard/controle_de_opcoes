from __future__ import annotations

from fastapi.testclient import TestClient

from opcoes.edge import EdgeSettings, create_app


class FakeGatewayClient:
    def __init__(self) -> None:
        self.batch_calls = 0

    def close(self) -> None:
        return None

    def get_quotes_batch(self, symbols: list[str], *, include_raw: bool = False) -> dict:
        self.batch_calls += 1
        return {
            "count": len(symbols),
            "items": [
                {
                    "requested_symbol": symbol,
                    "symbol": symbol,
                    "bid": 10.0,
                    "ask": 10.1,
                    "last": 10.05,
                }
                for symbol in symbols
            ],
        }

    def search_symbols(self, query: str, *, limit: int = 20) -> dict:
        return {
            "query": query,
            "count": 1,
            "items": [{"requested_query": query, "symbol": "PETR4"}],
        }

    def preview_order(self, payload: dict) -> dict:
        return {"requested_symbol": payload["symbol"], "check_completed": True}


class FakeAsyncGatewayClient:
    def __init__(self) -> None:
        self.batch_calls = 0

    async def aclose(self) -> None:
        return None

    async def get_quotes_batch(self, symbols: list[str], *, include_raw: bool = False) -> dict:
        self.batch_calls += 1
        return {
            "count": len(symbols),
            "items": [
                {
                    "requested_symbol": symbol,
                    "symbol": symbol,
                    "bid": 20.0,
                    "ask": 20.1,
                    "last": 20.05,
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


def test_edge_quotes_use_cache() -> None:
    client, gateway_client, _async_gateway_client = build_app()
    headers = {"Authorization": "Bearer token-123"}

    first = client.get("/v1/quotes/PETR4", headers=headers)
    second = client.get("/v1/quotes/PETR4", headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert gateway_client.batch_calls == 1


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
