from __future__ import annotations

import pytest

from opcoes import finance, portfolio
from opcoes.web import create_app


pytestmark = pytest.mark.requires_postgres


def test_performance_page_renders_auditable_result_and_updates_legacy_contract() -> None:
    complete_id = portfolio.add_position(
        ticker="BBASS198",
        underlying="BBAS3",
        trade_date="2026-06-22",
        qty=100,
        entry_price=0.30,
        side="short",
        strategy_tag="cash_put",
        contract_strike=20.0,
        contract_expiry="2026-07-17",
        capital_committed=2000.0,
        capital_source="strike_x_quantidade",
        performance_source_ref="nota 1",
    )
    portfolio.close_position(
        position_id=complete_id,
        exit_date="2026-07-17",
        exit_price=0.0,
        exit_reason="Expirou",
    )
    finance.add_transaction(
        date="2026-06-22",
        type=finance.TransactionType.PREMIUM,
        amount=30.0,
        description="Prêmio teste",
        position_id=complete_id,
    )
    finance.sync_position_closure_effects(position_id=complete_id)

    legacy_id = portfolio.add_position(
        ticker="BBASS198",
        underlying="BBAS3",
        trade_date="2026-05-18",
        qty=100,
        entry_price=0.20,
        side="short",
        strategy_tag="cash_put",
    )
    portfolio.close_position(
        position_id=legacy_id,
        exit_date="2026-06-19",
        exit_price=0.0,
        exit_reason="Expirou",
    )

    app = create_app()
    app.testing = True
    client = app.test_client()

    page = client.get("/performance?mode=real")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert "Desempenho das Estratégias" in html
    assert f"#{legacy_id} BBASS198" in html

    response = client.post(
        f"/performance/contract/{legacy_id}",
        data={
            "mode": "real",
            "contract_strike": "19.50",
            "contract_expiry": "2026-06-19",
            "capital_committed": "1950.00",
            "performance_source_ref": "nota de corretagem 2",
        },
    )
    assert response.status_code in (302, 303)
    updated = portfolio.get_position(legacy_id)
    assert updated["contract_strike"] == pytest.approx(19.50)
    assert updated["contract_expiry"] == "2026-06-19"
    assert updated["capital_committed"] == pytest.approx(1950.0)
    assert updated["performance_source_ref"] == "nota de corretagem 2"
