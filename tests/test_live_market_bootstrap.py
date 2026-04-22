from __future__ import annotations

from opcoes.web import create_app


def test_live_market_bootstrap_requires_session_when_auth_enabled(monkeypatch) -> None:
    monkeypatch.setenv("OPCOES_AUTH_ENABLED", "1")
    monkeypatch.setattr(
        "opcoes.market_data.MarketDataClient.create_ws_token",
        lambda self: {
            "token": "ws-short-token",
            "expires_in": 60,
            "ws_url": "wss://api.example.test/v1/ws/quotes",
            "stale_after_seconds": 60,
        },
    )

    app = create_app()
    client = app.test_client()

    response = client.get("/live-market/bootstrap?scope=covered-call&symbols=PETR4,PETRE500")

    assert response.status_code == 401
    assert response.get_json()["error"] == "Sessao expirada ou nao autenticada."


def test_live_market_bootstrap_returns_ws_contract_for_authenticated_session(monkeypatch) -> None:
    monkeypatch.setenv("OPCOES_AUTH_ENABLED", "1")
    monkeypatch.setattr(
        "opcoes.market_data.MarketDataClient.create_ws_token",
        lambda self: {
            "token": "ws-short-token",
            "expires_in": 60,
            "ws_url": "wss://api.example.test/v1/ws/quotes",
            "stale_after_seconds": 45,
        },
    )

    app = create_app()
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["username"] = "alice"
        sess["app_schema"] = "alice"
        sess["must_change_password"] = False

    response = client.get(
        "/live-market/bootstrap?scope=covered-call&symbols=PETR4,PETRE500,PETR4&fallback_seconds=75"
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["scope"] == "covered-call"
    assert payload["ws_url"] == "wss://api.example.test/v1/ws/quotes"
    assert payload["token"] == "ws-short-token"
    assert payload["expires_in"] == 60
    assert payload["stale_after_seconds"] == 45
    assert payload["fallback_seconds"] == 75
    assert payload["symbols"] == ["PETR4", "PETRE500"]
