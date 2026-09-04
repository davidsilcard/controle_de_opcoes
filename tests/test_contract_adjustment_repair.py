from __future__ import annotations

import pytest

from opcoes.contract_adjustment_repair import (
    ContractAdjustmentRepairError,
    build_contract_adjustment_repair_plan,
)


def _position(**changes) -> dict:
    row = {
        "id": 53,
        "ticker": "PETRE500",
        "side": "short",
        "strategy_tag": "covered_call",
        "contract_strike": None,
        "contract_adjusted_strike": None,
        "contract_adjustment_date": None,
    }
    row.update(changes)
    return row


def test_contract_adjustment_plan_records_original_and_adjusted_strikes() -> None:
    plan = build_contract_adjustment_repair_plan(
        position=_position(),
        original_strike=50.00,
        adjusted_strike=49.46,
        adjustment_date="2026-04-23",
    )

    assert plan.position_id == 53
    assert plan.update_required is True


def test_contract_adjustment_plan_is_idempotent() -> None:
    plan = build_contract_adjustment_repair_plan(
        position=_position(
            contract_strike=50.00,
            contract_adjusted_strike=49.46,
            contract_adjustment_date="2026-04-23",
        ),
        original_strike=50.00,
        adjusted_strike=49.46,
        adjustment_date="2026-04-23",
    )

    assert plan.update_required is False


def test_contract_adjustment_rejects_a_long_option() -> None:
    with pytest.raises(ContractAdjustmentRepairError, match="opções vendidas"):
        build_contract_adjustment_repair_plan(
            position=_position(side="long"),
            original_strike=50.00,
            adjusted_strike=49.46,
            adjustment_date="2026-04-23",
        )
