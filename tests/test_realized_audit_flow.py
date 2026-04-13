from __future__ import annotations

import pytest

from opcoes import finance, portfolio
from opcoes.web import create_app

pytestmark = pytest.mark.requires_postgres


def test_closing_position_syncs_realized_result_and_surfaces_in_audit() -> None:
    pos_id = portfolio.add_position(
        ticker="ITSA4",
        underlying="ITSA4",
        trade_date="2026-03-01",
        qty=100,
        entry_price=10.0,
        fees=2.0,
        trade_type="swing",
        side="long",
        strategy_tag="ranking",
    )

    app = create_app()
    app.testing = True
    client = app.test_client()

    response = client.post(
        f"/positions/update/{pos_id}",
        data={
            "ticker": "ITSA4",
            "underlying": "ITSA4",
            "status": "closed",
            "trade_type": "swing",
            "side": "long",
            "strategy_tag": "ranking",
            "parent_position_id": "",
            "is_simulated": "0",
            "trade_date": "2026-03-01",
            "qty": "100",
            "entry_price": "10.0",
            "fees": "2.0",
            "exit_date": "2026-03-20",
            "exit_price": "12.0",
            "notes": "",
            "partial_qty": "",
            "partial_price": "",
            "partial_date": "",
            "exit_reason": "alvo",
            "irrf": "0",
            "next": "/positions",
        },
    )
    assert response.status_code in (302, 303)

    txs = finance.get_transactions(limit=50)
    realized = [
        tx
        for tx in txs
        if tx.position_id == pos_id and tx.type == finance.TransactionType.REALIZED
    ]
    assert len(realized) == 1
    assert realized[0].date == "2026-03-20"
    assert abs(realized[0].amount - 198.0) < 1e-6

    audit_response = client.get("/audit?mode=real&include_closed=1")
    assert audit_response.status_code == 200
    html = audit_response.get_data(as_text=True)

    assert "Resultado realizado (nao caixa)" in html
    assert "Realizado ledger" in html
    assert "198.00" in html


def test_reopening_position_clears_exit_fields_and_realized_effects() -> None:
    pos_id = portfolio.add_position(
        ticker="ITSA4",
        underlying="ITSA4",
        trade_date="2026-03-01",
        qty=100,
        entry_price=10.0,
        fees=2.0,
        trade_type="swing",
        side="long",
        strategy_tag="ranking",
    )

    app = create_app()
    app.testing = True
    client = app.test_client()

    close_response = client.post(
        f"/positions/update/{pos_id}",
        data={
            "ticker": "ITSA4",
            "underlying": "ITSA4",
            "status": "closed",
            "trade_type": "swing",
            "side": "long",
            "strategy_tag": "ranking",
            "parent_position_id": "",
            "is_simulated": "0",
            "trade_date": "2026-03-01",
            "qty": "100",
            "entry_price": "10.0",
            "fees": "2.0",
            "exit_date": "2026-03-20",
            "exit_price": "12.0",
            "notes": "",
            "partial_qty": "",
            "partial_price": "",
            "partial_date": "",
            "exit_reason": "alvo",
            "irrf": "0",
            "next": "/positions",
        },
    )
    assert close_response.status_code in (302, 303)

    reopen_response = client.post(
        f"/positions/update/{pos_id}",
        data={
            "ticker": "ITSA4",
            "underlying": "ITSA4",
            "status": "open",
            "trade_type": "swing",
            "side": "long",
            "strategy_tag": "ranking",
            "parent_position_id": "",
            "is_simulated": "0",
            "trade_date": "2026-03-01",
            "qty": "100",
            "entry_price": "10.0",
            "fees": "2.0",
            "exit_date": "",
            "exit_price": "",
            "notes": "",
            "partial_qty": "",
            "partial_price": "",
            "partial_date": "",
            "exit_reason": "",
            "irrf": "0",
            "next": "/positions",
        },
    )
    assert reopen_response.status_code in (302, 303)

    pos = portfolio.get_position(pos_id)
    assert pos is not None
    assert pos["status"] == "open"
    assert pos["exit_date"] is None
    assert pos["exit_price"] is None
    assert pos["exit_reason"] is None
    assert pos["partial_date"] is None
    assert pos["partial_price"] is None
    assert pos["partial_qty"] == 0

    txs = finance.get_transactions(limit=50)
    realized = [
        tx
        for tx in txs
        if tx.position_id == pos_id and tx.type == finance.TransactionType.REALIZED
    ]
    assert realized == []

