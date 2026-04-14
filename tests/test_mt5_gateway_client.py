from __future__ import annotations

import hashlib
import hmac

import httpx
import pytest

from opcoes.mt5_gateway import (
    Mt5GatewayClient,
    Mt5GatewayConfig,
    Mt5GatewayError,
    build_hmac_headers,
)


def build_client(handler, *, scopes: frozenset[str] | None = None) -> Mt5GatewayClient:
    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(
        base_url="http://edge-test",
        transport=transport,
    )
    return Mt5GatewayClient(
        config=Mt5GatewayConfig(
            base_url="http://edge-test",
            key_id="edge=1",
            shared_secret="super-secret",
            timeout_seconds=5,
            scopes=scopes or frozenset({"quotes:read", "symbols:read", "orders:preview"}),
        ),
        http_client=http_client,
    )


def test_build_hmac_headers_matches_gateway_contract() -> None:
    body = b'{"symbols":["PETR4"],"include_raw":false}'
    headers = build_hmac_headers(
        key_id="edge=1",
        shared_secret="super-secret",
        method="POST",
        path="/internal/v1/quotes/batch",
        query="",
        body=body,
        timestamp="1710000000",
        nonce="nonce-123",
    )

    expected_body_hash = hashlib.sha256(body).hexdigest()
    canonical = "\n".join(
        [
            "POST",
            "/internal/v1/quotes/batch",
            "",
            "1710000000",
            "nonce-123",
            expected_body_hash,
        ]
    )
    expected_signature = hmac.new(
        b"super-secret",
        canonical.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    assert headers == {
        "X-Key-Id": "edge=1",
        "X-Timestamp": "1710000000",
        "X-Nonce": "nonce-123",
        "X-Signature": expected_signature,
    }


def test_gateway_client_get_quote_uses_signed_request() -> None:
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
                "requested_symbol": "PETR4",
                "symbol": "PETR4",
                "bid": 10.0,
                "ask": 10.1,
                "last": 10.05,
            },
        )

    client = build_client(handler)

    payload = client.get_quote("petr4")

    assert payload["symbol"] == "PETR4"
    assert captured["path"] == "/internal/v1/quotes/PETR4"
    assert captured["query"] == "include_raw=false"
    assert captured["key_id"] == "edge=1"
    assert captured["timestamp"]
    assert captured["nonce"]
    assert captured["signature"]


def test_gateway_client_normalizes_partial_batch() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "requested_symbol": "PETR4",
                        "ok": True,
                        "quote": {
                            "symbol": "PETR4",
                            "bid": 10.0,
                            "ask": 10.1,
                            "last": 10.05,
                        },
                    },
                    {
                        "requested_symbol": "VALE3",
                        "ok": False,
                        "error": {
                            "code": "symbol_not_found",
                            "message": "Simbolo indisponivel.",
                        },
                    },
                ]
            },
        )

    client = build_client(handler)

    payload = client.get_quotes_batch(["PETR4", "VALE3"])

    assert payload["count"] == 2
    assert payload["success_count"] == 1
    assert payload["error_count"] == 1
    assert payload["partial"] is True
    assert payload["items"][0]["requested_symbol"] == "PETR4"
    assert payload["items"][0]["symbol"] == "PETR4"
    assert payload["items"][0]["ok"] is True
    assert payload["items"][1]["requested_symbol"] == "VALE3"
    assert payload["items"][1]["ok"] is False
    assert payload["items"][1]["error"]["code"] == "symbol_not_found"


def test_gateway_client_reads_new_ready_payload() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/ready"
        return httpx.Response(
            200,
            json={
                "status": "ready",
                "mt5_connected": True,
                "mt5_state": "connected",
                "reconnect_count": 0,
            },
        )

    client = build_client(handler)

    payload = client.ready()

    assert payload == {
        "status": "ready",
        "mt5_connected": True,
        "mt5_state": "connected",
        "reconnect_count": 0,
    }


def test_gateway_client_blocks_send_order_without_scope() -> None:
    client = build_client(lambda _request: httpx.Response(200, json={"ok": True}), scopes=frozenset({"orders:preview"}))

    with pytest.raises(Mt5GatewayError) as exc:
        client.send_order({"symbol": "PETR4", "side": "buy", "order_type": "market", "volume": 1})

    assert exc.value.status_code == 403
    assert exc.value.payload["error"]["scope"] == "orders:send"
