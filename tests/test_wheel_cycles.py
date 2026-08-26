from __future__ import annotations

import pytest

from opcoes import finance, portfolio
from opcoes.wheel_cycles import (
    WheelCycleError,
    add_wheel_cycle_leg,
    build_wheel_backfill_plan,
    build_wheel_cycle_metrics,
    create_wheel_cycle,
)


def _ggbr_positions() -> dict[int, dict]:
    return {
        37: {
            "id": 37, "ticker": "GGBRO215", "underlying": "GGBR4", "qty": 800,
            "strategy_tag": "cash_put", "is_simulated": False, "trade_date": "2026-02-19",
            "exit_date": "2026-03-20", "exit_reason": "Exercício", "performance_source_ref": "Nota PUT",
        },
        43: {
            "id": 43, "ticker": "GGBR4", "underlying": "GGBR4", "qty": 800,
            "entry_price": 21.46, "fees": 0.0, "strategy_tag": "covered_call", "is_simulated": False,
            "trade_date": "2026-03-20", "parent_position_id": 37, "notes": "Exercício da PUT",
        },
        47: {
            "id": 47, "ticker": "GGBRD221", "underlying": "GGBR4", "qty": 800,
            "strategy_tag": "covered_call", "is_simulated": False, "trade_date": "2026-04-08",
            "exit_date": "2026-04-17", "exit_reason": "Expiração", "parent_position_id": 43,
        },
        54: {
            "id": 54, "ticker": "GGBRE228", "underlying": "GGBR4", "qty": 800,
            "strategy_tag": "covered_call", "is_simulated": False, "trade_date": "2026-04-22",
            "exit_date": "2026-05-15", "exit_reason": "Exercício", "parent_position_id": 43,
        },
        55: {
            "id": 55, "ticker": "GGBR4", "underlying": "GGBR4", "qty": 800,
            "entry_price": 20.73, "exit_price": 22.57, "fees": 0.0, "status": "closed",
            "strategy_tag": "covered_call", "is_simulated": False, "trade_date": "2026-05-15",
            "exit_date": "2026-05-15", "exit_reason": "Exercício", "parent_position_id": 54,
        },
    }


def test_ggbr4_wheel_regression_uses_acquisition_not_adjusted_stock_pm() -> None:
    positions = _ggbr_positions()
    cycle = {"id": 1, "underlying": "GGBR4", "is_simulated": False, "status": "closed", "opened_at": "2026-02-19"}
    legs = [
        {"id": 1, "leg_type": "put_origin", "position_id": 37, "quantity": 800},
        {"id": 2, "leg_type": "stock_acquisition", "position_id": 43, "quantity": 800},
        {"id": 3, "leg_type": "covered_call", "position_id": 47, "quantity": 800},
        {"id": 4, "leg_type": "covered_call", "position_id": 54, "quantity": 800},
        {"id": 5, "leg_type": "stock_exit", "position_id": 55, "quantity": 800},
    ]
    ledger = {
        37: {finance.TransactionType.PREMIUM.value: 607.20, finance.TransactionType.DARF.value: -91.08},
        47: {finance.TransactionType.PREMIUM.value: 39.96, finance.TransactionType.DARF.value: -5.99},
        54: {finance.TransactionType.PREMIUM.value: 287.63, finance.TransactionType.DARF.value: -43.14},
    }

    result = build_wheel_cycle_metrics(cycle, legs, positions_by_id=positions, ledger_sums=ledger)

    assert result["acquisition_cost"] == 17168.00
    assert result["sale_value"] == 18056.00
    assert result["premiums"] == 934.79
    assert result["result_before_darf"] == 1822.79
    assert result["capital_max"] == 17168.00
    assert result["return_pct"] == 10.6174
    assert result["official_darf"] == -140.21
    assert result["duration_days"] == 85


def test_backfill_accepts_only_the_unambiguous_ggbr_chain() -> None:
    positions = list(_ggbr_positions().values())

    plan = build_wheel_backfill_plan(positions)

    assert len(plan) == 1
    assert plan[0]["status"] == "ready"
    assert plan[0]["put_position_id"] == 37
    assert [(position["id"], leg_type) for position, leg_type in plan[0]["position_legs"]] == [
        (37, "put_origin"), (43, "stock_acquisition"), (47, "covered_call"),
        (54, "covered_call"), (55, "stock_exit"),
    ]


