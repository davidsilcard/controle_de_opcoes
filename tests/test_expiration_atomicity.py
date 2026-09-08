from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock
from time import monotonic

import pytest

from opcoes import finance, portfolio, web
from opcoes.config import (
    get_postgres_schema,
    reset_pg_schema_override,
    set_pg_schema_override,
)
from opcoes.db import open_db
from opcoes.web import create_app


pytestmark = pytest.mark.requires_postgres


@pytest.fixture(
    params=[
        pytest.param(("cash_put", "PETRN312", False), id="put-real"),
        pytest.param(("cash_put", "PETRN312", True), id="put-simulated"),
        pytest.param(("covered_call", "PETRB312", False), id="call-real"),
        pytest.param(("covered_call", "PETRB312", True), id="call-simulated"),
    ]
)
def expiration_case(request):
    strategy_tag, ticker, simulated = request.param
    position_id = portfolio.add_position(
        ticker=ticker,
        underlying="PETR4",
        trade_date="2026-01-09",
        qty=100,
        entry_price=0.61,
        fees=0.33,
        side="short",
        strategy_tag=strategy_tag,
        is_simulated=simulated,
    )
    app = create_app()
    app.testing = True
    destination = "/cash-covered-put" if strategy_tag == "cash_put" else "/covered-call"
    return app.test_client(), position_id, simulated, destination


def test_expiration_repetition_does_not_duplicate_ledger(expiration_case):
    client, position_id, simulated, destination = expiration_case
    form = {"position_id": str(position_id), "date": "2026-02-20"}
    response = client.post("/finance/expire", data=form)
    assert response.status_code == 302
    assert response.headers["Location"] == f"{destination}?underlying=PETR4"
    position = portfolio.get_position(position_id)
    assert position["status"] == "closed"
    assert position["exit_date"] == "2026-02-20"
    assert position["exit_price"] == 0.0
    assert position["exit_reason"] == "Expiração"
    before = finance.get_transactions(limit=100, is_simulated=simulated)
    realized = [
        row
        for row in before
        if row.position_id == position_id
        and row.type == finance.TransactionType.REALIZED
    ]
    assert len(realized) == 1
    assert realized[0].amount == pytest.approx(60.67)
    assert realized[0].date == "2026-02-20"
    response = client.post("/finance/expire", data=form)
    assert response.status_code == 302
    assert response.headers["Location"] == f"{destination}?underlying=PETR4"
    assert finance.get_transactions(limit=100, is_simulated=simulated) == before
    assert finance.get_transactions(limit=100, is_simulated=not simulated) == []


def test_expiration_financial_failure_rolls_back_position(expiration_case, monkeypatch):
    client, position_id, simulated, destination = expiration_case
    before = finance.get_transactions(limit=100, is_simulated=simulated)
    original_sync = finance.sync_position_closure_effects

    def fail_after_financial_write(**kwargs):
        assert kwargs.get("conn") is not None
        result = original_sync(**kwargs)
        assert result["realized"]
        raise RuntimeError("Injected failure after financial write")

    monkeypatch.setattr(
        finance, "sync_position_closure_effects", fail_after_financial_write
    )
    with pytest.raises(RuntimeError, match="Injected failure"):
        client.post(
            "/finance/expire",
            data={"position_id": str(position_id), "date": "2026-02-20"},
        )
    position = portfolio.get_position(position_id)
    assert position["status"] == "open"
    assert position["exit_date"] is None
    assert position["exit_price"] is None
    assert position["exit_reason"] is None
    assert finance.get_transactions(limit=100, is_simulated=simulated) == before
    assert finance.get_transactions(limit=100, is_simulated=not simulated) == []

    monkeypatch.setattr(finance, "sync_position_closure_effects", original_sync)
    response = client.post(
        "/finance/expire",
        data={"position_id": str(position_id), "date": "2026-02-20"},
    )
    assert response.status_code == 302
    assert response.headers["Location"] == f"{destination}?underlying=PETR4"
    assert portfolio.get_position(position_id)["status"] == "closed"


@pytest.mark.parametrize("date", [None, "invalid-date"])
def test_expiration_requires_valid_date_without_financial_changes(
    expiration_case, date
):
    client, position_id, simulated, destination = expiration_case
    form = {"position_id": str(position_id)}
    if date is not None:
        form["date"] = date
    before = finance.get_transactions(limit=100, is_simulated=simulated)

    response = client.post("/finance/expire", data=form)

    assert response.status_code == 302
    assert response.headers["Location"].startswith(f"{destination}?underlying=PETR4&")
    error_key = (
        "position_error" if destination == "/cash-covered-put" else "holding_error"
    )
    assert f"{error_key}=" in response.headers["Location"]
    position = portfolio.get_position(position_id)
    assert position["status"] == "open"
    assert position["exit_date"] is None
    assert finance.get_transactions(limit=100, is_simulated=simulated) == before
    assert finance.get_transactions(limit=100, is_simulated=not simulated) == []


