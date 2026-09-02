from __future__ import annotations

import pytest

from opcoes.finance import TransactionType
from opcoes.strategy_performance import build_strategy_performance


def _ledger(*, premium: float = 0.0, realized: float = 0.0, darf: float = 0.0) -> dict[str, float]:
    return {
        TransactionType.PREMIUM.value: premium,
        TransactionType.REALIZED.value: realized,
        TransactionType.DARF.value: darf,
    }


def test_cash_put_uses_realized_result_without_adding_premium_twice() -> None:
    positions = [
        {
            "id": 1,
            "ticker": "BBASS198",
            "underlying": "BBAS3",
            "strategy_tag": "cash_put",
            "side": "short",
            "status": "closed",
            "trade_date": "2026-06-22",
            "exit_date": "2026-07-17",
            "exit_reason": "Expirou",
            "qty": 300,
            "contract_strike": 19.39,
            "contract_expiry": "2026-07-17",
            "capital_committed": 5817.0,
            "is_simulated": False,
        }
    ]

    result = build_strategy_performance(
        positions,
        ledger_sums={1: _ledger(premium=83.89, realized=83.89, darf=-12.58)},
    )

    cycle = result["cycles"][0]
    assert cycle["total_result"] == 83.89
    assert cycle["capital"] == 5817.0
    assert cycle["capital_is_derived"] is False
    assert cycle["return_pct"] == round((83.89 / 5817.0) * 100.0, 4)
    assert result["totals"]["complete_result"] == 83.89
    assert result["totals"]["option_premium"] == 83.89
    assert result["totals"]["darf_provision"] == -12.58


def test_covered_call_exercise_includes_only_the_linked_stock_result() -> None:
    positions = [
        {
            "id": 10,
            "ticker": "PETRG405",
            "underlying": "PETR4",
            "strategy_tag": "covered_call",
            "side": "short",
            "status": "closed",
            "trade_date": "2026-06-22",
            "exit_date": "2026-07-17",
            "exit_reason": "Exercício",
            "qty": 100,
            "contract_strike": 37.35,
            "contract_expiry": "2026-07-17",
            "capital_committed": 3190.0,
            "is_simulated": False,
        },
        {
            "id": 11,
            "ticker": "PETR4",
            "underlying": "PETR4",
            "strategy_tag": "covered_call",
            "side": "long",
            "status": "closed",
            "exit_reason": "Exercício",
            "qty": 100,
            "pl": 546.0,
            "parent_position_id": 10,
            "is_simulated": False,
        },
        {
            "id": 12,
            "ticker": "PETR4",
            "underlying": "PETR4",
            "strategy_tag": "covered_call",
            "side": "long",
            "status": "closed",
            "exit_reason": "Exercício",
            "qty": 100,
            "pl": 999.0,
            "is_simulated": False,
        },
    ]

    result = build_strategy_performance(
        positions,
        ledger_sums={10: _ledger(premium=200.0, realized=200.0)},
    )

    cycle = result["cycles"][0]
    assert cycle["stock_result"] == 546.0
    assert cycle["total_result"] == 746.0
    assert result["totals"]["complete_result"] == 746.0


def test_open_cycle_does_not_dilute_closed_return_or_historical_coverage() -> None:
    positions = [
        {
            "id": 1,
            "ticker": "BBASS198",
            "underlying": "BBAS3",
            "strategy_tag": "cash_put",
            "side": "short",
            "status": "closed",
            "trade_date": "2026-06-22",
            "exit_date": "2026-07-17",
            "exit_reason": "Expirou",
            "qty": 100,
            "contract_strike": 20.0,
            "contract_expiry": "2026-07-17",
            "capital_committed": 2000.0,
            "is_simulated": False,
        },
        {
            "id": 2,
            "ticker": "BBASS198",
            "underlying": "BBAS3",
            "strategy_tag": "cash_put",
            "side": "short",
            "status": "open",
            "trade_date": "2026-08-20",
            "qty": 100,
            "contract_strike": 20.0,
            "contract_expiry": "2026-09-18",
            "capital_committed": 2000.0,
            "is_simulated": False,
        },
    ]

    result = build_strategy_performance(
        positions,
        ledger_sums={1: _ledger(realized=100.0), 2: _ledger(premium=50.0)},
    )

    assert result["totals"]["coverage_pct"] == 100.0
    assert result["totals"]["open_cycles"] == 1
    assert result["totals"]["weighted_return_pct"] == 5.0


