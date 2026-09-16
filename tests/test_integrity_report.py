from __future__ import annotations

from types import SimpleNamespace

from opcoes.integrity_report import build_integrity_report


def test_integrity_report_classifies_and_deduplicates_findings() -> None:
    report = build_integrity_report(
        reconciliation_issues=[
            SimpleNamespace(
                position_id=8,
                ticker="PETRD521",
                code="PREMIO_DIVERGENTE",
                message="Prêmio não bate.",
            ),
            SimpleNamespace(
                position_id=99,
                ticker="#99",
                code="LEDGER_ORFAO",
                message="Sem posição.",
            ),
        ],
        position_issues=[
            SimpleNamespace(
                position_id=8,
                ticker="PETRD521",
                code="PREMIO_DIVERGENTE",
                message="Mesmo alerta por estratégia.",
                action="Revise a estratégia.",
            ),
            SimpleNamespace(
                position_id=7,
                ticker="GGBRD221",
                code="DUPLICIDADE_PROVAVEL",
                message="Possível repetição.",
                action="Confira a nota.",
            ),
            SimpleNamespace(
                position_id=6,
                ticker="CMIGP137",
                code="FECHADA_SEM_DATA",
                message="Data ausente.",
                action="Informe a data.",
            ),
        ],
        totals={
            "expected_premium": 100.0,
            "actual_premium": 90.0,
            "expected_darf": None,
            "actual_darf": -15.0,
            "expected_cash_net": 100.0,
            "actual_cash_net": 90.0,
            "expected_total_cash": 100.0,
            "actual_total_cash": 90.0,
            "expected_realized": 50.0,
            "actual_realized": 50.0,
            "unverifiable_darf_count": 1,
        },
    )

    assert report["counts"] == {
        "orphan": 1,
        "duplicate": 1,
        "state": 1,
        "divergence": 4,
    }
    assert report["unverifiable_darf_count"] == 1
    assert len([item for item in report["findings"] if item["code"] == "PREMIO_DIVERGENTE"]) == 1
    assert not any(item["code"] == "TOTAL_DARF_DIVERGENTE" for item in report["findings"])
