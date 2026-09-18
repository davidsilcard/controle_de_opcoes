from __future__ import annotations

import pytest

from opcoes import portfolio
from opcoes.performance_evidence_repair import (
    PerformanceEvidenceRepairError,
    build_performance_evidence_repair_plan,
    repair_performance_evidence,
)


def _position(**changes) -> dict:
    row = {
        "id": 44,
        "ticker": "BBASP226",
        "side": "short",
        "strategy_tag": "cash_put",
        "contract_expiry": "2026-04-17",
        "contract_strike": None,
        "capital_committed": None,
    }
    row.update(changes)
    return row


def test_plan_requires_the_expected_ticker_and_expiry() -> None:
    plan = build_performance_evidence_repair_plan(
        position=_position(),
        expected_ticker="BBASP226",
        contract_strike=22.27,
        expected_expiry="2026-04-17",
    )

    assert plan.contract_update_required is True
    assert plan.capital_update_required is False

    with pytest.raises(PerformanceEvidenceRepairError, match="ticker esperado"):
        build_performance_evidence_repair_plan(
            position=_position(),
            expected_ticker="BBASP227",
            contract_strike=22.27,
            expected_expiry="2026-04-17",
        )

    with pytest.raises(PerformanceEvidenceRepairError, match="vencimento atual"):
        build_performance_evidence_repair_plan(
            position=_position(),
            expected_ticker="BBASP226",
            contract_strike=22.27,
            expected_expiry="2026-04-16",
        )


def test_plan_refuses_to_overwrite_a_different_value() -> None:
    with pytest.raises(PerformanceEvidenceRepairError, match="strike diferente"):
        build_performance_evidence_repair_plan(
            position=_position(contract_strike=23.27),
            expected_ticker="BBASP226",
            contract_strike=22.27,
            expected_expiry="2026-04-17",
        )


@pytest.mark.requires_postgres
def test_repair_persists_only_documented_metadata_and_is_idempotent() -> None:
    position_id = portfolio.add_position(
        ticker="GGBRD221",
        underlying="GGBR4",
        trade_date="2026-04-08",
        qty=800,
        entry_price=0.05,
        side="short",
        strategy_tag="covered_call",
        contract_expiry="2026-04-17",
    )

    report = repair_performance_evidence(
        position_id=position_id,
        expected_ticker="GGBRD221",
        contract_strike=22.03,
        expected_expiry="2026-04-17",
        contract_source_ref="Opções.net GGBRD221",
        capital_committed=17168.00,
        capital_source_ref="Histórico B3 GGBR4; posição vinculada #43",
    )
    assert report["applied"] is False
    assert report["update_required"] is True
    assert portfolio.get_position(position_id)["contract_strike"] is None

    applied = repair_performance_evidence(
        position_id=position_id,
        expected_ticker="GGBRD221",
        contract_strike=22.03,
        expected_expiry="2026-04-17",
        contract_source_ref="Opções.net GGBRD221",
        capital_committed=17168.00,
        capital_source_ref="Histórico B3 GGBR4; posição vinculada #43",
        apply=True,
    )
    assert applied["applied"] is True
    updated = portfolio.get_position(position_id)
    assert updated["contract_strike"] == pytest.approx(22.03)
    assert updated["capital_committed"] == pytest.approx(17168.00)
    assert updated["capital_source"] == "garantia_documentada"
    assert updated["capital_source_ref"] == "Histórico B3 GGBR4; posição vinculada #43"
    assert updated["performance_source_ref"] == "Opções.net GGBRD221"

    repeated = repair_performance_evidence(
        position_id=position_id,
        expected_ticker="GGBRD221",
        contract_strike=22.03,
        expected_expiry="2026-04-17",
        contract_source_ref="Opções.net GGBRD221",
        capital_committed=17168.00,
        capital_source_ref="Histórico B3 GGBR4; posição vinculada #43",
        apply=True,
    )
    assert repeated["applied"] is False
    assert repeated["update_required"] is False
