from __future__ import annotations

import pytest

from opcoes import finance, holdings, portfolio
from opcoes.audit_reconciliation import build_audit_reconciliation
from opcoes.tax import build_position_tax_events


def _closed_position():
    return dict(id=73, ticker="KLBNJ196", underlying="KLBN11", qty=1000,
                entry_price=0.34, fees=0.44, buyback_fees=0.07,
                trade_date="2026-09-21", exit_date="2026-09-25",
                exit_price=0.06, status="closed", side="short",
                strategy_tag="covered_call", trade_type="swing")


def test_buyback_fee_reconciles_without_changing_premium():
    pos = _closed_position()
    assert build_position_tax_events(pos)[0].amount == 279.49
    ctx = build_audit_reconciliation([pos], ledger_sums={73: {
        finance.TransactionType.PREMIUM.value: 339.56,
        finance.TransactionType.DARF.value: -50.93,
        finance.TransactionType.BUY.value: -60.07,
        finance.TransactionType.REALIZED.value: 279.49,
    }}, include_closed=True)
    row = ctx["rows"][0]
    assert row["expected_premium"] == 339.56
    assert row["expected_buyback"] == -60.07
    assert row["diff_buyback"] == 0
    assert not ctx["audit_issues"]


@pytest.mark.requires_postgres
def test_postgres_buyback_fee_persisted_and_repeat_is_idempotent():
    holdings.upsert_holding(ticker="KLBN11", quantity=1000, avg_price=17.96,
        is_simulated=False, event_date="2026-09-21")
    pid = portfolio.add_position(ticker="KLBNJ196", underlying="KLBN11",
        trade_date="2026-09-21", qty=1000, entry_price=0.34, fees=0.44,
        side="short", strategy_tag="covered_call")
    finance.recalc_position_premium_and_darf(position_id=pid,
        trade_date="2026-09-21", ticker="KLBNJ196", qty=1000,
        premium_amount=339.56, trade_type="swing", is_simulated=False)
    assert holdings.get_holding_snapshot(ticker="KLBN11", is_simulated=False)["shares_reserved"] == 1000
    portfolio.update_position(position_id=pid, status="closed",
        exit_date="2026-09-25", exit_price=0.06,
        exit_reason="recompra_encerramento", buyback_fees=0.07)
    for _ in range(2):
        synced = finance.sync_position_closure_effects(position_id=pid)
        assert synced["buyback"] == -60.07
        assert synced["realized"]["close"] == 279.49
    pos = portfolio.get_position(pid)
    assert pos["fees"] == 0.44
    assert pos["buyback_fees"] == 0.07
    assert pos["pl"] == pytest.approx(279.49)
    summary = portfolio.summarize_realized_positions()
    assert summary["period_positions"][0]["fees"] == 0.51
    assert finance.get_balance(mode="real") == pytest.approx(228.56)
    stock = holdings.get_holding_snapshot(ticker="KLBN11", is_simulated=False)
    assert stock["shares_reserved"] == 0
    assert stock["shares_free"] == 1000
