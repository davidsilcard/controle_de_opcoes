from __future__ import annotations

import re
from pathlib import Path

import pytest
from jinja2 import Environment, FileSystemLoader

from opcoes import finance
from opcoes.audit_reconciliation import build_audit_reconciliation


def test_audit_reconciliation_requires_sell_for_exercised_covered_call() -> None:
    positions = [
        {
            "id": 54,
            "ticker": "GGBRE228",
            "underlying": "GGBR4",
            "trade_date": "2026-04-22",
            "qty": 800,
            "entry_price": 0.36,
            "fees": 0.37,
            "trade_type": "swing",
            "side": "short",
            "status": "closed",
            "exit_date": "2026-05-15",
            "exit_price": 0.0,
            "exit_reason": "Exercicio",
            "strategy_tag": "covered_call",
        }
    ]

    ctx = build_audit_reconciliation(
        positions,
        ledger_sums={
            54: {
                finance.TransactionType.PREMIUM.value: 287.63,
                finance.TransactionType.DARF.value: -43.14,
                finance.TransactionType.REALIZED.value: 287.63,
            }
        },
        include_closed=True,
        holding_events=[
            {
                "related_position_id": 54,
                "ticker": "GGBR4",
                "event_type": "CALL_EXERCISE",
                "qty_delta": -800,
                "price_reference": 22.57,
            }
        ],
    )

    row = ctx["rows"][0]
    assert row["expected_sell"] == 18056.0
    assert row["actual_sell"] is None
    assert row["diff_sell"] == -18056.0
    assert any(issue.code == "SELL_DIVERGENTE" for issue in ctx["audit_issues"])


def test_audit_reconciliation_accepts_call_exercise_sell_when_ledger_matches() -> None:
    positions = [
        {
            "id": 54,
            "ticker": "GGBRE228",
            "underlying": "GGBR4",
            "trade_date": "2026-04-22",
            "qty": 800,
            "entry_price": 0.36,
            "fees": 0.37,
            "trade_type": "swing",
            "side": "short",
            "status": "closed",
            "exit_date": "2026-05-15",
            "exit_price": 0.0,
            "exit_reason": "Exercicio",
            "strategy_tag": "covered_call",
        }
    ]

    ctx = build_audit_reconciliation(
        positions,
        ledger_sums={
            54: {
                finance.TransactionType.PREMIUM.value: 287.63,
                finance.TransactionType.DARF.value: -43.14,
                finance.TransactionType.SELL.value: 18054.75,
                finance.TransactionType.REALIZED.value: 287.63,
            }
        },
        include_closed=True,
        holding_events=[
            {
                "related_position_id": 54,
                "ticker": "GGBR4",
                "event_type": "CALL_EXERCISE",
                "qty_delta": -800,
                "price_reference": 22.57,
                "fees": 1.25,
            }
        ],
    )

    row = ctx["rows"][0]
    assert row["diff_sell"] == 0.0
    assert row["sell_stock_fees"] == 1.25
    assert not ctx["audit_issues"]


def test_audit_reconciliation_includes_purchase_fees_in_put_assignment() -> None:
    positions = [
        {
            "id": 37,
            "ticker": "GGBRO215",
            "underlying": "GGBR4",
            "trade_date": "2026-02-19",
            "qty": 800,
            "entry_price": 0.76,
            "fees": 0.80,
            "trade_type": "swing",
            "side": "short",
            "status": "closed",
            "exit_date": "2026-03-20",
            "exit_price": 0.0,
            "exit_reason": "Exercicio",
            "strategy_tag": "cash_put",
        }
    ]

    ctx = build_audit_reconciliation(
        positions,
        ledger_sums={
            37: {
                finance.TransactionType.PREMIUM.value: 607.20,
                finance.TransactionType.DARF.value: -91.08,
                finance.TransactionType.ASSIGNMENT.value: -17171.20,
                finance.TransactionType.REALIZED.value: 607.20,
            }
        },
        include_closed=True,
        holding_events=[
            {
                "related_position_id": 37,
                "ticker": "GGBR4",
                "event_type": "PUT_ASSIGNMENT",
                "qty_delta": 800,
                "price_reference": 21.46,
                "fees": 3.20,
            }
        ],
    )

    row = ctx["rows"][0]
    assert row["expected_assignment"] == -17171.20
    assert row["diff_assignment"] == 0.0
    assert row["assignment_stock_fees"] == 3.20
    assert not ctx["audit_issues"]


def test_audit_reconciliation_separates_long_option_buy_from_short_buyback() -> None:
    positions = [
        {
            "id": 57,
            "ticker": "KLBNK171",
            "underlying": "KLBN11",
            "trade_date": "2026-05-29",
            "qty": 100,
            "entry_price": 3.16,
            "fees": 0.40,
            "trade_type": "swing",
            "side": "long",
            "status": "open",
            "exit_date": None,
            "exit_price": None,
            "exit_reason": None,
            "strategy_tag": "ranking",
        }
    ]

    ctx = build_audit_reconciliation(
        positions,
        ledger_sums={57: {finance.TransactionType.BUY.value: -316.40}},
        include_closed=True,
    )

    row = ctx["rows"][0]
    assert row["expected_option_buy"] == -316.40
    assert row["actual_option_buy"] == -316.40
    assert row["expected_buyback"] is None
    assert row["actual_buyback"] is None
    assert row["diff_option_buy"] == 0.0
    assert not ctx["audit_issues"]


