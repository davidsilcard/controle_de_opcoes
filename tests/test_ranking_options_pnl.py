from __future__ import annotations

from opcoes import finance
from opcoes.strategies.ranking import build_ranking_options_pnl_summary


def test_ranking_options_pnl_summary_separates_closed_profit_loss_and_open_cost() -> None:
    positions = [
        {
            "id": 1,
            "ticker": "PETRA456",
            "underlying": "PETR4",
            "strategy_tag": "ranking",
            "side": "long",
            "status": "closed",
            "trade_date": "2025-11-19",
            "exit_date": "2026-03-30",
            "qty": 100,
            "entry_price": 1.95,
            "exit_price": 12.0,
            "fees": 1.60,
        },
        {
            "id": 2,
            "ticker": "VALEA80",
            "underlying": "VALE3",
            "strategy_tag": "ranking",
            "side": "long",
            "status": "closed",
            "trade_date": "2026-01-10",
            "exit_date": "2026-02-10",
            "qty": 100,
            "entry_price": 0.90,
            "exit_price": 0.20,
            "fees": 0.20,
        },
        {
            "id": 3,
            "ticker": "ITUBE542",
            "underlying": "ITUB4",
            "strategy_tag": "ranking",
            "side": "long",
            "status": "open",
            "trade_date": "2025-11-19",
            "qty": 100,
            "entry_price": 2.33,
            "fees": 0.0,
        },
        {
            "id": 4,
            "ticker": "BBASQ237",
            "underlying": "BBAS3",
            "strategy_tag": "cash_put",
            "side": "short",
            "status": "closed",
            "trade_date": "2026-04-20",
            "qty": 500,
            "entry_price": 0.40,
        },
    ]
    ledger_sums = {
        1: {
            finance.TransactionType.BUY.value: -195.0,
            finance.TransactionType.REALIZED.value: 1003.40,
        },
        2: {
            finance.TransactionType.BUY.value: -90.0,
            finance.TransactionType.REALIZED.value: -70.20,
        },
        3: {finance.TransactionType.BUY.value: -233.0},
    }

    summary = build_ranking_options_pnl_summary(positions, ledger_sums=ledger_sums)

    assert summary["closed_count"] == 2
    assert summary["open_count"] == 1
    assert summary["closed_entry_cost"] == 285.0
    assert summary["open_cost"] == 233.0
    assert summary["profit"] == 1003.40
    assert summary["loss"] == -70.20
    assert summary["realized"] == 933.20
    assert summary["win_rate_pct"] == 50.0
    assert [row["ticker"] for row in summary["closed_rows"]] == ["PETRA456", "VALEA80"]
    assert [row["ticker"] for row in summary["open_rows"]] == ["ITUBE542"]


def test_ranking_options_pnl_summary_respects_option_type_filter() -> None:
    positions = [
        {
            "id": 1,
            "ticker": "ITUBE542",
            "underlying": "ITUB4",
            "strategy_tag": "ranking",
            "side": "long",
            "status": "open",
            "trade_date": "2025-11-19",
            "qty": 100,
            "entry_price": 2.33,
        },
        {
            "id": 2,
            "ticker": "BBASN235",
            "underlying": "BBAS3",
            "strategy_tag": "ranking",
            "side": "long",
            "status": "open",
            "trade_date": "2026-01-28",
            "qty": 100,
            "entry_price": 0.40,
        },
    ]

    summary = build_ranking_options_pnl_summary(
        positions,
        ledger_sums={
            1: {finance.TransactionType.BUY.value: -233.0},
            2: {finance.TransactionType.BUY.value: -40.0},
        },
        option_type_filter="CALL",
    )

    assert summary["open_count"] == 1
    assert summary["open_cost"] == 233.0
    assert summary["by_type"]["CALL"]["open_count"] == 1
    assert summary["by_type"]["PUT"]["open_count"] == 0
