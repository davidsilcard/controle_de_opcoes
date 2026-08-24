from __future__ import annotations

import pytest

from opcoes import finance, portfolio
from opcoes.holdings import (
    apply_put_assignment_to_holding,
    get_holding_snapshot,
    upsert_holding,
)
from opcoes.scraper.snapshots import SnapshotDB
from opcoes.web import create_app

pytestmark = pytest.mark.requires_postgres


def _ensure_snapshot_tables() -> None:
    snap = SnapshotDB()
    snap.close()


def test_put_assignment_updates_consolidated_stock_and_surfaces_audit_summary() -> None:
    _ensure_snapshot_tables()

    pos_id = portfolio.add_position(
        ticker="GGBRO215",
        underlying="GGBR4",
        trade_date="2026-03-17",
        qty=800,
        entry_price=0.76,
        fees=0.0,
        trade_type="swing",
        side="short",
        strategy_tag="cash_put",
    )
    finance.recalc_position_premium_and_darf(
        position_id=pos_id,
        trade_date="2026-03-17",
        ticker="GGBRO215",
        qty=800,
        premium_amount=finance.calculate_option_premium(
            entry_price=0.76,
            qty=800,
            fees=0.0,
        ),
        trade_type="swing",
        is_simulated=False,
    )

    app = create_app()
    app.testing = True
    client = app.test_client()

    response = client.post(
        "/finance/assign",
        data={
            "position_id": str(pos_id),
            "qty": "800",
            "strike": "21.46",
            "date": "2026-03-20",
            "purchase_fees": "3.20",
        },
    )
    assert response.status_code in (302, 303)

    put_pos = portfolio.get_position(pos_id)
    assert put_pos is not None
    assert (put_pos.get("status") or "").lower() == "closed"
    assert "exerc" in (put_pos.get("exit_reason") or "").lower()

    holding = get_holding_snapshot(ticker="GGBR4", is_simulated=False)
    assert int(holding.get("shares_total") or 0) == 800
    assert float(holding.get("avg_price") or 0.0) == pytest.approx((17168.0 + 3.20) / 800)
    assert int(holding.get("shares_reserved") or 0) == 0

    assignment_txs = [
        tx
        for tx in finance.get_transactions(limit=20, strategy_tag="cash_put")
        if tx.position_id == pos_id and tx.type == finance.TransactionType.ASSIGNMENT
    ]
    assert len(assignment_txs) == 1
    assert assignment_txs[0].date == "2026-03-20"
    assert assignment_txs[0].amount == pytest.approx(-17171.20)
    assert "despesas da compra: R$ 3.20" in assignment_txs[0].description

    audit_response = client.get("/audit?mode=real&include_closed=1")
    assert audit_response.status_code == 200
    audit_html = audit_response.get_data(as_text=True)
    assert "Exercicio (caixa)" in audit_html
    assert "GGBR4 800" in audit_html
    assert "-17171.20" in audit_html

    ccp_response = client.get("/cash-covered-put?underlying=GGBR4")
    assert ccp_response.status_code == 200
    ccp_html = ccp_response.get_data(as_text=True)
    assert "Ultimo exercicio detectado para GGBR4" in ccp_html
    assert "GGBRO215" in ccp_html
    assert "608.00" in ccp_html
    assert "Covered Call" in ccp_html


def test_put_assignment_recalculates_average_when_the_stock_already_exists() -> None:
    _ensure_snapshot_tables()
    upsert_holding(
        ticker="CMIG4",
        quantity=300,
        avg_price=11.61,
        is_simulated=False,
        notes="Estoque anterior confirmado",
        event_date="2026-08-01",
    )

    holding = apply_put_assignment_to_holding(
        ticker="CMIG4",
        qty=2100,
        strike=10.96,
        purchase_fees=32.36,
        date="2026-08-21",
        is_simulated=False,
        related_position_id=66,
    )

    expected = ((300 * 11.61) + (2100 * 10.96) + 32.36) / 2400
    assert int(holding["shares_total"]) == 2400
    assert float(holding["avg_price"]) == pytest.approx(expected)
    assert holding["price_status"] == "ok"


def test_put_assignment_without_confirmed_date_is_blocked() -> None:
    _ensure_snapshot_tables()

    pos_id = portfolio.add_position(
        ticker="BBASR210ON",
        underlying="BBAS3",
        trade_date="2026-05-18",
        qty=800,
        entry_price=0.71,
        fees=0.75,
        trade_type="swing",
        side="short",
        strategy_tag="cash_put",
    )

    app = create_app()
    app.testing = True
    client = app.test_client()

    response = client.post(
        "/finance/assign",
        data={
            "position_id": str(pos_id),
            "qty": "800",
            "strike": "20.73",
            "date": "",
        },
    )

    assert response.status_code in (302, 303)
    assert "position_error=" in (response.headers.get("Location") or "")
    put_pos = portfolio.get_position(pos_id)
    assert put_pos is not None
    assert put_pos["status"] == "open"
    assignment_txs = [
        tx
        for tx in finance.get_transactions(limit=20, strategy_tag="cash_put")
        if tx.position_id == pos_id and tx.type == finance.TransactionType.ASSIGNMENT
    ]
    assert assignment_txs == []


def test_cash_put_page_uses_confirmation_modals_for_expiration_and_assignment() -> None:
    _ensure_snapshot_tables()
    portfolio.add_position(
        ticker="BBASR210ON",
        underlying="BBAS3",
        trade_date="2026-05-18",
        qty=800,
        entry_price=0.71,
        fees=0.75,
        trade_type="swing",
        side="short",
        strategy_tag="cash_put",
    )

    app = create_app()
    app.testing = True
    client = app.test_client()

    response = client.get("/cash-covered-put?underlying=BBAS3")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'id="modalCashPutExpire"' in html
    assert 'id="modalCashPutAssign"' in html
    assert "Confirmar exercício da PUT" in html
    assert 'name="purchase_fees"' in html