def test_audit_reconciliation_accepts_legacy_stock_lot_for_put_assignment() -> None:
    positions = [
        {
            "id": 37,
            "ticker": "GGBRO215",
            "underlying": "GGBR4",
            "trade_date": "2026-02-19",
            "qty": 800,
            "entry_price": 0.76,
            "fees": 0.80,
            "trade_type": "swing",
            "side": "short",
            "status": "closed",
            "exit_date": "2026-03-20",
            "exit_price": 0.0,
            "exit_reason": "Exercicio",
            "strategy_tag": "cash_put",
        },
        {
            "id": 43,
            "ticker": "GGBR4",
            "underlying": "GGBR4",
            "trade_date": "2026-03-20",
            "qty": 800,
            "entry_price": 21.46,
            "fees": 0.0,
            "trade_type": "stock",
            "side": "long",
            "status": "closed",
            "exit_date": "2026-05-15",
            "exit_price": None,
            "exit_reason": "Consolidado no exercicio da call",
            "strategy_tag": "covered_call",
            "parent_position_id": 37,
        },
    ]

    ctx = build_audit_reconciliation(
        positions,
        ledger_sums={
            37: {
                finance.TransactionType.PREMIUM.value: 607.20,
                finance.TransactionType.DARF.value: -91.08,
                finance.TransactionType.ASSIGNMENT.value: -17168.0,
                finance.TransactionType.REALIZED.value: 607.20,
            }
        },
        include_closed=True,
        holding_events=[],
    )

    put_row = next(row for row in ctx["rows"] if row["id"] == 37)
    assert put_row["expected_assignment"] == -17168.0
    assert put_row["diff_assignment"] == 0.0
    assert not ctx["audit_issues"]


def _shared_fee_position() -> dict:
    return {
        "id": 60,
        "ticker": "BBASS198",
        "underlying": "BBAS3",
        "trade_date": "2026-06-22",
        "qty": 300,
        "entry_price": 0.28,
        "fees": 0.0,
        "trade_type": "swing",
        "side": "short",
        "status": "closed",
        "exit_date": "2026-07-17",
        "exit_price": 0.0,
        "exit_reason": "Expiracao",
        "strategy_tag": "cash_put",
        "shared_fee_pending": True,
        "shared_fee_note_ref": "Nota BTG #32674228",
        "is_simulated": False,
    }


@pytest.mark.parametrize("actual_darf", [-12.58, -9999.0, None])
def test_shared_note_fee_does_not_certify_darf_or_dependent_cash_values(
    actual_darf: float | None,
) -> None:
    ctx = build_audit_reconciliation(
        [_shared_fee_position()],
        ledger_sums={
            60: {
                finance.TransactionType.PREMIUM.value: 84.0,
                finance.TransactionType.DARF.value: actual_darf,
                finance.TransactionType.REALIZED.value: 84.0,
            }
        },
        include_closed=True,
    )

    row = ctx["rows"][0]
    assert row["shared_fee_unallocated"] is True
    assert row["shared_fee_note_ref"] == "Nota BTG #32674228"
    assert row["actual_darf"] == actual_darf
    for metric in ("darf", "net", "cash_net", "total_cash"):
        assert row[f"expected_{metric}"] is None
        assert row[f"diff_{metric}"] is None
        assert ctx["totals"][f"expected_{metric}"] is None
        assert ctx["totals"][f"diff_{metric}"] is None
    for metric in ("net", "cash_net", "total_cash"):
        assert row[f"actual_{metric}"] == pytest.approx(84.0 + (actual_darf or 0.0))
        assert ctx["totals"][f"actual_{metric}"] == pytest.approx(
            84.0 + (actual_darf or 0.0)
        )
    assert ctx["totals"]["actual_darf"] == (actual_darf or 0.0)
    assert ctx["totals"]["unverifiable_darf_count"] == 1
    assert not ctx["audit_issues"]


