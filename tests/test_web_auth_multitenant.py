from __future__ import annotations

import sqlite3

from opcoes.auth import create_user, user_db_path
from opcoes import finance, portfolio
from opcoes.fundamentus import save_signals, save_snapshot
from opcoes.scraper.snapshots import SnapshotDB
from opcoes.scraper.storage import CSV_FIELDS
from opcoes.settings import (
    update_cash_put_settings,
    update_covered_call_settings,
    update_fundamentus_settings,
)
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


def _setting_value(db_path, key: str):
    if not db_path.exists():
        return None
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def _build_option_row(
    *,
    underlying: str,
    ticker: str,
    option_type: str,
    strike: str,
    best_bid: str,
    underlying_price: str,
    dist_perc_strike: str = "3,00",
    dias_uteis: str = "20",
) -> dict:
    row = {col: "" for col in CSV_FIELDS}
    row.update(
        {
            "underlying": underlying,
            "ticker": ticker,
            "option_type": option_type,
            "vencimento": "20/03/2026",
            "dias_uteis": dias_uteis,
            "strike": strike,
            "best_bid": best_bid,
            "ultimo": best_bid,
            "underlying_price": underlying_price,
            "dist_perc_strike": dist_perc_strike,
            "score_total": "5,00",
        }
    )
    return row


