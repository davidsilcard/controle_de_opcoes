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


def test_performance_separates_shared_fee_and_preserves_confirmed_contract_fields() -> None:
    shared_id = portfolio.add_position(
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
        performance_source_ref="nota compartilhada",
        shared_fee_pending=True,
        shared_fee_note_ref="Nota BTG #1",
    )
    portfolio.close_position(
        position_id=shared_id,
        exit_date="2026-07-17",
        exit_price=0.0,
        exit_reason="Expirou",
    )
    finance.add_transaction(
        date="2026-06-22",
        type=finance.TransactionType.PREMIUM,
        amount=30.0,
        description="Prêmio compartilhado",
        position_id=shared_id,
    )
    finance.sync_position_closure_effects(position_id=shared_id)

    partial_id = portfolio.add_position(
        ticker="BBASP226",
        underlying="BBAS3",
        trade_date="2026-03-23",
        qty=100,
        entry_price=0.20,
        side="short",
        strategy_tag="cash_put",
        contract_expiry="2026-04-17",
        performance_source_ref="nota comprovada",
    )
    portfolio.close_position(
        position_id=partial_id,
        exit_date="2026-04-17",
        exit_price=0.0,
        exit_reason="Expirou",
    )

    app = create_app()
    app.testing = True
    client = app.test_client()

    html = client.get("/performance?mode=real").get_data(as_text=True)
    assert "Confirmações com evidência pendente" in html
    assert "Aguardando rateio da corretora" in html
    assert f"/performance/contract/{shared_id}" not in html
    assert f"/performance/contract/{partial_id}" in html
    assert "Strike pendente" in html
    assert 'name="contract_expiry"' not in html

    response = client.post(
        f"/performance/contract/{partial_id}",
        data={
            "mode": "real",
            "contract_strike": "22.61",
            "capital_committed": "2261.00",
        },
    )
    assert response.status_code in (302, 303)
    updated = portfolio.get_position(partial_id)
    assert updated["contract_strike"] == pytest.approx(22.61)
    assert updated["capital_committed"] == pytest.approx(2261.0)
    assert updated["contract_expiry"] == "2026-04-17"
    assert updated["performance_source_ref"] == "nota comprovada"


def test_performance_accepts_expiry_evidence_without_unproven_strike_or_capital() -> None:
    partial_id = portfolio.add_position(
        ticker="PETRD521",
        underlying="PETR4",
        trade_date="2026-04-06",
        qty=100,
        entry_price=0.53,
        side="short",
        strategy_tag="covered_call",
    )
    portfolio.close_position(
        position_id=partial_id,
        exit_date="2026-04-17",
        exit_price=0.0,
        exit_reason="Expirou",
    )

    app = create_app()
    app.testing = True
    client = app.test_client()
    response = client.post(
        f"/performance/contract/{partial_id}",
        data={
            "mode": "real",
            "contract_expiry": "2026-04-17",
            "performance_source_ref": "Calendário oficial B3 — abril/2026",
        },
    )

    assert response.status_code in (302, 303)
    updated = portfolio.get_position(partial_id)
    assert updated["contract_strike"] is None
    assert updated["capital_committed"] is None
    assert updated["contract_expiry"] == "2026-04-17"
    assert updated["performance_source_ref"] == "Calendário oficial B3 — abril/2026"