def test_shared_fee_uncertainty_propagates_to_mixed_totals_only() -> None:
    known_position = {
        **_shared_fee_position(),
        "id": 61,
        "qty": 100,
        "entry_price": 0.50,
        "shared_fee_pending": False,
    }
    ctx = build_audit_reconciliation(
        [_shared_fee_position(), known_position],
        ledger_sums={
            60: {"PREMIUM": 84.0, "DARF": -9999.0, "REALIZED": 84.0},
            61: {"PREMIUM": 50.0, "DARF": -7.50, "REALIZED": 50.0},
        },
        include_closed=True,
    )

    known_row = next(row for row in ctx["rows"] if row["id"] == 61)
    assert known_row["shared_fee_unallocated"] is False
    assert known_row["expected_darf"] == -7.50
    assert known_row["diff_darf"] == 0.0
    assert known_row["expected_total_cash"] == 42.50
    assert known_row["diff_total_cash"] == 0.0
    assert ctx["totals"]["expected_premium"] == 134.0
    assert ctx["totals"]["actual_darf"] == -10006.50
    assert ctx["totals"]["actual_total_cash"] == -9872.50
    for metric in ("darf", "net", "cash_net", "total_cash"):
        assert ctx["totals"][f"expected_{metric}"] is None
        assert ctx["totals"][f"diff_{metric}"] is None


def test_shared_fee_darf_uncertainty_does_not_certify_exercise_total() -> None:
    position = {**_shared_fee_position(), "exit_reason": "Exercicio"}
    ctx = build_audit_reconciliation(
        [position],
        ledger_sums={
            60: {
                "PREMIUM": 84.0,
                "DARF": -9999.0,
                "ASSIGN": -5955.0,
                "REALIZED": 84.0,
            }
        },
        include_closed=True,
        holding_events=[
            {
                "related_position_id": 60,
                "ticker": "BBAS3",
                "event_type": "PUT_ASSIGNMENT",
                "qty_delta": 300,
                "price_reference": 19.85,
            }
        ],
    )

    row = ctx["rows"][0]
    assert row["expected_assignment"] == -5955.0
    assert row["diff_assignment"] == 0.0
    assert row["actual_total_cash"] == -15870.0
    assert row["expected_total_cash"] is None
    assert row["diff_total_cash"] is None
    assert ctx["totals"]["expected_total_cash"] is None
    assert ctx["totals"]["diff_total_cash"] is None
    assert not ctx["audit_issues"]


def test_shared_fee_flag_does_not_hide_unexpected_darf_for_long_option() -> None:
    position = {
        **_shared_fee_position(),
        "ticker": "KLBNK171",
        "underlying": "KLBN11",
        "side": "long",
        "strategy_tag": "ranking",
        "status": "open",
        "exit_date": None,
        "exit_price": None,
        "exit_reason": None,
        "qty": 100,
        "entry_price": 3.16,
    }
    ctx = build_audit_reconciliation(
        [position],
        ledger_sums={60: {"BUY": -316.0, "DARF": -9999.0}},
        include_closed=True,
    )

    row = ctx["rows"][0]
    assert row["shared_fee_unallocated"] is False
    assert row["expected_darf"] is None
    assert row["diff_darf"] == -9999.0
    assert ctx["totals"]["unverifiable_darf_count"] == 0
    assert ctx["totals"]["expected_darf"] == 0.0
    assert ctx["totals"]["diff_darf"] == -9999.0
    assert any(issue.code == "DARF_DIVERGENTE" for issue in ctx["audit_issues"])


def test_darf_remains_verifiable_without_shared_fee_pending() -> None:
    position = {**_shared_fee_position(), "shared_fee_pending": False}
    ctx = build_audit_reconciliation(
        [position],
        ledger_sums={60: {"PREMIUM": 84.0, "DARF": -9999.0, "REALIZED": 84.0}},
        include_closed=True,
    )

    row = ctx["rows"][0]
    assert row["shared_fee_unallocated"] is False
    assert row["expected_darf"] == -12.60
    assert row["diff_darf"] == -9986.40
    assert any(issue.code == "DARF_DIVERGENTE" for issue in ctx["audit_issues"])


def test_audit_template_marks_unverifiable_darf_without_green_reconciliation() -> None:
    ctx = build_audit_reconciliation(
        [_shared_fee_position()],
        ledger_sums={60: {"PREMIUM": 84.0, "DARF": -9999.0, "REALIZED": 84.0}},
        include_closed=True,
    )
    templates = Path(__file__).resolve().parents[1] / "opcoes" / "templates"
    template = Environment(
        loader=FileSystemLoader(templates), autoescape=True
    ).get_template("audit.html")
    html = template.render(
        **ctx, mode="real", include_closed=True, inventory_summary=[]
    )

    assert "Provisão DARF não verificável por falta de rateio" in html
    assert "não é certificado como correto" in html
    assert "Nota BTG #32674228" in html
    assert "A Auditoria encontrou regras quebradas" not in html
    assert html.count('<span class="text-muted">Não verificável</span>') == 16
    table_row = next(
        row for row in re.findall(r"<tr>(.*?)</tr>", html, flags=re.DOTALL)
        if "<td>60</td>" in row
    )
    cells = re.findall(r"<td\b[^>]*>.*?</td>", table_row, flags=re.DOTALL)
    assert "-9999.00" in cells[12]
    for index in (11, 13, 26, 28, 29, 31, 32, 34):
        assert "Não verificável" in cells[index]
        assert "text-success" not in cells[index]
        assert "0.00" not in cells[index]
