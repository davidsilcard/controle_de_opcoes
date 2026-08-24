from __future__ import annotations

import pytest

from opcoes.put_assignment_pm_repair import (
    PutAssignmentPmRepairError,
    build_put_assignment_pm_repair_plan,
)


def _put() -> dict:
    return {
        "id": 66,
        "ticker": "CMIGT111",
        "underlying": "CMIG4",
        "qty": 2100,
        "status": "closed",
        "exit_date": "2026-08-21",
        "exit_reason": "Exercicio",
        "strategy_tag": "cash_put",
        "is_simulated": 0,
    }


def _holding(*, quantity: int = 2400, avg_price: float = 11.61) -> dict:
    return {
        "id": 3,
        "ticker": "CMIG4",
        "quantity": quantity,
        "avg_price": avg_price,
        "is_simulated": 0,
    }


def _event(*, average_after: float = 11.61) -> dict:
    return {
        "id": 18,
        "ticker": "CMIG4",
        "event_type": "PUT_ASSIGNMENT",
        "event_date": "2026-08-21",
        "qty_delta": 2100,
        "quantity_before": 300,
        "quantity_after": 2400,
        "avg_price_before": 11.61,
        "avg_price_after": average_after,
        "price_reference": 10.96,
        "fees": 32.36,
        "is_simulated": 0,
    }


def test_put_assignment_pm_repair_plan_calculates_weighted_average() -> None:
    plan = build_put_assignment_pm_repair_plan(
        put_position=_put(), holding=_holding(), holding_events=[_event()]
    )

    expected = round(((300 * 11.61) + (2100 * 10.96) + 32.36) / 2400, 2)
    assert plan.corrected_avg_price == pytest.approx(expected)
    assert plan.update_required is True


def test_put_assignment_pm_repair_plan_is_idempotent_after_correction() -> None:
    expected = round(((300 * 11.61) + (2100 * 10.96) + 32.36) / 2400, 2)
    plan = build_put_assignment_pm_repair_plan(
        put_position=_put(),
        holding=_holding(avg_price=expected),
        holding_events=[_event(average_after=expected)],
    )

    assert plan.update_required is False


def test_put_assignment_pm_repair_blocks_holding_with_later_movements() -> None:
    with pytest.raises(PutAssignmentPmRepairError, match="movimentos posteriores"):
        build_put_assignment_pm_repair_plan(
            put_position=_put(), holding=_holding(quantity=2500), holding_events=[_event()]
        )
