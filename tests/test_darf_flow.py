from __future__ import annotations

import pytest

from opcoes import darf, finance, portfolio
from opcoes.web import create_app

pytestmark = pytest.mark.requires_postgres


def test_darf_generate_ignores_open_premium_provision_until_result_is_realized() -> None:
    app = create_app()
    app.testing = True
    client = app.test_client()

    res = client.post(
        "/positions/add",
        data={
            "ticker": "CMIGM100",
            "underlying": "CMIG4",
            "qty": "100",
            "entry_price": "1.00",
            "fees": "0",
            "trade_date": "2025-01-15",
            "trade_type": "swing",
            "strategy_tag": "cash_put",
            "contract_strike": "10.00",
            "contract_expiry": "2025-02-21",
            "performance_source_ref": "nota teste",
            "record_premium": "1",
            "reserve_darf": "1",
            "is_simulated": "0",
        },
    )
    assert res.status_code in (302, 303)

    balance_before = finance.get_balance(mode="real")
    assert abs(balance_before - 85.0) < 1e-6

    res = client.post("/darf/generate", data={"period": "2025-01", "is_simulated": "0"})
    assert res.status_code in (302, 303)

    rec = darf.get_month(period="2025-01", is_simulated=False)
    assert rec is None

    balance_after_generate = finance.get_balance(mode="real")
    assert abs(balance_after_generate - balance_before) < 1e-6


def test_darf_generate_and_pay_uses_realized_monthly_result() -> None:
    pos_id = portfolio.add_position(
        ticker="PETR4",
        underlying="PETR4",
        trade_date="2025-01-10",
        qty=100,
        entry_price=10.0,
        fees=0.0,
        trade_type="swing",
        side="long",
    )
    portfolio.update_position(
        position_id=pos_id,
        status="closed",
        exit_date="2025-01-20",
        exit_price=12.0,
    )
    finance.sync_position_closure_effects(position_id=pos_id)

    app = create_app()
    app.testing = True
    client = app.test_client()

    balance_before = finance.get_balance(mode="real")
    assert abs(balance_before - 0.0) < 1e-6

    res = client.post("/darf/generate", data={"period": "2025-01", "is_simulated": "0"})
    assert res.status_code in (302, 303)

    rec = darf.get_month(period="2025-01", is_simulated=False)
    assert rec is not None
    assert rec.due_date == "2025-02-28"
    assert abs(rec.amount - 30.0) < 1e-6
    assert rec.paid_date is None

    balance_after_generate = finance.get_balance(mode="real")
    assert abs(balance_after_generate - balance_before) < 1e-6

    res = client.post(
        "/darf/pay",
        data={
            "period": "2025-01",
            "is_simulated": "0",
            "paid_date": "2025-02-28",
        },
    )
    assert res.status_code in (302, 303)

    rec2 = darf.get_month(period="2025-01", is_simulated=False)
    assert rec2 is not None
    assert rec2.paid_date == "2025-02-28"
    assert abs((rec2.paid_amount or 0.0) - 30.0) < 1e-6

    balance_after_pay = finance.get_balance(mode="real")
    assert abs(balance_after_pay - balance_before) < 1e-6


def test_darf_simulated_mode_uses_loss_compensation() -> None:
    loss_id = portfolio.add_position(
        ticker="SIML3",
        underlying="SIML3",
        trade_date="2025-01-05",
        qty=10,
        entry_price=10.0,
        fees=0.0,
        trade_type="daytrade",
        side="long",
        is_simulated=True,
    )
    portfolio.update_position(
        position_id=loss_id,
        status="closed",
        exit_date="2025-01-20",
        exit_price=5.0,
    )
    finance.sync_position_closure_effects(position_id=loss_id)

    gain_id = portfolio.add_position(
        ticker="SIMG3",
        underlying="SIMG3",
        trade_date="2025-02-05",
        qty=10,
        entry_price=10.0,
        fees=0.0,
        trade_type="daytrade",
        side="long",
        is_simulated=True,
    )
    portfolio.update_position(
        position_id=gain_id,
        status="closed",
        exit_date="2025-02-20",
        exit_price=20.0,
    )
    finance.sync_position_closure_effects(position_id=gain_id)

    app = create_app()
    app.testing = True
    client = app.test_client()

    res = client.get("/darf?mode=simulated&period=2025-02")
    assert res.status_code == 200

    res = client.post("/darf/generate", data={"period": "2025-02", "is_simulated": "1"})
    assert res.status_code in (302, 303)

    rec = darf.get_month(period="2025-02", is_simulated=True)
    assert rec is not None
    # Day trade gain 100 less carryforward loss 50 => taxable 50, IR 20% = 10.
    assert abs(rec.amount - 10.0) < 1e-6