def test_concurrent_expiration_waits_and_does_not_resync(expiration_case, monkeypatch):
    client, position_id, simulated, _destination = expiration_case
    first_locked, second_started, release_first = Event(), Event(), Event()
    counter_lock = Lock()
    pids = {}
    reads = 0
    syncs = []
    original_get = web.get_position
    original_sync = finance.sync_position_closure_effects

    def locked_read(*args, **kwargs):
        nonlocal reads
        assert kwargs.get("for_update") is True
        conn = kwargs["conn"]
        conn.execute("SET LOCAL statement_timeout = '15s'")
        with counter_lock:
            reads += 1
            order = reads
            pids[order] = conn.execute("SELECT pg_backend_pid() AS pid").fetchone()[
                "pid"
            ]
        if order == 2:
            second_started.set()
        result = original_get(*args, **kwargs)
        if order == 1:
            first_locked.set()
            assert release_first.wait(15), "Primeira requisição não foi liberada."
        return result

    def record_sync(**kwargs):
        syncs.append(kwargs["position_id"])
        return original_sync(**kwargs)

    monkeypatch.setattr(web, "get_position", locked_read)
    monkeypatch.setattr(finance, "sync_position_closure_effects", record_sync)

    def expire():
        with client.application.test_client() as separate_client:
            return separate_client.post(
                "/finance/expire",
                data={"position_id": str(position_id), "date": "2026-02-20"},
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(expire)
        try:
            assert first_locked.wait(10)
            second = executor.submit(expire)
            assert second_started.wait(10)
            deadline = monotonic() + 10
            blocked = False
            with open_db() as probe:
                while monotonic() < deadline:
                    row = probe.execute(
                        "SELECT %s = ANY(pg_blocking_pids(%s)) AS blocked",
                        (pids[1], pids[2]),
                    ).fetchone()
                    if row["blocked"]:
                        blocked = True
                        break
            assert blocked, "A segunda expiração não aguardou o bloqueio da primeira."
        finally:
            release_first.set()
        assert first.result(timeout=20).status_code == 302
        assert second.result(timeout=20).status_code == 302

    assert syncs == [position_id]
    assert portfolio.get_position(position_id)["status"] == "closed"
    realized = [
        tx
        for tx in finance.get_transactions(limit=100, is_simulated=simulated)
        if tx.position_id == position_id and tx.type == finance.TransactionType.REALIZED
    ]
    assert len(realized) == 1
    assert realized[0].amount == pytest.approx(60.67)


def test_expiration_cannot_close_another_user_position(expiration_case, monkeypatch):
    client, position_id, simulated, destination = expiration_case
    owner_schema = get_postgres_schema()
    other_schema = f"{owner_schema}_other"
    token = set_pg_schema_override(other_schema)
    try:
        with open_db():
            pass
    finally:
        reset_pg_schema_override(token)
    monkeypatch.setenv("OPCOES_AUTH_ENABLED", "1")
    app = client.application
    app.testing = False

    with client.session_transaction() as session:
        session["username"] = "other"
        session["app_schema"] = other_schema
        session[web.CSRF_FIELD_NAME] = "test-csrf"
    form = {
        "position_id": str(position_id),
        "date": "2026-02-20",
        web.CSRF_FIELD_NAME: "test-csrf",
    }
    response = client.post("/finance/expire", data=form)
    assert response.status_code == 302
    assert response.location == "/positions"
    assert portfolio.get_position(position_id)["status"] == "open"
    assert finance.get_transactions(limit=100, is_simulated=simulated) == []

    with client.session_transaction() as session:
        session["username"] = "owner"
        session["app_schema"] = owner_schema
    response = client.post("/finance/expire", data=form)
    assert response.status_code == 302
    assert response.location == f"{destination}?underlying=PETR4"
    assert portfolio.get_position(position_id)["status"] == "closed"
    token = set_pg_schema_override(other_schema)
    try:
        assert portfolio.get_position(position_id) is None
        assert finance.get_transactions(limit=100, is_simulated=simulated) == []
    finally:
        reset_pg_schema_override(token)
