from __future__ import annotations

import pytest

from opcoes.exercise_fee_repair import (
    ExerciseFeeRepairError,
    build_covered_call_exercise_fee_repair_plan,
)


def _call_position() -> dict:
    return {
        "id": 67,
        "ticker": "TAEEH392",
        "underlying": "TAEE11",
        "qty": 400,
        "status": "closed",
        "exit_date": "2026-08-21",
        "exit_reason": "Exercicio",
        "strategy_tag": "covered_call",
        "is_simulated": 0,
    }


def _stock_position(*, fees: float = 21.01) -> dict:
    return {
        "id": 68,
        "ticker": "TAEE11",
        "qty": 400,
        "status": "closed",
        "exit_date": "2026-08-21",
        "exit_reason": "Exercicio",
        "exit_price": 37.35,
        "fees": fees,
        "strategy_tag": "covered_call",
        "is_simulated": 0,
    }


def _event(*, fees: float = 0.0) -> dict:
    return {
        "id": 17,
        "ticker": "TAEE11",
        "event_type": "CALL_EXERCISE",
        "event_date": "2026-08-21",
        "qty_delta": -400,
        "price_reference": 37.35,
        "fees": fees,
        "is_simulated": 0,
    }


def _sell(*, amount: float = 14940.0) -> dict:
    return {
        "id": 107,
        "date": "2026-08-21",
        "type": "SELL",
        "amount": amount,
        "is_simulated": 0,
    }


def test_covered_call_fee_repair_plan_updates_only_legacy_values() -> None:
    plan = build_covered_call_exercise_fee_repair_plan(
        call_position=_call_position(),
        stock_position=_stock_position(),
        holding_events=[_event()],
        sell_transactions=[_sell()],
        sale_fees="21,01",
    )

    assert plan.gross_sale == 14940.0
    assert plan.net_sale == 14918.99
    assert plan.update_holding_event is True
    assert plan.update_sell_ledger is True
    assert plan.changes_required is True


def test_covered_call_fee_repair_plan_is_idempotent_after_repair() -> None:
    plan = build_covered_call_exercise_fee_repair_plan(
        call_position=_call_position(),
        stock_position=_stock_position(),
        holding_events=[_event(fees=21.01)],
        sell_transactions=[_sell(amount=14918.99)],
        sale_fees=21.01,
    )

    assert plan.changes_required is False


def test_covered_call_fee_repair_rejects_fee_that_disagrees_with_stock_history() -> None:
    with pytest.raises(ExerciseFeeRepairError, match="historico fiscal"):
        build_covered_call_exercise_fee_repair_plan(
            call_position=_call_position(),
            stock_position=_stock_position(fees=20.0),
            holding_events=[_event()],
            sell_transactions=[_sell()],
            sale_fees=21.01,
        )


def test_covered_call_fee_repair_rejects_ambiguous_sell_ledger() -> None:
    with pytest.raises(ExerciseFeeRepairError, match="exatamente um SELL"):
        build_covered_call_exercise_fee_repair_plan(
            call_position=_call_position(),
            stock_position=_stock_position(),
            holding_events=[_event()],
            sell_transactions=[_sell(), _sell()],
            sale_fees=21.01,
        )