def test_missing_legacy_contract_remains_visible_without_invented_return() -> None:
    positions = [
        {
            "id": 20,
            "ticker": "BBASS198",
            "underlying": "BBAS3",
            "strategy_tag": "cash_put",
            "side": "short",
            "status": "closed",
            "trade_date": "2026-06-22",
            "exit_date": "2026-07-17",
            "exit_reason": "Expirou",
            "qty": 100,
            "is_simulated": False,
        }
    ]

    result = build_strategy_performance(positions, ledger_sums={20: _ledger(realized=80.0)})

    cycle = result["cycles"][0]
    assert cycle["return_pct"] is None
    assert cycle["contract_missing_reasons"] == [
        "strike nao preservado",
        "vencimento nao preservado",
    ]
    assert cycle["return_base_missing_reasons"] == [
        "capital de garantia nao declarado"
    ]
    assert cycle["linkage_missing_reasons"] == []
    assert cycle["is_result_complete"] is True
    assert cycle["is_return_complete"] is False
    assert result["totals"]["complete_result"] == 80.0
    assert result["totals"]["return_result"] == 0.0
    assert result["totals"]["coverage_pct"] == 0.0


def test_documents_exhausted_remains_excluded_from_return_and_coverage() -> None:
    positions = [
        {
            "id": 21,
            "ticker": "PETRD521",
            "underlying": "PETR4",
            "strategy_tag": "covered_call",
            "side": "short",
            "status": "closed",
            "trade_date": "2026-04-06",
            "exit_date": "2026-04-17",
            "exit_reason": "Expiração",
            "qty": 100,
            "contract_strike": 52.15,
            "contract_expiry": "2026-04-17",
            "performance_evidence_state": "documents_exhausted",
            "performance_evidence_note": "Notas e extratos auditados; capital não comprovável.",
            "is_simulated": False,
        }
    ]

    result = build_strategy_performance(positions, ledger_sums={21: _ledger(realized=52.95)})

    cycle = result["cycles"][0]
    assert cycle["performance_evidence_state"] == "documents_exhausted"
    assert cycle["capital"] is None
    assert cycle["capital_is_derived"] is False
    assert cycle["is_complete"] is False
    assert cycle["return_pct"] is None
    assert result["totals"]["coverage_pct"] == 0.0


def test_shared_note_fee_is_warning_without_blocking_completion_or_return() -> None:
    positions = [
        {
            "id": 30,
            "ticker": "TAEEH392",
            "underlying": "TAEE11",
            "strategy_tag": "covered_call",
            "side": "short",
            "status": "closed",
            "trade_date": "2026-08-17",
            "exit_date": "2026-08-20",
            "exit_reason": "Exercicio",
            "qty": 400,
            "contract_strike": 37.35,
            "contract_expiry": "2026-08-21",
            "capital_committed": 13760.0,
            "shared_fee_pending": True,
            "shared_fee_note_ref": "BTG #33861523",
            "is_simulated": False,
        },
        {
            "id": 31,
            "ticker": "TAEE11",
            "underlying": "TAEE11",
            "strategy_tag": "covered_call",
            "side": "long",
            "status": "closed",
            "qty": 400,
            "pl": 0.0,
            "parent_position_id": 30,
            "is_simulated": False,
        },
    ]

    result = build_strategy_performance(
        positions,
        ledger_sums={30: _ledger(premium=167.79, realized=167.79)},
    )

    cycle = result["cycles"][0]
    assert cycle["is_complete"] is True
    assert cycle["is_result_complete"] is True
    assert cycle["is_return_complete"] is True
    assert cycle["return_pct"] == round((167.79 / 13760.0) * 100.0, 4)
    assert cycle["missing_reasons"] == []
    assert cycle["shared_fee_note_ref"] == "BTG #33861523"
    assert "taxas compartilhadas da nota sem rateio documental (BTG #33861523)" in cycle[
        "warning_reasons"
    ]
    assert result["incomplete_cycles"] == []
    assert [item["position_id"] for item in result["warning_cycles"]] == [30]
    assert result["totals"]["complete_cycles"] == 1
    assert result["totals"]["warning_cycles"] == 1


