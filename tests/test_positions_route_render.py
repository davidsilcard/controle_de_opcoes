from __future__ import annotations

from opcoes.web import create_app


def test_positions_route_always_injects_realized_summary(monkeypatch) -> None:
    monkeypatch.setattr("opcoes.web.list_positions", lambda **_kwargs: [])
    monkeypatch.setattr(
        "opcoes.web.finance.get_premium_position_ids",
        lambda _position_ids: set(),
    )
    monkeypatch.setattr(
        "opcoes.web.summarize_realized_positions",
        lambda **_kwargs: {
            "available_years": [],
            "available_months": [],
            "selected_year": None,
            "selected_month": None,
            "overall_totals": {
                "count": 0,
                "total_net": 0.0,
                "total_profit": 0.0,
                "total_loss": 0.0,
                "profit_count": 0,
                "loss_count": 0,
                "breakeven_count": 0,
            },
            "period_totals": {
                "count": 0,
                "total_net": 0.0,
                "total_profit": 0.0,
                "total_loss": 0.0,
                "profit_count": 0,
                "loss_count": 0,
                "breakeven_count": 0,
            },
            "by_year": [],
            "by_month": [],
            "period_positions": [],
        },
    )

    app = create_app()
    app.testing = True
    client = app.test_client()

    response = client.get("/positions")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Resultados realizados" in html
    assert "Nenhuma posição registrada." in html

