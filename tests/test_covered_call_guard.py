from __future__ import annotations

import pytest

from opcoes import finance, portfolio
from opcoes.covered_call_guard import (
    CoveredCallValidationError,
    audit_covered_call_positions,
    validate_covered_call_input,
)
from opcoes.holdings import get_holding, upsert_holding
from opcoes.scraper.snapshots import SnapshotDB
from opcoes.web import create_app


def _ensure_snapshot_tables() -> None:
    snap = SnapshotDB()
    snap.close()


def test_covered_call_guard_blocks_wrong_underlying_prefix() -> None:
    with pytest.raises(CoveredCallValidationError):
        validate_covered_call_input(
            ticker="WIZCB103",
            underlying="WICZ3",
            trade_date="2026-02-05",
            qty=300,
            entry_price=0.23,
            side="short",
            strategy_tag="covered_call",
        )


def test_covered_call_audit_flags_probable_duplicate() -> None:
    positions = [
        {
            "id": 49,
            "ticker": "CAMLD794",
            "underlying": "CAML3",
            "trade_date": " 2026-04-15",
            "qty": 1000,
            "entry_price": 0.05,
            "fees": 0.05,
            "trade_type": "swing",
            "side": "short",
            "status": "closed",
            "exit_date": "2026-04-17",
            "exit_price": 0.0,
            "exit_reason": "Expiração",
            "strategy_tag": "covered_call",
            "is_simulated": 0,
        },
        {
            "id": 50,
            "ticker": "CAMLD794",
            "underlying": "CAML3",
            "trade_date": "2026-04-15",
            "qty": 1000,
            "entry_price": 0.05,
            "fees": 0.04,
            "trade_type": "swing",
            "side": "short",
            "status": "closed",
            "exit_date": "2026-04-17",
            "exit_price": 0.0,
            "exit_reason": "Expiração",
            "strategy_tag": "covered_call",
            "is_simulated": 0,
        },
    ]

    issues = audit_covered_call_positions(
        positions,
        ledger_sums={
            49: {
                finance.TransactionType.PREMIUM.value: 49.95,
                finance.TransactionType.REALIZED.value: 49.95,
            },
            50: {
                finance.TransactionType.PREMIUM.value: 49.96,
                finance.TransactionType.REALIZED.value: 49.96,
            },
        },
    )

    assert any(issue.code == "DUPLICIDADE_PROVAVEL" for issue in issues)
    assert any(issue.code == "VALIDACAO" and issue.position_id == 49 for issue in issues)


def test_covered_call_audit_flags_exercise_without_stock_event() -> None:
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
            "exit_reason": "Exercício",
            "strategy_tag": "covered_call",
            "is_simulated": 0,
        }
    ]

    issues = audit_covered_call_positions(
        positions,
        ledger_sums={
            54: {
                finance.TransactionType.PREMIUM.value: 287.63,
                finance.TransactionType.SELL.value: 18056.0,
                finance.TransactionType.REALIZED.value: 287.63,
            }
        },
        holding_events=[],
    )

    assert any(issue.code == "EXERCICIO_SEM_ESTOQUE" for issue in issues)


def test_covered_call_audit_flags_legacy_stock_open_with_zero_holding() -> None:
    positions = [
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
            "status": "open",
            "strategy_tag": "covered_call",
            "is_simulated": 0,
        }
    ]

    issues = audit_covered_call_positions(
        positions,
        ledger_sums={},
        holding_snapshots=[
            {
                "ticker": "GGBR4",
                "is_simulated": False,
                "shares_total": 0,
                "coverage_gap": 0,
            }
        ],
    )

    assert any(issue.code == "LOTE_ABERTO_SEM_ESTOQUE" for issue in issues)


@pytest.mark.requires_postgres
def test_covered_call_web_add_blocks_wrong_underlying() -> None:
    _ensure_snapshot_tables()
    upsert_holding(
        ticker="WICZ3",
        quantity=300,
        avg_price=7.16,
        is_simulated=False,
        notes="Dado digitado errado para testar trava",
    )

    app = create_app()
    app.testing = True
    client = app.test_client()

    res = client.post(
        "/positions/add",
        data={
            "ticker": "WIZCB103",
            "underlying": "WICZ3",
            "qty": "300",
            "entry_price": "0.23",
            "fees": "0.07",
            "trade_date": "2026-02-05",
            "trade_type": "swing",
            "side": "short",
            "strategy_tag": "covered_call",
            "record_premium": "1",
            "reserve_darf": "1",
            "is_simulated": "0",
        },
    )

    assert res.status_code in (302, 303)
    assert "holding_error=" in (res.headers.get("Location") or "")
    assert portfolio.list_positions(include_closed=True, ticker="WIZCB103") == []