def _cmig_put_and_assignment() -> tuple[dict, dict]:
    return (
        {
            "id": 66, "ticker": "CMIGT111", "underlying": "CMIG4", "qty": 2100,
            "strategy_tag": "cash_put", "is_simulated": False, "trade_date": "2026-07-21",
            "exit_date": "2026-08-21", "exit_reason": "Exercício",
            "performance_source_ref": "Nota BTG 21/07/2026; exercício e despesas em 21/08/2026.",
        },
        {
            "id": 18, "ticker": "CMIG4", "event_date": "2026-08-21", "event_type": "PUT_ASSIGNMENT",
            "qty_delta": 2100, "price_reference": 10.96, "fees": 32.36,
            "related_position_id": 66, "is_simulated": False, "notes": "Exercício da PUT #66 confirmado.",
        },
    )


def test_open_cmig_wheel_uses_consolidated_assignment_without_realized_result() -> None:
    put, assignment = _cmig_put_and_assignment()
    cycle = {"id": 2, "underlying": "CMIG4", "is_simulated": False, "status": "open", "opened_at": "2026-07-21"}
    result = build_wheel_cycle_metrics(
        cycle,
        [
            {"id": 1, "leg_type": "put_origin", "position_id": 66, "quantity": 2100},
            {"id": 2, "leg_type": "stock_acquisition", "holding_event_id": 18, "quantity": 2100},
        ],
        positions_by_id={66: put},
        holding_events_by_id={18: assignment},
        ledger_sums={
            66: {
                finance.TransactionType.PREMIUM.value: 335.56,
                finance.TransactionType.DARF.value: -50.33,
            }
        },
    )

    assert result["premiums"] == 335.56
    assert result["acquisition_cost"] == 23048.36
    assert result["cash_flow_before_darf"] == -22712.80
    assert result["result_before_darf"] is None
    assert result["return_pct"] is None
    assert result["capital_max"] == 23048.36
    assert result["official_darf"] == -50.33
    assert result["legs"][1]["holding_event_id"] == 18
    assert result["legs"][1]["position_id"] is None


def test_backfill_accepts_confirmed_consolidated_put_assignment_as_open_cycle() -> None:
    put, assignment = _cmig_put_and_assignment()

    plan = build_wheel_backfill_plan([put], [assignment])

    assert len(plan) == 1
    assert plan[0]["status"] == "ready"
    assert plan[0]["put_position_id"] == 66
    assert plan[0]["position_legs"] == [(put, "put_origin")]
    assert plan[0]["holding_event_legs"] == [(assignment, "stock_acquisition")]


def test_exercised_call_cannot_consume_more_shares_than_the_cycle_acquired() -> None:
    positions = _ggbr_positions()
    positions[54] = {**positions[54], "qty": 900}
    cycle = {"id": 1, "underlying": "GGBR4", "is_simulated": False, "opened_at": "2026-02-19"}
    legs = [
        {"leg_type": "stock_acquisition", "position_id": 43, "quantity": 800},
        {"leg_type": "covered_call", "position_id": 54, "quantity": 900},
    ]

    with pytest.raises(WheelCycleError, match="consome mais acoes"):
        build_wheel_cycle_metrics(cycle, legs, positions_by_id=positions, ledger_sums={})


@pytest.mark.requires_postgres
def test_cycle_rejects_position_from_other_mode() -> None:
    put_id = portfolio.add_position(
        ticker="TESTP100", underlying="TEST4", trade_date="2026-01-01", qty=100,
        entry_price=1.0, side="short", strategy_tag="cash_put", is_simulated=True,
    )
    portfolio.close_position(
        position_id=put_id, exit_date="2026-01-15", exit_price=0.0, exit_reason="Exercício"
    )
    cycle_id = create_wheel_cycle(
        underlying="TEST4", is_simulated=False, opened_at="2026-01-01", source_ref="Nota de teste"
    )

    with pytest.raises(WheelCycleError, match="modos diferentes"):
        add_wheel_cycle_leg(
            cycle_id=cycle_id, leg_type="put_origin", position_id=put_id, quantity=100
        )
