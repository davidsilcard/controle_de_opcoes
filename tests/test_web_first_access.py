from __future__ import annotations

import datetime as dt

import pytest

from opcoes.auth import _connect, authenticate_user, issue_temporary_password
from opcoes.web import create_app

pytestmark = pytest.mark.requires_postgres


def _csrf_token_from_page(client, path: str) -> str:
    response = client.get(path)
    assert response.status_code == 200
    with client.session_transaction() as sess:
        token = str(sess.get("_csrf_token") or "")
    assert token
    return token


def test_temp_password_redirects_to_first_access(monkeypatch) -> None:
    monkeypatch.setenv("OPCOES_SECRET_KEY", "teste-seguro")

    temp_password = issue_temporary_password(username="alice", replace=True)
    app = create_app()
    client = app.test_client()
    csrf_token = _csrf_token_from_page(client, "/login")

    response = client.post(
        "/login",
        data={
            "username": "alice",
            "password": temp_password,
            "next": "/positions",
            "_csrf_token": csrf_token,
        },
    )

    assert response.status_code in (302, 303)
    assert "/first-access" in str(response.headers.get("Location") or "")

    blocked = client.get("/positions")
    assert blocked.status_code in (302, 303)
    assert "/first-access" in str(blocked.headers.get("Location") or "")


def test_first_access_updates_password_and_releases_navigation(monkeypatch) -> None:
    monkeypatch.setenv("OPCOES_SECRET_KEY", "teste-seguro")

    temp_password = issue_temporary_password(username="bob", replace=True)
    app = create_app()
    client = app.test_client()
    login_csrf = _csrf_token_from_page(client, "/login")

    login_response = client.post(
        "/login",
        data={
            "username": "bob",
            "password": temp_password,
            "next": "/positions",
            "_csrf_token": login_csrf,
        },
    )
    assert "/first-access" in str(login_response.headers.get("Location") or "")

    first_access_csrf = _csrf_token_from_page(client, "/first-access")
    change_response = client.post(
        "/first-access",
        data={
            "password": "SenhaFinal123!",
            "password_confirm": "SenhaFinal123!",
            "_csrf_token": first_access_csrf,
        },
    )

    assert change_response.status_code in (302, 303)
    assert "/positions" in str(change_response.headers.get("Location") or "")
    assert authenticate_user(username="bob", password="SenhaFinal123!")
    assert not authenticate_user(username="bob", password=temp_password)


def test_first_access_rejects_password_mismatch(monkeypatch) -> None:
    monkeypatch.setenv("OPCOES_SECRET_KEY", "teste-seguro")

    temp_password = issue_temporary_password(username="carol", replace=True)
    app = create_app()
    client = app.test_client()
    login_csrf = _csrf_token_from_page(client, "/login")

    client.post(
        "/login",
        data={
            "username": "carol",
            "password": temp_password,
            "next": "/positions",
            "_csrf_token": login_csrf,
        },
    )

    first_access_csrf = _csrf_token_from_page(client, "/first-access")
    response = client.post(
        "/first-access",
        data={
            "password": "SenhaNova123!",
            "password_confirm": "SenhaOutra123!",
            "_csrf_token": first_access_csrf,
        },
    )

    assert response.status_code == 200
    assert "As senhas nao conferem" in response.get_data(as_text=True)


def test_expired_temp_password_shows_clear_message(monkeypatch) -> None:
    monkeypatch.setenv("OPCOES_SECRET_KEY", "teste-seguro")
    monkeypatch.setenv("OPCOES_TEMP_PASSWORD_TTL_SECONDS", "10800")

    temp_password = issue_temporary_password(username="dan", replace=True)
    conn = _connect()
    try:
        conn.execute(
            """
            UPDATE web_users
            SET temp_password_issued_at = %s
            WHERE username = %s
            """,
            (dt.datetime.now(dt.UTC) - dt.timedelta(hours=4), "dan"),
        )
        conn.commit()
    finally:
        conn.close()

    app = create_app()
    client = app.test_client()
    csrf_token = _csrf_token_from_page(client, "/login")

    response = client.post(
        "/login",
        data={
            "username": "dan",
            "password": temp_password,
            "next": "/positions",
            "_csrf_token": csrf_token,
        },
    )

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "senha temporaria expirou apos 3 horas" in html
