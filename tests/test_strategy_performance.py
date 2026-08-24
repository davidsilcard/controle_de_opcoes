from __future__ import annotations

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

    assert result["cycles"][0]["return_pct"] is None
    assert "strike nao preservado" in result["cycles"][0]["missing_reasons"]
    assert result["totals"]["complete_result"] == 0.0
    assert result["totals"]["coverage_pct"] == 0.0
