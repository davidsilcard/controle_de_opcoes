from __future__ import annotations

import math

from opcoes import finance, portfolio
from opcoes.scraper.snapshots import SnapshotDB
from opcoes.strategies.covered_call import get_covered_call_context


def _ensure_snapshot_tables(db_path) -> None:
    snap = SnapshotDB(db_path)
    snap.close()


def test_covered_call_context_exposes_monthly_premium_and_operational_results(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "covered_call_finance.db"
    monkeypatch.setenv("OPCOES_DB_PATH", str(db_path))
    _ensure_snapshot_tables(db_path)

    pos_id = portfolio.add_position(
        ticker="BBASN235",
        underlying="BBAS3",
        trade_date="2026-01-28",
        qty=600,
        entry_price=0.33,
        fees=4.61,
        trade_type="swing",
        side="short",
        strategy_tag="covered_call",
    )

    premium_amount = finance.calculate_option_premium(entry_price=0.33, qty=600, fees=4.61)
    finance.recalc_position_premium_and_darf(
        position_id=pos_id,
        trade_date="2026-01-28",
        ticker="BBASN235",
        qty=600,
        premium_amount=premium_amount,
        trade_type="swing",
        is_simulated=False,
    )
    portfolio.update_position(
        position_id=pos_id,
        status="closed",
        exit_date="2026-02-18",
        exit_price=0.01,
        exit_reason="recompra_encerramento",
    )
    finance.sync_short_option_buyback(
        position_id=pos_id,
        ticker="BBASN235",
        qty=600,
        partial_qty=None,
        status="closed",
        exit_date="2026-02-18",
        exit_price=0.01,
        is_simulated=False,
    )

    ctx = get_covered_call_context({"underlying": "BBAS3"})

    assert "monthly_premiums" in ctx
    assert "monthly_operational_result" in ctx
    assert ctx["monthly_premiums"]
    assert ctx["monthly_operational_result"]

    monthly_premium = {row["month"]: float(row["total"]) for row in ctx["monthly_premiums"]}
    monthly_oper = {row["month"]: float(row["total"]) for row in ctx["monthly_operational_result"]}

    # PREMIUM + DARF lançados na data de abertura.
    assert math.isclose(monthly_premium["2026-01"], 164.38, abs_tol=1e-6)
    # Resultado operacional inclui recompra lançada em 2026-02.
    assert math.isclose(monthly_oper["2026-01"], 164.38, abs_tol=1e-6)
    assert math.isclose(monthly_oper["2026-02"], -6.0, abs_tol=1e-6)
