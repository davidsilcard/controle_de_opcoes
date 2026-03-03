from __future__ import annotations

import time

import pytest

from opcoes.auth import create_user
from opcoes.web import create_app

pytestmark = pytest.mark.requires_postgres


def _login(client, username: str, password: str = "SenhaForte123!") -> None:
    resp = client.post(
        "/login",
        data={"username": username, "password": password, "next": "/positions"},
    )
    assert resp.status_code in (302, 303)


def test_session_expires_after_inactivity(monkeypatch) -> None:
    monkeypatch.setenv("OPCOES_SECRET_KEY", "teste-seguro")
    monkeypatch.setenv("OPCOES_SESSION_IDLE_MINUTES", "15")

    create_user(username="alice", password="SenhaForte123!")
    app = create_app()
    client = app.test_client()

    _login(client, "alice")
    with client.session_transaction() as sess:
        sess["last_activity_at"] = 0

    resp = client.get("/positions")
    assert resp.status_code in (302, 303)
    location = str(resp.headers.get("Location") or "")
    assert "/login" in location
    assert "reason=expired" in location

    with client.session_transaction() as sess:
        assert "username" not in sess


def test_session_is_renewed_while_user_is_active(monkeypatch) -> None:
    monkeypatch.setenv("OPCOES_SECRET_KEY", "teste-seguro")
    monkeypatch.setenv("OPCOES_SESSION_IDLE_MINUTES", "15")

    create_user(username="alice", password="SenhaForte123!")
    app = create_app()
    client = app.test_client()

    _login(client, "alice")
    old_ts = int(time.time()) - 60
    with client.session_transaction() as sess:
        sess["last_activity_at"] = old_ts

    resp = client.get("/positions")
    assert resp.status_code == 200

    with client.session_transaction() as sess:
        refreshed_ts = int(sess.get("last_activity_at") or 0)
    assert refreshed_ts > old_ts


def test_new_browser_instance_requires_login_again(monkeypatch) -> None:
    monkeypatch.setenv("OPCOES_SECRET_KEY", "teste-seguro")

    create_user(username="alice", password="SenhaForte123!")
    app = create_app()

    client_logged = app.test_client()
    _login(client_logged, "alice")
    resp_logged = client_logged.get("/positions")
    assert resp_logged.status_code == 200

    # Simula navegador novo/sem cookie de sessão.
    client_new_browser = app.test_client()
    resp_new_browser = client_new_browser.get("/positions")
    assert resp_new_browser.status_code in (302, 303)
    assert "/login" in str(resp_new_browser.headers.get("Location") or "")
