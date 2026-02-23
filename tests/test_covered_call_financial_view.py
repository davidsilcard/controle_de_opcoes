from __future__ import annotations

import math
import sqlite3

from opcoes import finance, portfolio
from opcoes.scraper.snapshots import SnapshotDB
from opcoes.scraper.storage import CSV_FIELDS
from opcoes.strategies.covered_call import get_covered_call_context


def _ensure_snapshot_tables(db_path) -> None:
    snap = SnapshotDB(db_path)
    snap.close()


def _build_option_row(
    *,
    underlying: str,
    ticker: str,
    option_type: str,
    strike: str,
    best_bid: str,
    underlying_price: str = "45,01",
    dist_perc_strike: str = "3,00",
    extrinsic_pct_spot: str = "1,20",
    dias_uteis: str = "19",
) -> dict:
    row = {col: "" for col in CSV_FIELDS}
    row.update(
        {
            "underlying": underlying,
            "ticker": ticker,
            "option_type": option_type,
            "vencimento": "20/03/2026",
            "dias_uteis": dias_uteis,
            "strike": strike,
            "ultimo": best_bid,
            "best_bid": best_bid,
            "dist_perc_strike": dist_perc_strike,
            "extrinsic_pct_spot": extrinsic_pct_spot,
            "underlying_price": underlying_price,
            "score_total": "4,00",
        }
    )
    return row


