from __future__ import annotations

from opcoes import portfolio


def test_summarize_realized_positions_uses_net_result_for_fiscal_totals(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "opcoes.portfolio.list_positions",
        lambda **_kwargs: [
            {
                "id": 6,
                "ticker": "PETRA456",
                "underlying": "PETR4",
                "trade_type": "swing",
                "strategy_tag": "ranking",
                "side": "long",
                "qty": 100,
                "exit_date": "2026-03-30",
                "exit_reason": "ajuste_manual",
                "realized_pl": 1005.0,
                "fees": 1.60,
                "pl": 1003.40,
                "irrf": 0.06,
            },
            {
                "id": 37,
                "ticker": "GGBRO215",
                "underlying": "GGBR4",
                "trade_type": "swing",
                "strategy_tag": "cash_put",
                "side": "short",
                "qty": 800,
                "exit_date": "2026-03-23",
                "exit_reason": "Exercício",
                "realized_pl": 608.0,
                "fees": 0.80,
                "pl": 607.20,
                "irrf": 0.0,
            },
        ],
    )

    summary = portfolio.summarize_realized_positions(
        selected_year=2026,
        selected_month=3,
    )

    assert summary["period_totals"]["count"] == 2
    assert summary["period_totals"]["total_gross"] == 1613.0
    assert summary["period_totals"]["total_fees"] == 2.4
    assert summary["period_totals"]["total_net"] == 1610.6

    march = summary["by_month"][0]
    assert march["period"] == "2026-03"
    assert march["total_gross"] == 1613.0
    assert march["total_fees"] == 2.4
    assert march["total_net"] == 1610.6

    assert summary["period_positions"][0]["ticker"] == "PETRA456"
    assert summary["period_positions"][0]["gross_result"] == 1005.0
    assert summary["period_positions"][0]["fees"] == 1.6
    assert summary["period_positions"][0]["net_result"] == 1003.4
