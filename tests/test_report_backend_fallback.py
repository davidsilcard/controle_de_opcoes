from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from opcoes.report import generate_report


def _setup_minimal_report_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            """
            CREATE TABLE option_snapshots (
                snapshot_date TEXT NOT NULL,
                ticker TEXT,
                underlying TEXT,
                option_type TEXT,
                "score_total" TEXT,
                "trend_flag" TEXT,
                "underlying_price_date" TEXT,
                "dias_uteis" TEXT,
                "Status_Moneyness" TEXT,
                "Status_Liquidez" TEXT,
                "Status_2x" TEXT,
                "iv_score" TEXT,
                "em2x_score" TEXT,
                "delta" TEXT,
                "ultimo" TEXT,
                "underlying_price" TEXT,
                "%_Alta_p_2x" TEXT,
                "custo_pct" TEXT,
                "intrinsic_value" TEXT,
                "extrinsic_value" TEXT,
                "extrinsic_pct_spot" TEXT,
                "breakeven_price" TEXT,
                "breakeven_dist_pct" TEXT,
                "vol_fluxo_5d" TEXT,
                "num_fluxo_5d" TEXT,
                "iv_rank_180d" TEXT,
                "vol_impl_perc" TEXT,
                "best_bid" TEXT,
                "best_ask" TEXT,
                "spread_pct" TEXT,
                "preco_teorico" TEXT,
                "distorcao_preco_pct" TEXT,
                "distorcao_flag" TEXT,
                "illiquidez_flag" TEXT,
                "Status_Remoto" TEXT,
                "prob_itm_pct" TEXT,
                "prob_itm_delta_pct" TEXT,
                "prob_be_pct" TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE underlying_snapshots (
                underlying TEXT,
                snapshot_date TEXT,
                price REAL
            )
            """
        )
        conn.execute(
            """
            INSERT INTO option_snapshots (
                snapshot_date, ticker, underlying, option_type, "score_total", "trend_flag",
                "underlying_price_date", "dias_uteis", "Status_Moneyness", "Status_Liquidez",
                "Status_2x", "iv_score", "em2x_score", "delta", "ultimo", "underlying_price",
                "%_Alta_p_2x", "custo_pct", "intrinsic_value", "extrinsic_value",
                "extrinsic_pct_spot", "breakeven_price", "breakeven_dist_pct", "vol_fluxo_5d",
                "num_fluxo_5d", "iv_rank_180d", "vol_impl_perc", "best_bid", "best_ask",
                "spread_pct", "preco_teorico", "distorcao_preco_pct", "distorcao_flag",
                "illiquidez_flag", "Status_Remoto", "prob_itm_pct", "prob_itm_delta_pct", "prob_be_pct"
            )
            VALUES (
                '2026-02-26', 'ABCDK123', 'ABCD3', 'CALL', '8.5', '1',
                '2026-02-26', '25', 'ITM', 'Alta', 'OK', '2', '2', '0.70', '1.25', '20.00',
                '10.0', '5.0', '0.0', '1.25', '6.25', '21.25', '6.25', '100000',
                '10', '15.0', '20.0', '1.20', '1.30',
                '8.0', '1.28', '1.0', '', '', '', '', '', ''
            )
            """
        )
        conn.execute(
            """
            INSERT INTO underlying_snapshots (underlying, snapshot_date, price)
            VALUES ('ABCD3', '2026-02-26', 20.0)
            """
        )
        conn.commit()
    finally:
        conn.close()


class _FailingPostgresConnection:
    backend = "postgres"

    def execute(self, _query, _params=()):
        raise RuntimeError("postgres query failed")

    def close(self) -> None:
        return None


def test_report_falls_back_to_sqlite_when_postgres_connection_fails(
    monkeypatch, tmp_path: Path
) -> None:
    db_path = tmp_path / "report.db"
    _setup_minimal_report_db(db_path)
    monkeypatch.setenv("OPCOES_DB_PATH", str(db_path))
    monkeypatch.setenv("OPCOES_DB_BACKEND", "postgres")
    monkeypatch.setattr("opcoes.report._connect_postgres", lambda: (_ for _ in ()).throw(RuntimeError("boom")))

    data = generate_report(min_score=8, limit=10, recurring_days=30, recurring_limit=10)

    assert data.snapshot_date == "2026-02-26"
    assert len(data.opportunities) == 1


def test_report_falls_back_to_sqlite_when_postgres_query_fails(
    monkeypatch, tmp_path: Path
) -> None:
    db_path = tmp_path / "report.db"
    _setup_minimal_report_db(db_path)
    monkeypatch.setenv("OPCOES_DB_PATH", str(db_path))
    monkeypatch.setenv("OPCOES_DB_BACKEND", "postgres")
    monkeypatch.setattr("opcoes.report._connect_postgres", lambda: _FailingPostgresConnection())

    data = generate_report(min_score=8, limit=10, recurring_days=30, recurring_limit=10)

    assert data.snapshot_date == "2026-02-26"
    assert len(data.opportunities) == 1


def test_report_does_not_fallback_when_postgres_strict_mode_enabled(
    monkeypatch, tmp_path: Path
) -> None:
    db_path = tmp_path / "report.db"
    _setup_minimal_report_db(db_path)
    monkeypatch.setenv("OPCOES_DB_PATH", str(db_path))
    monkeypatch.setenv("OPCOES_DB_BACKEND", "postgres")
    monkeypatch.setenv("OPCOES_POSTGRES_STRICT", "1")
    monkeypatch.setattr(
        "opcoes.report._connect_postgres",
        lambda: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    with pytest.raises(RuntimeError, match="boom"):
        generate_report(min_score=8, limit=10, recurring_days=30, recurring_limit=10)