def _insert_underlying_snapshot(db_path, *, snapshot_date: str, underlying: str, price: float) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO underlying_snapshots
            (snapshot_date, underlying, price, price_date)
            VALUES (?, ?, ?, ?)
            """,
            (snapshot_date, underlying, float(price), snapshot_date),
        )
        conn.commit()
    finally:
        conn.close()


def _seed_taee_target_scenario(
    db_path,
    *,
    bid_440: str = "1,20",
    bid_465: str = "4,00",
) -> None:
    portfolio.add_position(
        ticker="TAEE11",
        underlying="TAEE11",
        trade_date="2026-02-19",
        qty=400,
        entry_price=34.4,
        trade_type="stock",
        side="long",
        is_simulated=False,
    )

    snap = SnapshotDB(db_path)
    snap.record_options(
        "2026-02-20",
        [
            _build_option_row(
                underlying="TAEE11",
                ticker="TAEEC440",
                option_type="CALL",
                strike="46,01",
                best_bid=bid_440,
            ),
            _build_option_row(
                underlying="TAEE11",
                ticker="TAEEC465",
                option_type="CALL",
                strike="46,51",
                best_bid=bid_465,
            ),
        ],
    )
    snap.close()
    _insert_underlying_snapshot(
        db_path,
        snapshot_date="2026-02-20",
        underlying="TAEE11",
        price=45.01,
    )


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


def test_covered_call_context_exposes_underlying_quick_filter(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "covered_call_quick_filter.db"
    monkeypatch.setenv("OPCOES_DB_PATH", str(db_path))
    _ensure_snapshot_tables(db_path)

    portfolio.add_position(
        ticker="PETR4",
        underlying="PETR4",
        trade_date="2026-02-01",
        qty=200,
        entry_price=31.9,
        trade_type="stock",
        side="long",
        is_simulated=False,
    )
    portfolio.add_position(
        ticker="VALE3",
        underlying="VALE3",
        trade_date="2026-02-02",
        qty=100,
        entry_price=62.95,
        trade_type="stock",
        side="long",
        is_simulated=True,
    )
    portfolio.add_position(
        ticker="PETRC999",
        underlying="PETR4",
        trade_date="2026-02-03",
        qty=100,
        entry_price=0.75,
        side="short",
        strategy_tag="covered_call",
        is_simulated=False,
    )
    portfolio.add_position(
        ticker="HYPE3",
        underlying="",
        trade_date="2026-02-04",
        qty=300,
        entry_price=26.14,
        trade_type="stock",
        side="long",
        strategy_tag="estoque",
        is_simulated=False,
    )
    portfolio.add_position(
        ticker="WICZ3",
        underlying="WIZC3",
        trade_date="2026-02-05",
        qty=300,
        entry_price=7.16,
        trade_type="stock",
        side="long",
        strategy_tag="estoque",
        is_simulated=False,
    )

    ctx = get_covered_call_context({"underlying": "PETR4"})
    quick_filter = ctx["underlying_quick_filter"]
    tickers = [row["ticker"] for row in quick_filter]

    assert tickers[0] == "PETR4"
    assert "VALE3" in tickers
    assert "HYPE3" in tickers
    assert "WICZ3" in tickers

    petr4 = next(row for row in quick_filter if row["ticker"] == "PETR4")
    vale3 = next(row for row in quick_filter if row["ticker"] == "VALE3")
    hype3 = next(row for row in quick_filter if row["ticker"] == "HYPE3")
    wicz3 = next(row for row in quick_filter if row["ticker"] == "WICZ3")

    assert petr4["qty_real"] == 200
    assert petr4["qty_simulated"] == 0
    assert petr4["qty_total"] == 200
    assert petr4["has_open_calls"] is True

    assert vale3["qty_real"] == 0
    assert vale3["qty_simulated"] == 100
    assert vale3["qty_total"] == 100

    assert hype3["qty_real"] == 300
    assert hype3["qty_total"] == 300
    assert wicz3["qty_real"] == 300
    assert wicz3["qty_total"] == 300


def test_covered_call_context_uses_max_price_target_for_suggestions(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "covered_call_target.db"
    monkeypatch.setenv("OPCOES_DB_PATH", str(db_path))
    _ensure_snapshot_tables(db_path)
    _seed_taee_target_scenario(db_path)

    ctx = get_covered_call_context(
        {
            "underlying": "TAEE11",
            "min_extrinsic": "0.5",
            "min_days": "10",
            "max_days": "90",
            "min_dist_strike": "2.0",
            "target_upside_pct": "12",
        }
    )

    target = ctx["sell_target"]
    assert math.isclose(float(target["avg_free_price"]), 34.4, abs_tol=1e-6)
    assert math.isclose(float(target["spot_price"]), 45.01, abs_tol=1e-6)
    assert math.isclose(float(target["base_price"]), 45.01, abs_tol=1e-6)
    assert math.isclose(float(target["target_price"]), 50.4112, abs_tol=1e-6)

    suggestions = ctx["suggestions"]
    assert suggestions
    assert suggestions[0]["ticker"] == "TAEEC465"
    assert suggestions[0]["target_hit"] is True
    assert suggestions[0]["best_flag"] is True
    assert math.isclose(float(suggestions[0]["premium_pct_base"]), 8.8869, rel_tol=1e-3)
    assert math.isclose(float(suggestions[0]["meta_advantage_pct"]), 0.1960, rel_tol=1e-2)
    assert suggestions[1]["ticker"] == "TAEEC440"
    assert suggestions[1]["target_hit"] is False
    assert math.isclose(float(suggestions[1]["premium_pct_base"]), 2.6661, rel_tol=1e-3)
    assert math.isclose(float(suggestions[1]["meta_advantage_pct"]), -6.3513, rel_tol=1e-2)


def test_covered_call_context_filters_only_target_hits_and_persists_choice(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "covered_call_only_hits.db"
    monkeypatch.setenv("OPCOES_DB_PATH", str(db_path))
    _ensure_snapshot_tables(db_path)
    _seed_taee_target_scenario(db_path)

    ctx = get_covered_call_context(
        {
            "underlying": "TAEE11",
            "min_extrinsic": "0.5",
            "min_days": "10",
            "max_days": "90",
            "min_dist_strike": "2.0",
            "target_upside_pct": "12",
            "only_target_hits": "1",
        }
    )

    assert ctx["filters"]["only_target_hits"] is True
    assert [s["ticker"] for s in ctx["suggestions"]] == ["TAEEC465"]
    assert ctx["sell_target"]["hits_count"] == 1

    reopen_ctx = get_covered_call_context({})
    assert reopen_ctx["filters"]["only_target_hits"] is True
    assert [s["ticker"] for s in reopen_ctx["suggestions"]] == ["TAEEC465"]


def test_covered_call_context_only_hits_can_return_empty_table(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "covered_call_only_hits_empty.db"
    monkeypatch.setenv("OPCOES_DB_PATH", str(db_path))
    _ensure_snapshot_tables(db_path)
    _seed_taee_target_scenario(db_path, bid_440="0,91", bid_465="0,70")

    ctx = get_covered_call_context(
        {
            "underlying": "TAEE11",
            "min_extrinsic": "0.5",
            "min_days": "10",
            "max_days": "90",
            "min_dist_strike": "2.0",
            "target_upside_pct": "12",
            "only_target_hits": "1",
        }
    )

    assert ctx["filters"]["only_target_hits"] is True
    assert ctx["sell_target"]["hits_count"] == 0
    assert ctx["suggestions"] == []


def test_covered_call_context_extrinsic_filter_uses_premium_ref_basis(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "covered_call_extrinsic_ref.db"
    monkeypatch.setenv("OPCOES_DB_PATH", str(db_path))
    _ensure_snapshot_tables(db_path)

    portfolio.add_position(
        ticker="TAEE11",
        underlying="TAEE11",
        trade_date="2026-02-19",
        qty=400,
        entry_price=34.4,
        trade_type="stock",
        side="long",
        is_simulated=False,
    )

    snap = SnapshotDB(db_path)
    snap.record_options(
        "2026-02-20",
        [
            _build_option_row(
                underlying="TAEE11",
                ticker="TAEEC465",
                option_type="CALL",
                strike="46,51",
                best_bid="0,09",
                # Dado inconsistente de snapshot: alto no CSV, mas prêmio ref baixo.
                extrinsic_pct_spot="5,00",
            ),
            _build_option_row(
                underlying="TAEE11",
                ticker="TAEEC470",
                option_type="CALL",
                strike="47,01",
                best_bid="0,60",
                # Dado inconsistente oposto: baixo no CSV, mas prêmio ref alto.
                extrinsic_pct_spot="0,10",
            ),
        ],
    )
    snap.close()
    _insert_underlying_snapshot(
        db_path,
        snapshot_date="2026-02-20",
        underlying="TAEE11",
        price=45.01,
    )

    ctx = get_covered_call_context(
        {
            "underlying": "TAEE11",
            "min_extrinsic": "1.0",
            "min_days": "10",
            "max_days": "90",
            "min_dist_strike": "2.0",
            "target_upside_pct": "12",
        }
    )

    # Com base no prêmio ref:
    # - TAEEC465: 0.09 / 45.01 = ~0.20% (deve cair fora)
    # - TAEEC470: 0.60 / 45.01 = ~1.33% (deve passar)
    suggestions = ctx["suggestions"]
    assert [s["ticker"] for s in suggestions] == ["TAEEC470"]
    assert math.isclose(float(suggestions[0]["extrinsic_pct_spot"]), 1.3330, rel_tol=1e-3)
