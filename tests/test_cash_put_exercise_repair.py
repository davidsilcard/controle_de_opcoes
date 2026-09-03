from __future__ import annotations

import pytest

from opcoes.cash_put_exercise_repair import (
    CashPutExerciseRepairError,
    build_cash_put_exercise_repair_plan,
)


def _position(**changes) -> dict:
    row = {
        "id": 51,
        "ticker": "CMIGQ135",
        "underlying": "CMIG4",
        "qty": 100,
        "status": "closed",
        "exit_date": "2026-05-18",
        "exit_reason": "Exercício",
        "strategy_tag": "cash_put",
        "is_simulated": 0,
        "contract_strike": None,
        "contract_exercise_strike": None,
    }
    row.update(changes)
    return row


def _holding(**changes) -> dict:
    row = {"id": 3, "ticker": "CMIG4", "quantity": 2400, "avg_price": 11.05, "is_simulated": 0}
    row.update(changes)
    return row


def _events() -> list[dict]:
    return [
        {
            "id": 4,
            "ticker": "CMIG4",
            "event_date": "2026-05-18",
            "event_type": "PUT_ASSIGNMENT",
            "qty_delta": 100,
            "quantity_before": 0,
            "quantity_after": 100,
            "avg_price_before": None,
            "avg_price_after": 13.14,
            "price_reference": 13.14,
            "fees": 0.0,
            "related_position_id": 51,
            "is_simulated": 0,
        },
        {
            "id": 11,
            "ticker": "CMIG4",
            "event_date": "2026-06-08",
            "event_type": "MANUAL_SET",
            "qty_delta": 200,
            "quantity_before": 100,
            "quantity_after": 300,
            "avg_price_before": 13.14,
            "avg_price_after": 11.61,
            "price_reference": 11.61,
            "fees": 0.0,
            "related_position_id": None,
            "is_simulated": 0,
        },
        {
            "id": 18,
            "ticker": "CMIG4",
            "event_date": "2026-08-20",
            "event_type": "PUT_ASSIGNMENT",
            "qty_delta": 2100,
            "quantity_before": 300,
            "quantity_after": 2400,
            "avg_price_before": 11.61,
            "avg_price_after": 11.05,
            "price_reference": 10.96,
            "fees": 0.0,
            "related_position_id": 66,
            "is_simulated": 0,
        },
        {
            "id": 19,
            "ticker": "CMIG4",
            "event_date": "2026-08-24",
            "event_type": "MANUAL_SET",
            "qty_delta": 0,
            "quantity_before": 2400,
            "quantity_after": 2400,
            "avg_price_before": 11.61,
            "avg_price_after": 11.05,
            "price_reference": 11.05,
            "fees": 0.0,
            "related_position_id": None,
            "is_simulated": 0,
        },
    ]


def _ledger() -> tuple[list[dict], list[dict]]:
    return (
        [{"id": 58, "date": "2026-05-18", "amount": -1314.0}],
        [{"id": 59, "date": "2026-05-18", "amount": 17.99}],
    )


def test_cash_put_exercise_plan_corrects_documented_date_cost_and_lineage() -> None:
    assignments, realized = _ledger()
    plan = build_cash_put_exercise_repair_plan(
        put_position=_position(),
        holding=_holding(),
        holding_events=_events(),
        assignment_transactions=assignments,
        realized_transactions=realized,
        exercise_date="2026-05-15",
        original_strike=13.38,
        exercise_strike=13.14,
        purchase_fees=7.65,
    )

    assert plan.assignment_amount == pytest.approx(-1321.65)
    assert plan.holding_events_rebased == (11, 19)
    assert plan.update_required is True


def test_cash_put_exercise_plan_is_idempotent_after_repair() -> None:
    assignments, realized = _ledger()
    assignments[0].update(date="2026-05-15", amount=-1321.65)
    realized[0]["date"] = "2026-05-15"
    events = _events()
    events[0].update(event_date="2026-05-15", price_reference=13.14, fees=7.65, avg_price_after=13.2165)
    events[1]["avg_price_before"] = 13.2165
    events[3]["avg_price_before"] = 11.05
    plan = build_cash_put_exercise_repair_plan(
        put_position=_position(exit_date="2026-05-15", contract_strike=13.38, contract_exercise_strike=13.14),
        holding=_holding(),
        holding_events=events,
        assignment_transactions=assignments,
        realized_transactions=realized,
        exercise_date="2026-05-15",
        original_strike=13.38,
        exercise_strike=13.14,
        purchase_fees=7.65,
    )

    assert plan.holding_events_rebased == ()
    assert plan.update_required is False


def test_cash_put_exercise_plan_blocks_a_broken_stock_chain() -> None:
    assignments, realized = _ledger()
    events = _events()
    events[1]["quantity_after"] = 301
    with pytest.raises(CashPutExerciseRepairError, match="quantidade incoerente"):
        build_cash_put_exercise_repair_plan(
            put_position=_position(),
            holding=_holding(),
            holding_events=events,
            assignment_transactions=assignments,
            realized_transactions=realized,
            exercise_date="2026-05-15",
            original_strike=13.38,
            exercise_strike=13.14,
            purchase_fees=7.65,
        )
