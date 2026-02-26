from __future__ import annotations

import sqlite3

from opcoes.auth import create_user, user_db_path
from opcoes.web import create_app


def _positions_tickers(db_path) -> list[str]:
    if not db_path.exists():
        return []
    conn = sqlite3.connect(db_path)
    try:
        table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'positions' LIMIT 1"
        ).fetchone()
        if not table:
            return []
        rows = conn.execute("SELECT ticker FROM positions ORDER BY id ASC").fetchall()
        return [str(r[0]) for r in rows]
    finally:
        conn.close()


def _login(client, username: str, password: str = "SenhaForte123!") -> None:
    resp = client.post(
        "/login",
        data={"username": username, "password": password, "next": "/positions"},
    )
    assert resp.status_code in (302, 303)


def test_web_requires_login_when_auth_enabled(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("OPCOES_AUTH_DB_PATH", str(tmp_path / "auth.db"))
    monkeypatch.setenv("OPCOES_USERS_DB_DIR", str(tmp_path / "users"))
    monkeypatch.setenv("OPCOES_SECRET_KEY", "teste-seguro")

    create_user(username="alice", password="SenhaForte123!")
    app = create_app()
    client = app.test_client()

    resp = client.get("/positions")
    assert resp.status_code in (302, 303)
    assert "/login" in str(resp.headers.get("Location") or "")


def test_web_isolates_data_per_user_database(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("OPCOES_AUTH_DB_PATH", str(tmp_path / "auth.db"))
    monkeypatch.setenv("OPCOES_USERS_DB_DIR", str(tmp_path / "users"))
    monkeypatch.setenv("OPCOES_SECRET_KEY", "teste-seguro")

    create_user(username="alice", password="SenhaForte123!")
    create_user(username="bob", password="SenhaForte123!")

    app = create_app()
    alice_client = app.test_client()
    bob_client = app.test_client()

    _login(alice_client, "alice")
    res = alice_client.post(
        "/positions/add",
        data={
            "ticker": "PETR4",
            "underlying": "PETR4",
            "trade_date": "2026-02-26",
            "qty": "100",
            "entry_price": "30.10",
            "fees": "0",
            "trade_type": "swing",
            "side": "long",
            "is_simulated": "0",
            "next": "/positions",
        },
    )
    assert res.status_code in (302, 303)

    _login(bob_client, "bob")
    res = bob_client.post(
        "/positions/add",
        data={
            "ticker": "VALE3",
            "underlying": "VALE3",
            "trade_date": "2026-02-26",
            "qty": "200",
            "entry_price": "58.20",
            "fees": "0",
            "trade_type": "swing",
            "side": "long",
            "is_simulated": "0",
            "next": "/positions",
        },
    )
    assert res.status_code in (302, 303)

    alice_tickers = _positions_tickers(user_db_path("alice"))
    bob_tickers = _positions_tickers(user_db_path("bob"))

    assert alice_tickers == ["PETR4"]
    assert bob_tickers == ["VALE3"]