@pytest.mark.requires_postgres
def test_covered_call_web_add_blocks_probable_duplicate() -> None:
    _ensure_snapshot_tables()
    upsert_holding(
        ticker="CAML3",
        quantity=2000,
        avg_price=6.60,
        is_simulated=False,
        notes="Estoque para teste de duplicidade",
    )
    portfolio.add_position(
        ticker="CAMLD794",
        underlying="CAML3",
        trade_date="2026-04-15",
        qty=1000,
        entry_price=0.05,
        fees=0.05,
        trade_type="swing",
        side="short",
        strategy_tag="covered_call",
    )

    app = create_app()
    app.testing = True
    client = app.test_client()

    res = client.post(
        "/positions/add",
        data={
            "ticker": "CAMLD794",
            "underlying": "CAML3",
            "qty": "1000",
            "entry_price": "0.05",
            "fees": "0.04",
            "trade_date": "2026-04-15",
            "trade_type": "swing",
            "side": "short",
            "strategy_tag": "covered_call",
            "record_premium": "1",
            "reserve_darf": "1",
            "is_simulated": "0",
        },
    )

    assert res.status_code in (302, 303)
    assert "holding_error=" in (res.headers.get("Location") or "")
    assert len(portfolio.list_positions(include_closed=True, ticker="CAMLD794")) == 1


@pytest.mark.requires_postgres
def test_covered_call_exercise_without_confirmed_date_is_blocked() -> None:
    _ensure_snapshot_tables()
    upsert_holding(
        ticker="GGBR4",
        quantity=800,
        avg_price=20.73,
        is_simulated=False,
        notes="Estoque para teste de exercicio",
    )
    pos_id = portfolio.add_position(
        ticker="GGBRE228",
        underlying="GGBR4",
        trade_date="2026-04-22",
        qty=800,
        entry_price=0.36,
        fees=0.37,
        trade_type="swing",
        side="short",
        strategy_tag="covered_call",
    )

    app = create_app()
    app.testing = True
    client = app.test_client()

    res = client.post("/finance/callaway", data={"position_id": str(pos_id), "date": ""})

    assert res.status_code in (302, 303)
    assert "holding_error=" in (res.headers.get("Location") or "")
    assert portfolio.get_position(pos_id)["status"] == "open"
    assert get_holding(ticker="GGBR4", is_simulated=False)["quantity"] == 800


@pytest.mark.requires_postgres
def test_covered_call_expiration_without_confirmed_date_is_blocked() -> None:
    _ensure_snapshot_tables()
    upsert_holding(
        ticker="CAML3",
        quantity=1000,
        avg_price=6.60,
        is_simulated=False,
        notes="Estoque para teste de expiracao",
    )
    pos_id = portfolio.add_position(
        ticker="CAMLD794",
        underlying="CAML3",
        trade_date="2026-04-15",
        qty=1000,
        entry_price=0.05,
        fees=0.05,
        trade_type="swing",
        side="short",
        strategy_tag="covered_call",
    )

    app = create_app()
    app.testing = True
    client = app.test_client()

    res = client.post("/finance/expire", data={"position_id": str(pos_id), "date": ""})

    assert res.status_code in (302, 303)
    assert "holding_error=" in (res.headers.get("Location") or "")
    assert portfolio.get_position(pos_id)["status"] == "open"


@pytest.mark.requires_postgres
def test_covered_call_page_uses_confirmation_modals_for_expiration_and_exercise() -> None:
    _ensure_snapshot_tables()
    upsert_holding(
        ticker="GGBR4",
        quantity=800,
        avg_price=20.73,
        is_simulated=False,
        notes="Estoque para teste de modal",
    )
    portfolio.add_position(
        ticker="GGBRE228",
        underlying="GGBR4",
        trade_date="2026-04-22",
        qty=800,
        entry_price=0.36,
        fees=0.37,
        trade_type="swing",
        side="short",
        strategy_tag="covered_call",
    )

    app = create_app()
    app.testing = True
    client = app.test_client()

    page = client.get("/covered-call?underlying=GGBR4")
    partial = client.get("/covered-call/partial/audit?underlying=GGBR4")

    assert page.status_code == 200
    page_html = page.get_data(as_text=True)
    assert 'id="modalCoveredCallExpire"' in page_html
    assert 'id="modalCoveredCallExercise"' in page_html
    assert "Confirmar exercício da CALL" in page_html

    assert partial.status_code == 200
    partial_html = partial.get_data(as_text=True)
    assert 'data-bs-target="#modalCoveredCallExpire"' in partial_html
