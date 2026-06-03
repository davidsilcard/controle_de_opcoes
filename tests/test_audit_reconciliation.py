from __future__ import annotations

from opcoes import finance
from opcoes.audit_reconciliation import build_audit_reconciliation


def test_audit_reconciliation_requires_sell_for_exercised_covered_call() -> None:
    positions = [
        {
            "id": 54,
            "ticker": "GGBRE228",
            "underlying": "GGBR4",
            "trade_date": "2026-04-22",
            "qty": 800,
            "entry_price": 0.36,
            "fees": 0.37,
            "trade_type": "swing",
            "side": "short",
            "status": "closed",
            "exit_date": "2026-05-15",
            "exit_price": 0.0,
            "exit_reason": "Exercicio",
            "strategy_tag": "covered_call",
        }
    ]

    ctx = build_audit_reconciliation(
        positions,
        ledger_sums={
            54: {
                finance.TransactionType.PREMIUM.value: 287.63,
                finance.TransactionType.DARF.value: -43.14,
                finance.TransactionType.REALIZED.value: 287.63,
            }
        },
        include_closed=True,
        holding_events=[
            {
                "related_position_id": 54,
                "ticker": "GGBR4",
                "event_type": "CALL_EXERCISE",
                "qty_delta": -800,
                "price_reference": 22.57,
            }
        ],
    )

    row = ctx["rows"][0]
    assert row["expected_sell"] == 18056.0
    assert row["actual_sell"] is None
    assert row["diff_sell"] == -18056.0
    assert any(issue.code == "SELL_DIVERGENTE" for issue in ctx["audit_issues"])


def test_audit_reconciliation_accepts_call_exercise_sell_when_ledger_matches() -> None:
    positions = [
        {
            "id": 54,
            "ticker": "GGBRE228",
            "underlying": "GGBR4",
            "trade_date": "2026-04-22",
            "qty": 800,
            "entry_price": 0.36,
            "fees": 0.37,
            "trade_type": "swing",
            "side": "short",
            "status": "closed",
            "exit_date": "2026-05-15",
            "exit_price": 0.0,
            "exit_reason": "Exercicio",
            "strategy_tag": "covered_call",
        }
    ]

    ctx = build_audit_reconciliation(
        positions,
        ledger_sums={
            54: {
                finance.TransactionType.PREMIUM.value: 287.63,
                finance.TransactionType.DARF.value: -43.14,
                finance.TransactionType.SELL.value: 18056.0,
                finance.TransactionType.REALIZED.value: 287.63,
            }
        },
        include_closed=True,
        holding_events=[
            {
                "related_position_id": 54,
                "ticker": "GGBR4",
                "event_type": "CALL_EXERCISE",
                "qty_delta": -800,
                "price_reference": 22.57,
            }
        ],
    )

    row = ctx["rows"][0]
    assert row["diff_sell"] == 0.0
    assert not ctx["audit_issues"]


def test_audit_reconciliation_separates_long_option_buy_from_short_buyback() -> None:
    positions = [
        {
            "id": 57,
            "ticker": "KLBNK171",
            "underlying": "KLBN11",
            "trade_date": "2026-05-29",
            "qty": 100,
            "entry_price": 3.16,
            "fees": 0.40,
            "trade_type": "swing",
            "side": "long",
            "status": "open",
            "exit_date": None,
            "exit_price": None,
            "exit_reason": None,
            "strategy_tag": "ranking",
        }
    ]

    ctx = build_audit_reconciliation(
        positions,
        ledger_sums={57: {finance.TransactionType.BUY.value: -316.40}},
        include_closed=True,
    )

    row = ctx["rows"][0]
    assert row["expected_option_buy"] == -316.40
    assert row["actual_option_buy"] == -316.40
    assert row["expected_buyback"] is None
    assert row["actual_buyback"] is None
    assert row["diff_option_buy"] == 0.0
    assert not ctx["audit_issues"]