@pytest.mark.parametrize("persisted_capital", [None, 0, -1, "invalido"])
def test_cash_put_derives_non_positive_capital_from_strike_and_quantity(
    persisted_capital: object,
) -> None:
    position = {
        "id": 40,
        "ticker": "BBASS198",
        "underlying": "BBAS3",
        "strategy_tag": "cash_put",
        "side": "short",
        "status": "closed",
        "trade_date": "2026-06-22",
        "exit_date": "2026-07-17",
        "exit_reason": "Expirou",
        "qty": 300,
        "contract_strike": 19.39,
        "contract_expiry": "2026-07-17",
        "capital_committed": persisted_capital,
        "is_simulated": False,
    }

    result = build_strategy_performance(
        [position],
        ledger_sums={40: _ledger(realized=83.89)},
    )

    cycle = result["cycles"][0]
    assert cycle["capital"] == 5817.0
    assert cycle["capital_source"] == "strike_x_quantidade"
    assert cycle["capital_is_derived"] is True
    assert cycle["return_base_missing_reasons"] == []
    assert cycle["is_complete"] is True
    assert cycle["return_pct"] == round((83.89 / 5817.0) * 100.0, 4)
    assert position["capital_committed"] == persisted_capital


def test_contract_audit_is_independent_from_known_return_base() -> None:
    positions = [
        {
            "id": 50,
            "ticker": "PETRG405",
            "underlying": "PETR4",
            "strategy_tag": "covered_call",
            "side": "short",
            "status": "closed",
            "trade_date": "2026-06-22",
            "exit_date": "2026-07-17",
            "exit_reason": "Expirou",
            "qty": 100,
            "contract_strike": 37.35,
            "capital_committed": 3190.0,
            "is_simulated": False,
        }
    ]

    result = build_strategy_performance(
        positions,
        ledger_sums={50: _ledger(realized=80.0)},
    )

    cycle = result["cycles"][0]
    assert cycle["contract_missing_reasons"] == ["vencimento nao preservado"]
    assert cycle["return_base_missing_reasons"] == []
    assert cycle["linkage_missing_reasons"] == []
    assert cycle["is_contract_complete"] is False
    assert cycle["is_return_base_complete"] is True
    assert cycle["is_linkage_complete"] is True
    assert cycle["is_complete"] is False
    assert cycle["is_return_complete"] is True
    assert cycle["return_pct"] == round((80.0 / 3190.0) * 100.0, 4)
    assert result["totals"]["coverage_pct"] == 0.0
    assert result["totals"]["weighted_return_pct"] == cycle["return_pct"]


def test_exercised_call_linkage_blocks_result_and_return_only() -> None:
    positions = [
        {
            "id": 60,
            "ticker": "PETRG405",
            "underlying": "PETR4",
            "strategy_tag": "covered_call",
            "side": "short",
            "status": "closed",
            "trade_date": "2026-06-22",
            "exit_date": "2026-07-17",
            "exit_reason": "Exercicio",
            "qty": 100,
            "contract_strike": 37.35,
            "contract_expiry": "2026-07-17",
            "capital_committed": 3190.0,
            "is_simulated": False,
        }
    ]

    result = build_strategy_performance(
        positions,
        ledger_sums={60: _ledger(realized=200.0)},
    )

    cycle = result["cycles"][0]
    assert cycle["contract_missing_reasons"] == []
    assert cycle["return_base_missing_reasons"] == []
    assert cycle["linkage_missing_reasons"] == [
        "historico de acao da CALL exercida nao vinculado"
    ]
    assert cycle["is_contract_complete"] is True
    assert cycle["is_return_base_complete"] is True
    assert cycle["is_linkage_complete"] is False
    assert cycle["is_result_complete"] is False
    assert cycle["is_return_complete"] is False
    assert cycle["return_pct"] is None
    assert result["totals"]["complete_result"] == 0.0


