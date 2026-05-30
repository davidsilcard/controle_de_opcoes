from __future__ import annotations

import pytest

from opcoes import finance, portfolio
from opcoes.cash_put_guard import (
    CashPutValidationError,
    audit_cash_put_positions,
    validate_cash_put_input,
)
from opcoes.web import create_app


def test_cash_put_guard_blocks_non_put_strategy_input() -> None:
    with pytest.raises(CashPutValidationError):
        validate_cash_put_input(
            ticker="PETRA30",
            underlying="PETR4",
            trade_date="2026-04-20",
            qty=100,
            entry_price=0.18,
            side="short",
            strategy_tag="cash_put",
        )


def test_cash_put_guard_blocks_invalid_trade_date() -> None:
    with pytest.raises(CashPutValidationError):
        validate_cash_put_input(
            ticker="PETRN312",
            underlying="PETR4",
            trade_date="026-04-20",
            qty=100,
            entry_price=0.18,
            side="short",
            strategy_tag="cash_put",
        )


def test_cash_put_audit_flags_missing_realized_result() -> None:
    positions = [
        {
            "id": 25,
            "ticker": "BBASN235",
            "underlying": "BBAS3",
            "trade_date": "2026-01-28",
            "qty": 600,
            "entry_price": 0.33,
            "fees": 4.61,
            "trade_type": "swing",
            "side": "short",
            "status": "closed",
            "exit_date": "2026-02-18",
            "exit_price": 0.01,
            "exit_reason": "recompra_encerramento",
            "strategy_tag": "cash_put",
            "is_simulated": 0,
        }
    ]
    issues = audit_cash_put_positions(
        positions,
        ledger_sums={
            25: {
                finance.TransactionType.PREMIUM.value: 193.39,
                finance.TransactionType.BUY.value: -6.0,
            }
        },
    )

    assert any(issue.code == "REALIZED_DIVERGENTE" for issue in issues)


@pytest.mark.requires_postgres
def test_cash_put_web_add_blocks_call_ticker() -> None:
    app = create_app()
    app.testing = True
    client = app.test_client()

    response = client.post(
        "/positions/add",
        data={
            "ticker": "PETRA30",
            "underlying": "PETR4",
            "trade_date": "2026-04-20",
            "qty": "100",
            "entry_price": "0.18",
            "fees": "0.01",
            "trade_type": "swing",
            "side": "short",
            "strategy_tag": "cash_put",
            "is_simulated": "0",
            "next": "/positions",
        },
    )

    assert response.status_code in (302, 303)
    assert "position_error=" in response.headers["Location"]
    assert portfolio.list_positions(include_closed=True) == []


@pytest.mark.requires_postgres
def test_cash_put_web_add_records_premium_and_darf_automatically() -> None:
    app = create_app()
    app.testing = True
    client = app.test_client()

    response = client.post(
        "/positions/add",
        data={
            "ticker": "PETRN312",
            "underlying": "PETR4",
            "trade_date": "2026-01-09",
            "qty": "400",
            "entry_price": "0.61",
            "fees": "0.33",
            "trade_type": "swing",
            "side": "long",
            "strategy_tag": "cash_put",
            "is_simulated": "0",
            "next": "/positions",
        },
    )

    assert response.status_code in (302, 303)
    positions = portfolio.list_positions(include_closed=True)
    assert len(positions) == 1
    assert positions[0]["side"] == "short"
    txs = finance.get_transactions(limit=20)
    by_type = {tx.type.value: tx.amount for tx in txs}
    assert round(by_type[finance.TransactionType.PREMIUM.value], 2) == 243.67
    assert round(by_type[finance.TransactionType.DARF.value], 2) == -36.55


@pytest.mark.requires_postgres
def test_cash_put_web_add_rolls_back_if_ledger_fails(monkeypatch) -> None:
    original_add_transaction = finance.add_transaction

    def _fail_on_darf(*args, **kwargs):
        if kwargs.get("type") == finance.TransactionType.DARF:
            raise RuntimeError("falha simulada no ledger")
        return original_add_transaction(*args, **kwargs)

    monkeypatch.setattr(finance, "add_transaction", _fail_on_darf)

    app = create_app()
    app.testing = True
    client = app.test_client()

    with pytest.raises(RuntimeError):
        client.post(
            "/positions/add",
            data={
                "ticker": "PETRN312",
                "underlying": "PETR4",
                "trade_date": "2026-01-09",
                "qty": "400",
                "entry_price": "0.61",
                "fees": "0.33",
                "trade_type": "swing",
                "side": "short",
                "strategy_tag": "cash_put",
                "is_simulated": "0",
                "next": "/positions",
            },
        )

    assert portfolio.list_positions(include_closed=True) == []
    assert finance.get_transactions(limit=20) == []


@pytest.mark.requires_postgres
def test_cash_put_expiration_without_confirmed_date_is_blocked() -> None:
    pos_id = portfolio.add_position(
        ticker="PETRN312",
        underlying="PETR4",
        trade_date="2026-01-09",
        qty=400,
        entry_price=0.61,
        fees=0.33,
        trade_type="swing",
        side="short",
        strategy_tag="cash_put",
    )

    app = create_app()
    app.testing = True
    client = app.test_client()

    response = client.post(
        "/finance/expire",
        data={"position_id": str(pos_id), "date": ""},
    )

    assert response.status_code in (302, 303)
    assert "position_error=" in response.headers["Location"]
    pos = portfolio.get_position(pos_id)
    assert pos is not None
    assert pos["status"] == "open"
