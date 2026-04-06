from __future__ import annotations

import httpx

from opcoes.mt5_gateway import Mt5GatewayClient, Mt5GatewayConfig


def test_gateway_client_signs_batch_requests() -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["query"] = request.url.query.decode()
        captured["key_id"] = request.headers["X-Key-Id"]
        captured["timestamp"] = request.headers["X-Timestamp"]
        captured["nonce"] = request.headers["X-Nonce"]
        captured["signature"] = request.headers["X-Signature"]
        return httpx.Response(
            200,
            json={
                "count": 2,
                "items": [
                    {"requested_symbol": "PETR4", "symbol": "PETR4"},
                    {"requested_symbol": "VALE3", "symbol": "VALE3"},
                ],
            },
        )

    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(
        base_url="http://edge-test",
        transport=transport,
    )
    client = Mt5GatewayClient(
        config=Mt5GatewayConfig(
            base_url="http://edge-test",
            key_id="edge-1",
            shared_secret="super-secret",
            timeout_seconds=5,
        ),
        http_client=http_client,
    )

    payload = client.get_quotes_batch(["PETR4", "VALE3"], include_raw=False)

    assert payload["count"] == 2
    assert captured["path"] == "/internal/v1/quotes/batch"
    assert captured["key_id"] == "edge-1"
    assert captured["timestamp"]
    assert captured["nonce"]
    assert captured["signature"]

