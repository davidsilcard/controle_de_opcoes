from __future__ import annotations

import pytest

from opcoes.auth import create_user
from opcoes.web import create_app


def _login_csrf_token(client) -> str:
    response = client.get("/login")
    assert response.status_code == 200
    with client.session_transaction() as sess:
        token = str(sess.get("_csrf_token") or "")
    assert token
    return token


def test_create_app_requires_secret_key_in_production(monkeypatch) -> None:
    monkeypatch.setenv("OPCOES_SKIP_PRODUCTION_CHECKS", "0")
    monkeypatch.setenv("OPCOES_WEB_DEBUG", "0")
    monkeypatch.delenv("OPCOES_SECRET_KEY", raising=False)

    with pytest.raises(RuntimeError, match="OPCOES_SECRET_KEY"):
        create_app()


@pytest.mark.requires_postgres
def test_login_rejects_post_without_csrf(monkeypatch) -> None:
    monkeypatch.setenv("OPCOES_SECRET_KEY", "teste-seguro")

    create_user(username="alice", password="SenhaForte123!")
    app = create_app()
    client = app.test_client()

    response = client.post(
        "/login",
        data={"username": "alice", "password": "SenhaForte123!", "next": "/positions"},
    )

    assert response.status_code == 400
    assert "Formulario expirado" in response.get_data(as_text=True)


@pytest.mark.requires_postgres
def test_login_rate_limit_blocks_repeated_failures(monkeypatch) -> None:
    monkeypatch.setenv("OPCOES_SECRET_KEY", "teste-seguro")
    monkeypatch.setenv("OPCOES_LOGIN_MAX_ATTEMPTS", "2")
    monkeypatch.setenv("OPCOES_LOGIN_BLOCK_SECONDS", "120")
    monkeypatch.setenv("OPCOES_LOGIN_WINDOW_SECONDS", "120")

    create_user(username="alice", password="SenhaForte123!")
    app = create_app()
    client = app.test_client()
    csrf_token = _login_csrf_token(client)

    first = client.post(
        "/login",
        data={
            "username": "alice",
            "password": "senha-errada",
            "next": "/positions",
            "_csrf_token": csrf_token,
        },
    )
    assert first.status_code == 200
    assert "inv" in first.get_data(as_text=True).lower()

    second = client.post(
        "/login",
        data={
            "username": "alice",
            "password": "senha-errada",
            "next": "/positions",
            "_csrf_token": csrf_token,
        },
    )
    assert second.status_code == 429
    assert "Muitas tentativas de login" in second.get_data(as_text=True)

    third = client.post(
        "/login",
        data={
            "username": "alice",
            "password": "SenhaForte123!",
            "next": "/positions",
            "_csrf_token": csrf_token,
        },
    )
    assert third.status_code == 429
    assert "Muitas tentativas de login" in third.get_data(as_text=True)


@pytest.mark.requires_postgres
def test_login_rate_limit_ignores_forged_forwarded_for(monkeypatch) -> None:
    monkeypatch.setenv("OPCOES_SECRET_KEY", "teste-seguro")
    monkeypatch.setenv("OPCOES_LOGIN_MAX_ATTEMPTS", "1")
    monkeypatch.setenv("OPCOES_LOGIN_BLOCK_SECONDS", "120")
    monkeypatch.setenv("OPCOES_LOGIN_WINDOW_SECONDS", "120")

    create_user(username="alice", password="SenhaForte123!")
    app = create_app()
    client = app.test_client()
    csrf_token = _login_csrf_token(client)

    first = client.post(
        "/login",
        data={
            "username": "alice",
            "password": "senha-errada",
            "next": "/positions",
            "_csrf_token": csrf_token,
        },
        headers={"X-Forwarded-For": "198.51.100.10"},
    )
    assert first.status_code == 429

    second = client.post(
        "/login",
        data={
            "username": "alice",
            "password": "SenhaForte123!",
            "next": "/positions",
            "_csrf_token": csrf_token,
        },
        headers={"X-Forwarded-For": "203.0.113.20"},
    )
    assert second.status_code == 429
    assert "Muitas tentativas de login" in second.get_data(as_text=True)


@pytest.mark.requires_postgres
def test_login_rate_limit_is_shared_between_app_instances(monkeypatch) -> None:
    monkeypatch.setenv("OPCOES_SECRET_KEY", "teste-seguro")
    monkeypatch.setenv("OPCOES_LOGIN_MAX_ATTEMPTS", "2")
    monkeypatch.setenv("OPCOES_LOGIN_BLOCK_SECONDS", "120")
    monkeypatch.setenv("OPCOES_LOGIN_WINDOW_SECONDS", "120")

    create_user(username="alice", password="SenhaForte123!")
    app_one = create_app()
    app_two = create_app()
    client_one = app_one.test_client()
    client_two = app_two.test_client()
    csrf_one = _login_csrf_token(client_one)
    csrf_two = _login_csrf_token(client_two)

    first = client_one.post(
        "/login",
        data={
            "username": "alice",
            "password": "senha-errada",
            "next": "/positions",
            "_csrf_token": csrf_one,
        },
    )
    assert first.status_code == 200

    second = client_two.post(
        "/login",
        data={
            "username": "alice",
            "password": "senha-errada",
            "next": "/positions",
            "_csrf_token": csrf_two,
        },
    )
    assert second.status_code == 429

    third = client_one.post(
        "/login",
        data={
            "username": "alice",
            "password": "SenhaForte123!",
            "next": "/positions",
            "_csrf_token": csrf_one,
        },
    )
    assert third.status_code == 429


def test_https_security_headers_are_applied(monkeypatch) -> None:
    monkeypatch.setenv("OPCOES_SECRET_KEY", "teste-seguro")
    monkeypatch.setenv("OPCOES_EDGE_BASE_URL", "http://edge:8001")
    monkeypatch.setenv("OPCOES_EDGE_PUBLIC_BASE_URL", "https://api.moven.cloud")
    monkeypatch.setenv("OPCOES_MARKET_DATA_TOKEN", "token-app")

    app = create_app()
    client = app.test_client()

    response = client.get("/login", base_url="https://opcoes.test")

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert response.headers["Strict-Transport-Security"].startswith("max-age=")
    csp = response.headers["Content-Security-Policy"]
    assert "frame-ancestors 'none'" in csp
    assert "connect-src" in csp
    assert "'self'" in csp
    assert "http://edge:8001" in csp
    assert "ws://edge:8001" in csp
    assert "https://api.moven.cloud" in csp
    assert "wss://api.moven.cloud" in csp


def test_login_emits_server_timing_when_perf_enabled(monkeypatch) -> None:
    monkeypatch.setenv("OPCOES_SECRET_KEY", "teste-seguro")
    monkeypatch.setenv("OPCOES_PERF_TIMING_ENABLED", "1")

    app = create_app()
    client = app.test_client()

    response = client.get("/login")

    assert response.status_code == 200
    header = response.headers.get("Server-Timing", "")
    assert "request.total" in header


def test_login_omits_server_timing_when_perf_disabled(monkeypatch) -> None:
    monkeypatch.setenv("OPCOES_SECRET_KEY", "teste-seguro")
    monkeypatch.setenv("OPCOES_PERF_TIMING_ENABLED", "0")

    app = create_app()
    client = app.test_client()

    response = client.get("/login")

    assert response.status_code == 200
    assert "Server-Timing" not in response.headers
