from __future__ import annotations

import pytest

from opcoes.strategy_contracts import (
    StrategyContractError,
    validate_position_closure_update,
    validate_position_identity_update,
)


def _covered_call_position() -> dict:
    return {
        "ticker": "WIZCB103",
        "underlying": "WIZC3",
        "trade_date": "2026-02-05",
        "qty": 300,
        "entry_price": 0.23,
        "trade_type": "swing",
        "side": "short",
        "strategy_tag": "covered_call",
        "is_simulated": 0,
        "parent_position_id": None,
    }


def test_position_identity_contract_allows_same_strategy_identity() -> None:
    existing = _covered_call_position()
    proposed = {
        **existing,
        "status": "closed",
        "exit_date": "2026-02-18",
        "exit_price": 0.01,
        "exit_reason": "recompra_encerramento",
    }

    validate_position_identity_update(existing=existing, proposed=proposed)


def test_position_identity_contract_blocks_strategy_reclassification() -> None:
    existing = _covered_call_position()
    proposed = {**existing, "strategy_tag": "ranking"}

    with pytest.raises(StrategyContractError, match="estrategia"):
        validate_position_identity_update(existing=existing, proposed=proposed)


def test_position_identity_contract_blocks_side_change() -> None:
    existing = _covered_call_position()
    proposed = {**existing, "side": "long"}

    with pytest.raises(StrategyContractError, match="posicao"):
        validate_position_identity_update(existing=existing, proposed=proposed)


def test_position_identity_contract_allows_unstrategized_stock_underlying_correction() -> None:
    existing = {
        "ticker": "HYPE3",
        "underlying": "",
        "trade_date": "2026-02-19",
        "qty": 300,
        "entry_price": 26.14,
        "trade_type": "swing",
        "side": "long",
        "strategy_tag": "",
        "is_simulated": 0,
        "parent_position_id": None,
    }
    proposed = {**existing, "underlying": "HYPE4"}

    validate_position_identity_update(existing=existing, proposed=proposed)


def test_position_closure_contract_blocks_cash_put_exercise_from_positions_table() -> None:
    existing = {
        "ticker": "BBASQ237",
        "underlying": "BBAS3",
        "status": "open",
        "strategy_tag": "cash_put",
    }
    proposed = {
        "status": "closed",
        "exit_reason": "Exercício",
    }

    with pytest.raises(StrategyContractError, match="botao de exercicio"):
        validate_position_closure_update(existing=existing, proposed=proposed)


def test_position_closure_contract_allows_short_option_buyback() -> None:
    existing = {
        "ticker": "WIZCB103",
        "underlying": "WIZC3",
        "status": "open",
        "strategy_tag": "covered_call",
    }
    proposed = {
        "status": "closed",
        "exit_reason": "recompra_encerramento",
    }

    validate_position_closure_update(existing=existing, proposed=proposed)