def _insert_underlying_snapshot(db_path, *, snapshot_date: str, underlying: str, price: float) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO underlying_snapshots
            (snapshot_date, underlying, price, price_date)
            VALUES (?, ?, ?, ?)
            """,
            (snapshot_date, underlying, float(price), snapshot_date),
        )
        conn.commit()
    finally:
        conn.close()


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


def test_web_first_login_with_empty_user_db_shows_guided_empty_state(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("OPCOES_AUTH_DB_PATH", str(tmp_path / "auth.db"))
    monkeypatch.setenv("OPCOES_USERS_DB_DIR", str(tmp_path / "users"))
    monkeypatch.setenv("OPCOES_SECRET_KEY", "teste-seguro")

    create_user(username="alice", password="SenhaForte123!")
    app = create_app()
    client = app.test_client()

    _login(client, "alice")
    resp = client.get("/")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Ainda não há snapshots para este usuário." in html


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


def test_settings_are_isolated_per_logged_user(monkeypatch, tmp_path) -> None:
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
        "/settings",
        data={
            "equity_fixed": "1.11",
            "equity_percent": "0.10",
            "option_fixed": "0.20",
            "option_percent_notional": "0.30",
            "strat_min_score": "9",
            "strat_limit_opportunities": "31",
            "strat_recurring_days": "11",
        },
    )
    assert res.status_code in (302, 303)

    _login(bob_client, "bob")
    res = bob_client.post(
        "/settings",
        data={
            "equity_fixed": "9.99",
            "equity_percent": "0.90",
            "option_fixed": "0.80",
            "option_percent_notional": "0.70",
            "strat_min_score": "7",
            "strat_limit_opportunities": "21",
            "strat_recurring_days": "19",
        },
    )
    assert res.status_code in (302, 303)

    alice_db = user_db_path("alice")
    bob_db = user_db_path("bob")

    assert _setting_value(alice_db, "fee_equity_fixed") == "1.11"
    assert _setting_value(bob_db, "fee_equity_fixed") == "9.99"
    assert _setting_value(alice_db, "strat_min_score") == "9"
    assert _setting_value(bob_db, "strat_min_score") == "7"


def test_ranking_filters_are_isolated_and_persistent_per_user(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("OPCOES_AUTH_DB_PATH", str(tmp_path / "auth.db"))
    monkeypatch.setenv("OPCOES_USERS_DB_DIR", str(tmp_path / "users"))
    monkeypatch.setenv("OPCOES_SECRET_KEY", "teste-seguro")

    create_user(username="alice", password="SenhaForte123!")
    create_user(username="bob", password="SenhaForte123!")

    app = create_app()
    alice_client = app.test_client()
    bob_client = app.test_client()

    _login(alice_client, "alice")
    resp = alice_client.get(
        "/?min_score=9&limit=31&recurring_days=11&recurring_limit=7&underlying=ALIC&option_type=PUT"
    )
    assert resp.status_code == 200

    _login(bob_client, "bob")
    resp = bob_client.get(
        "/?min_score=6&limit=22&recurring_days=19&recurring_limit=5&underlying=BOB&option_type=CALL"
    )
    assert resp.status_code == 200

    alice_db = user_db_path("alice")
    bob_db = user_db_path("bob")
    assert _setting_value(alice_db, "strat_min_score") == "9"
    assert _setting_value(alice_db, "strat_limit_opportunities") == "31"
    assert _setting_value(alice_db, "strat_recurring_days") == "11"
    assert _setting_value(alice_db, "rank_recurring_limit") == "7"
    assert _setting_value(alice_db, "rank_underlying_filter") == "ALIC"
    assert _setting_value(alice_db, "rank_option_type_filter") == "PUT"

    assert _setting_value(bob_db, "strat_min_score") == "6"
    assert _setting_value(bob_db, "strat_limit_opportunities") == "22"
    assert _setting_value(bob_db, "strat_recurring_days") == "19"
    assert _setting_value(bob_db, "rank_recurring_limit") == "5"
    assert _setting_value(bob_db, "rank_underlying_filter") == "BOB"
    assert _setting_value(bob_db, "rank_option_type_filter") == "CALL"

    # Nova sessão de login para validar persistência após reabrir.
    alice_client_relogin = app.test_client()
    _login(alice_client_relogin, "alice")
    resp_alice = alice_client_relogin.get("/")
    assert resp_alice.status_code == 200
    html_alice = resp_alice.get_data(as_text=True)
    assert 'name="min_score" class="form-control form-control-sm" value="9"' in html_alice
    assert 'name="limit" class="form-control form-control-sm" value="31"' in html_alice
    assert 'name="recurring_days" class="form-control form-control-sm" value="11"' in html_alice
    assert 'name="recurring_limit" class="form-control form-control-sm" value="7"' in html_alice
    assert 'name="underlying" class="form-control form-control-sm" value="ALIC"' in html_alice
    assert '<option value="PUT" selected' in html_alice
    assert '<option value="CALL" selected' not in html_alice

    bob_client_relogin = app.test_client()
    _login(bob_client_relogin, "bob")
    resp_bob = bob_client_relogin.get("/")
    assert resp_bob.status_code == 200
    html_bob = resp_bob.get_data(as_text=True)
    assert 'name="min_score" class="form-control form-control-sm" value="6"' in html_bob
    assert 'name="limit" class="form-control form-control-sm" value="22"' in html_bob
    assert 'name="recurring_days" class="form-control form-control-sm" value="19"' in html_bob
    assert 'name="recurring_limit" class="form-control form-control-sm" value="5"' in html_bob
    assert 'name="underlying" class="form-control form-control-sm" value="BOB"' in html_bob
    assert '<option value="CALL" selected' in html_bob
    assert '<option value="PUT" selected' not in html_bob


def test_positions_page_and_filters_are_isolated_per_user(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("OPCOES_AUTH_DB_PATH", str(tmp_path / "auth.db"))
    monkeypatch.setenv("OPCOES_USERS_DB_DIR", str(tmp_path / "users"))
    monkeypatch.setenv("OPCOES_SECRET_KEY", "teste-seguro")

    create_user(username="alice", password="SenhaForte123!")
    create_user(username="bob", password="SenhaForte123!")

    alice_db = user_db_path("alice")
    alice_db.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("OPCOES_DB_PATH", str(alice_db))
    portfolio.add_position(
        ticker="ALICM100",
        underlying="ALIC3",
        trade_date="2026-02-26",
        qty=100,
        entry_price=1.0,
        fees=0.0,
        trade_type="swing",
        side="short",
        strategy_tag="cash_put",
        is_simulated=False,
    )

    bob_db = user_db_path("bob")
    bob_db.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("OPCOES_DB_PATH", str(bob_db))
    portfolio.add_position(
        ticker="BOBA200",
        underlying="BOB4",
        trade_date="2026-02-26",
        qty=100,
        entry_price=2.0,
        fees=0.0,
        trade_type="swing",
        side="short",
        strategy_tag="covered_call",
        is_simulated=True,
    )

    app = create_app()
    alice_client = app.test_client()
    bob_client = app.test_client()

    _login(alice_client, "alice")
    resp_alice = alice_client.get("/positions")
    assert resp_alice.status_code == 200
    html_alice = resp_alice.get_data(as_text=True)
    assert "ALICM100" in html_alice
    assert "BOBA200" not in html_alice

    resp_alice_filtered = alice_client.get("/positions?strategy_tag=cash_put&ticker=ALIC&status=open&is_simulated=0")
    assert resp_alice_filtered.status_code == 200
    html_alice_filtered = resp_alice_filtered.get_data(as_text=True)
    assert "ALICM100" in html_alice_filtered
    assert "BOBA200" not in html_alice_filtered
    assert 'name="ticker" class="form-control form-control-sm" value="ALIC"' in html_alice_filtered
    assert '<option value="cash_put" selected' in html_alice_filtered
    assert '<option value="open" selected' in html_alice_filtered
    assert '<option value="0" selected' in html_alice_filtered

    _login(bob_client, "bob")
    resp_bob = bob_client.get("/positions")
    assert resp_bob.status_code == 200
    html_bob = resp_bob.get_data(as_text=True)
    assert "BOBA200" in html_bob
    assert "ALICM100" not in html_bob

    resp_bob_filtered = bob_client.get("/positions?strategy_tag=covered_call&ticker=BOB&status=open&is_simulated=1")
    assert resp_bob_filtered.status_code == 200
    html_bob_filtered = resp_bob_filtered.get_data(as_text=True)
    assert "BOBA200" in html_bob_filtered
    assert "ALICM100" not in html_bob_filtered
    assert 'name="ticker" class="form-control form-control-sm" value="BOB"' in html_bob_filtered
    assert '<option value="covered_call" selected' in html_bob_filtered
    assert '<option value="open" selected' in html_bob_filtered
    assert '<option value="1" selected' in html_bob_filtered


def test_audit_is_isolated_per_logged_user(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("OPCOES_AUTH_DB_PATH", str(tmp_path / "auth.db"))
    monkeypatch.setenv("OPCOES_USERS_DB_DIR", str(tmp_path / "users"))
    monkeypatch.setenv("OPCOES_SECRET_KEY", "teste-seguro")

    create_user(username="alice", password="SenhaForte123!")
    create_user(username="bob", password="SenhaForte123!")

    alice_db = user_db_path("alice")
    alice_db.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("OPCOES_DB_PATH", str(alice_db))
    alice_pos = portfolio.add_position(
        ticker="ALICB100",
        underlying="ALIC3",
        trade_date="2026-02-26",
        qty=100,
        entry_price=1.0,
        fees=0.0,
        trade_type="swing",
        side="short",
    )
    finance.add_transaction(
        date="2026-02-26",
        type=finance.TransactionType.PREMIUM,
        amount=100.0,
        description="Premium Alice",
        position_id=alice_pos,
        is_simulated=False,
    )

    bob_db = user_db_path("bob")
    bob_db.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("OPCOES_DB_PATH", str(bob_db))
    bob_pos = portfolio.add_position(
        ticker="BOBCB200",
        underlying="BOBC3",
        trade_date="2026-02-26",
        qty=200,
        entry_price=2.0,
        fees=0.0,
        trade_type="swing",
        side="short",
    )
    finance.add_transaction(
        date="2026-02-26",
        type=finance.TransactionType.PREMIUM,
        amount=400.0,
        description="Premium Bob",
        position_id=bob_pos,
        is_simulated=False,
    )

    app = create_app()
    alice_client = app.test_client()
    bob_client = app.test_client()

    _login(alice_client, "alice")
    resp_alice = alice_client.get("/audit?mode=real&include_closed=1")
    assert resp_alice.status_code == 200
    html_alice = resp_alice.get_data(as_text=True)
    assert "ALICB100" in html_alice
    assert "BOBCB200" not in html_alice

    _login(bob_client, "bob")
    resp_bob = bob_client.get("/audit?mode=real&include_closed=1")
    assert resp_bob.status_code == 200
    html_bob = resp_bob.get_data(as_text=True)
    assert "BOBCB200" in html_bob
    assert "ALICB100" not in html_bob


def test_darf_is_isolated_per_logged_user(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("OPCOES_AUTH_DB_PATH", str(tmp_path / "auth.db"))
    monkeypatch.setenv("OPCOES_USERS_DB_DIR", str(tmp_path / "users"))
    monkeypatch.setenv("OPCOES_SECRET_KEY", "teste-seguro")

    create_user(username="alice", password="SenhaForte123!")
    create_user(username="bob", password="SenhaForte123!")

    alice_db = user_db_path("alice")
    alice_db.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("OPCOES_DB_PATH", str(alice_db))
    alice_pos = portfolio.add_position(
        ticker="ALICD100",
        underlying="ALIC3",
        trade_date="2026-02-10",
        qty=100,
        entry_price=1.0,
        fees=0.0,
        trade_type="swing",
        side="short",
    )
    finance.add_transaction(
        date="2026-02-10",
        type=finance.TransactionType.DARF,
        amount=-15.0,
        description="DARF Alice",
        position_id=alice_pos,
        is_simulated=False,
    )

    bob_db = user_db_path("bob")
    bob_db.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("OPCOES_DB_PATH", str(bob_db))
    bob_pos = portfolio.add_position(
        ticker="BOBD200",
        underlying="BOBD3",
        trade_date="2026-02-10",
        qty=200,
        entry_price=2.0,
        fees=0.0,
        trade_type="swing",
        side="short",
    )
    finance.add_transaction(
        date="2026-02-10",
        type=finance.TransactionType.DARF,
        amount=-25.0,
        description="DARF Bob",
        position_id=bob_pos,
        is_simulated=False,
    )

    app = create_app()
    alice_client = app.test_client()
    bob_client = app.test_client()

    _login(alice_client, "alice")
    resp_alice = alice_client.get("/darf?mode=real&period=2026-02")
    assert resp_alice.status_code == 200
    html_alice = resp_alice.get_data(as_text=True)
    assert "ALICD100" in html_alice
    assert "BOBD200" not in html_alice

    _login(bob_client, "bob")
    resp_bob = bob_client.get("/darf?mode=real&period=2026-02")
    assert resp_bob.status_code == 200
    html_bob = resp_bob.get_data(as_text=True)
    assert "BOBD200" in html_bob
    assert "ALICD100" not in html_bob


def test_fundamentus_data_and_filters_are_isolated_per_user(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("OPCOES_AUTH_DB_PATH", str(tmp_path / "auth.db"))
    monkeypatch.setenv("OPCOES_USERS_DB_DIR", str(tmp_path / "users"))
    monkeypatch.setenv("OPCOES_SECRET_KEY", "teste-seguro")

    # Evita dependência externa de rede/yfinance no teste.
    monkeypatch.setattr(
        "opcoes.strategies.fundamentus._fetch_metadata_yf",
        lambda tickers: {t: {"sector": "Finance", "industry": "Banks"} for t in tickers},
    )

    create_user(username="alice", password="SenhaForte123!")
    create_user(username="bob", password="SenhaForte123!")

    snapshot_date = "2026-02-20"

    alice_db = user_db_path("alice")
    alice_db.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("OPCOES_DB_PATH", str(alice_db))
    save_snapshot(
        [
            {
                "papel": "ALIC3",
                "cotacao": "20,00",
                "div_yield": "10,00",
                "liquidez_2m": "2000000",
                "div_bruta_patrim": "0,50",
                "cresc_rec_5a": "5,00",
                "roe": "18,00",
                "margem_liquida": "12,00",
            }
        ],
        snapshot_date=snapshot_date,
    )
    save_signals(
        [
            {
                "papel": "ALIC3",
                "status": "approved",
                "failed_step": None,
                "failed_rule": None,
                "failed_value": None,
                "reason": "approved",
            }
        ],
        snapshot_date=snapshot_date,
    )
    update_fundamentus_settings(
        target_yield_pct=10.0,
        put_distance_limit_pct=12.0,
        put_min_premium_pct=0.9,
        put_target_monthly_yield_pct=1.2,
        put_min_score=5.0,
    )

    bob_db = user_db_path("bob")
    bob_db.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("OPCOES_DB_PATH", str(bob_db))
    save_snapshot(
        [
            {
                "papel": "BOB4",
                "cotacao": "30,00",
                "div_yield": "6,00",
                "liquidez_2m": "2500000",
                "div_bruta_patrim": "0,40",
                "cresc_rec_5a": "6,00",
                "roe": "20,00",
                "margem_liquida": "14,00",
            }
        ],
        snapshot_date=snapshot_date,
    )
    save_signals(
        [
            {
                "papel": "BOB4",
                "status": "approved",
                "failed_step": None,
                "failed_rule": None,
                "failed_value": None,
                "reason": "approved",
            }
        ],
        snapshot_date=snapshot_date,
    )
    update_fundamentus_settings(
        target_yield_pct=6.0,
        put_distance_limit_pct=18.0,
        put_min_premium_pct=0.5,
        put_target_monthly_yield_pct=0.8,
        put_min_score=4.0,
    )

    app = create_app()
    alice_client = app.test_client()
    bob_client = app.test_client()

    _login(alice_client, "alice")
    resp_alice = alice_client.get(f"/fundamentus?status=approved&date={snapshot_date}")
    assert resp_alice.status_code == 200
    html_alice = resp_alice.get_data(as_text=True)
    assert "ALIC3" in html_alice
    assert "BOB4" not in html_alice
    assert "Preco teto 10.0%" in html_alice
    assert "Preco teto 6.0%" not in html_alice

    _login(bob_client, "bob")
    resp_bob = bob_client.get(f"/fundamentus?status=approved&date={snapshot_date}")
    assert resp_bob.status_code == 200
    html_bob = resp_bob.get_data(as_text=True)
    assert "BOB4" in html_bob
    assert "ALIC3" not in html_bob
    assert "Preco teto 6.0%" in html_bob
    assert "Preco teto 10.0%" not in html_bob


def test_cash_covered_put_data_and_filters_are_isolated_per_user(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("OPCOES_AUTH_DB_PATH", str(tmp_path / "auth.db"))
    monkeypatch.setenv("OPCOES_USERS_DB_DIR", str(tmp_path / "users"))
    monkeypatch.setenv("OPCOES_SECRET_KEY", "teste-seguro")

    create_user(username="alice", password="SenhaForte123!")
    create_user(username="bob", password="SenhaForte123!")

    snapshot_date = "2026-02-20"

    alice_db = user_db_path("alice")
    alice_db.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("OPCOES_DB_PATH", str(alice_db))
    snap_alice = SnapshotDB(alice_db)
    try:
        snap_alice.record_options(
            snapshot_date,
            [
                _build_option_row(
                    underlying="ALIC3",
                    ticker="ALICM100",
                    option_type="PUT",
                    strike="20,00",
                    best_bid="1,20",
                    underlying_price="22,00",
                )
            ],
        )
    finally:
        snap_alice.close()
    _insert_underlying_snapshot(alice_db, snapshot_date=snapshot_date, underlying="ALIC3", price=22.0)
    portfolio.add_position(
        ticker="ALICM100",
        underlying="ALIC3",
        trade_date="2026-02-19",
        qty=100,
        entry_price=1.2,
        fees=0.0,
        trade_type="swing",
        side="short",
        strategy_tag="cash_put",
    )
    update_cash_put_settings(
        underlying="ALIC3",
        min_yield_pct=3.3,
        min_buffer_pct=2.2,
        min_days=5,
        max_days=40,
        contract_size=100,
        limit=9,
        cash_mode="real",
        buyback_target_pct=37.0,
    )

    bob_db = user_db_path("bob")
    bob_db.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("OPCOES_DB_PATH", str(bob_db))
    snap_bob = SnapshotDB(bob_db)
    try:
        snap_bob.record_options(
            snapshot_date,
            [
                _build_option_row(
                    underlying="BOB4",
                    ticker="BOBM200",
                    option_type="PUT",
                    strike="30,00",
                    best_bid="2,10",
                    underlying_price="31,50",
                )
            ],
        )
    finally:
        snap_bob.close()
    _insert_underlying_snapshot(bob_db, snapshot_date=snapshot_date, underlying="BOB4", price=31.5)
    portfolio.add_position(
        ticker="BOBM200",
        underlying="BOB4",
        trade_date="2026-02-19",
        qty=100,
        entry_price=2.1,
        fees=0.0,
        trade_type="swing",
        side="short",
        strategy_tag="cash_put",
    )
    update_cash_put_settings(
        underlying="BOB4",
        min_yield_pct=7.7,
        min_buffer_pct=9.9,
        min_days=11,
        max_days=33,
        contract_size=200,
        limit=4,
        cash_mode="simulated",
        buyback_target_pct=81.0,
    )

    app = create_app()
    alice_client = app.test_client()
    bob_client = app.test_client()

    _login(alice_client, "alice")
    resp_alice = alice_client.get("/cash-covered-put")
    assert resp_alice.status_code == 200
    html_alice = resp_alice.get_data(as_text=True)
    assert "Cash-Covered Put – ALIC3" in html_alice
    assert "ALICM100" in html_alice
    assert "BOBM200" not in html_alice
    assert "Meta de recompra: 37.0% do prêmio." in html_alice
    assert '<option value="real" selected' in html_alice
    assert 'name="min_yield_pct"' in html_alice and 'value="3.3"' in html_alice

    _login(bob_client, "bob")
    resp_bob = bob_client.get("/cash-covered-put")
    assert resp_bob.status_code == 200
    html_bob = resp_bob.get_data(as_text=True)
    assert "Cash-Covered Put – BOB4" in html_bob
    assert "BOBM200" in html_bob
    assert "ALICM100" not in html_bob
    assert "Meta de recompra: 81.0% do prêmio." in html_bob
    assert '<option value="simulated" selected' in html_bob
    assert 'name="min_yield_pct"' in html_bob and 'value="7.7"' in html_bob


def test_covered_call_data_and_filters_are_isolated_per_user(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("OPCOES_AUTH_DB_PATH", str(tmp_path / "auth.db"))
    monkeypatch.setenv("OPCOES_USERS_DB_DIR", str(tmp_path / "users"))
    monkeypatch.setenv("OPCOES_SECRET_KEY", "teste-seguro")

    create_user(username="alice", password="SenhaForte123!")
    create_user(username="bob", password="SenhaForte123!")

    snapshot_date = "2026-02-20"

    alice_db = user_db_path("alice")
    alice_db.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("OPCOES_DB_PATH", str(alice_db))
    snap_alice = SnapshotDB(alice_db)
    try:
        snap_alice.record_options(
            snapshot_date,
            [
                _build_option_row(
                    underlying="ALIC3",
                    ticker="ALICA100",
                    option_type="CALL",
                    strike="23,00",
                    best_bid="1,50",
                    underlying_price="22,00",
                    dist_perc_strike="4,50",
                )
            ],
        )
    finally:
        snap_alice.close()
    _insert_underlying_snapshot(alice_db, snapshot_date=snapshot_date, underlying="ALIC3", price=22.0)
    portfolio.add_position(
        ticker="ALIC3",
        underlying="ALIC3",
        trade_date="2026-02-19",
        qty=100,
        entry_price=20.0,
        fees=0.0,
        trade_type="stock",
        side="long",
        strategy_tag="estoque",
    )
    portfolio.add_position(
        ticker="ALICA100",
        underlying="ALIC3",
        trade_date="2026-02-19",
        qty=100,
        entry_price=1.5,
        fees=0.0,
        trade_type="swing",
        side="short",
        strategy_tag="covered_call",
    )
    update_covered_call_settings(
        underlying="ALIC3",
        min_extrinsic=2.5,
        min_days=10,
        max_days=40,
        min_dist_strike=2.2,
        buyback_target_pct=33.0,
        only_target_hits=True,
    )

    bob_db = user_db_path("bob")
    bob_db.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("OPCOES_DB_PATH", str(bob_db))
    snap_bob = SnapshotDB(bob_db)
    try:
        snap_bob.record_options(
            snapshot_date,
            [
                _build_option_row(
                    underlying="BOB4",
                    ticker="BOBA200",
                    option_type="CALL",
                    strike="32,00",
                    best_bid="2,00",
                    underlying_price="31,50",
                    dist_perc_strike="3,90",
                )
            ],
        )
    finally:
        snap_bob.close()
    _insert_underlying_snapshot(bob_db, snapshot_date=snapshot_date, underlying="BOB4", price=31.5)
    portfolio.add_position(
        ticker="BOB4",
        underlying="BOB4",
        trade_date="2026-02-19",
        qty=100,
        entry_price=30.0,
        fees=0.0,
        trade_type="stock",
        side="long",
        strategy_tag="estoque",
    )
    portfolio.add_position(
        ticker="BOBA200",
        underlying="BOB4",
        trade_date="2026-02-19",
        qty=100,
        entry_price=2.0,
        fees=0.0,
        trade_type="swing",
        side="short",
        strategy_tag="covered_call",
    )
    update_covered_call_settings(
        underlying="BOB4",
        min_extrinsic=6.6,
        min_days=11,
        max_days=33,
        min_dist_strike=4.4,
        buyback_target_pct=77.0,
        only_target_hits=False,
    )

    app = create_app()
    alice_client = app.test_client()
    bob_client = app.test_client()

    _login(alice_client, "alice")
    resp_alice = alice_client.get("/covered-call")
    assert resp_alice.status_code == 200
    html_alice = resp_alice.get_data(as_text=True)
    assert "Covered Call – ALIC3" in html_alice
    assert "ALICA100" in html_alice
    assert "BOBA200" not in html_alice
    assert "Meta de recompra: 33.0% do prêmio." in html_alice
    assert 'name="min_extrinsic"' in html_alice and 'value="2.5"' in html_alice
    assert 'name="min_days"' in html_alice and 'value="10"' in html_alice
    assert 'name="min_dist_strike"' in html_alice and 'value="2.2"' in html_alice
    assert "Exibindo somente as que batem a meta." in html_alice
    assert ">ALIC3<" in html_alice
    assert ">BOB4<" not in html_alice

    _login(bob_client, "bob")
    resp_bob = bob_client.get("/covered-call")
    assert resp_bob.status_code == 200
    html_bob = resp_bob.get_data(as_text=True)
    assert "Covered Call – BOB4" in html_bob
    assert "BOBA200" in html_bob
    assert "ALICA100" not in html_bob
    assert "Meta de recompra: 77.0% do prêmio." in html_bob
    assert 'name="min_extrinsic"' in html_bob and 'value="6.6"' in html_bob
    assert 'name="min_days"' in html_bob and 'value="11"' in html_bob
    assert 'name="min_dist_strike"' in html_bob and 'value="4.4"' in html_bob
    assert "Exibindo somente as que batem a meta." not in html_bob
    assert ">BOB4<" in html_bob
    assert ">ALIC3<" not in html_bob