@pytest.mark.parametrize(
    "second_ledger",
    [None, {TransactionType.PREMIUM.value: 50.0}],
)
def test_missing_realized_is_unknown_and_does_not_dilute_weighted_return(
    second_ledger: dict[str, float] | None,
) -> None:
    base_position = {
        "ticker": "BBASP226",
        "underlying": "BBAS3",
        "strategy_tag": "cash_put",
        "side": "short",
        "status": "closed",
        "trade_date": "2026-03-23",
        "exit_date": "2026-04-17",
        "exit_reason": "Expirou",
        "qty": 100,
        "contract_strike": 20.0,
        "contract_expiry": "2026-04-17",
        "is_simulated": False,
    }
    positions = [
        dict(base_position, id=70, capital_committed=2000.0),
        dict(base_position, id=71),
    ]
    ledger_sums = {70: _ledger(realized=100.0)}
    if second_ledger is not None:
        ledger_sums[71] = second_ledger

    result = build_strategy_performance(positions, ledger_sums=ledger_sums)

    unknown_cycle = next(
        cycle for cycle in result["cycles"] if cycle["position_id"] == 71
    )
    assert unknown_cycle["capital"] == 2000.0
    assert unknown_cycle["capital_is_derived"] is True
    assert unknown_cycle["option_result"] is None
    assert unknown_cycle["total_result"] is None
    assert unknown_cycle["return_pct"] is None
    assert unknown_cycle["annualized_return_pct"] is None
    assert unknown_cycle["is_result_complete"] is False
    assert unknown_cycle["is_return_complete"] is False
    summary = next(
        item for item in result["summaries"] if item["strategy"] == "cash_put"
    )
    for aggregate in (summary, result["totals"]):
        assert aggregate["result_complete_cycles"] == 1
        assert aggregate["return_complete_cycles"] == 1
        assert aggregate["complete_result"] == 100.0
        assert aggregate["return_result"] == 100.0
        assert aggregate["capital_sum"] == 2000.0
        assert aggregate["capital_days"] == 50000.0
        assert aggregate["weighted_return_pct"] == 5.0
        assert aggregate["annualized_return_pct"] == 73.0


def test_explicit_zero_realized_remains_known_and_counts_in_weighted_return() -> None:
    base_position = {
        "ticker": "BBASP226",
        "underlying": "BBAS3",
        "strategy_tag": "cash_put",
        "side": "short",
        "status": "closed",
        "trade_date": "2026-03-23",
        "exit_date": "2026-04-17",
        "exit_reason": "Expirou",
        "qty": 100,
        "contract_strike": 20.0,
        "contract_expiry": "2026-04-17",
        "is_simulated": False,
    }
    positions = [dict(base_position, id=80), dict(base_position, id=81)]

    result = build_strategy_performance(
        positions,
        ledger_sums={80: _ledger(realized=100.0), 81: _ledger(realized=0.0)},
    )

    zero_cycle = next(
        cycle for cycle in result["cycles"] if cycle["position_id"] == 81
    )
    assert zero_cycle["option_result"] == 0.0
    assert zero_cycle["total_result"] == 0.0
    assert zero_cycle["return_pct"] == 0.0
    assert zero_cycle["annualized_return_pct"] == 0.0
    assert zero_cycle["is_result_complete"] is True
    assert zero_cycle["is_return_complete"] is True
    assert result["totals"]["result_complete_cycles"] == 2
    assert result["totals"]["return_complete_cycles"] == 2
    assert result["totals"]["capital_sum"] == 4000.0
    assert result["totals"]["weighted_return_pct"] == 2.5
