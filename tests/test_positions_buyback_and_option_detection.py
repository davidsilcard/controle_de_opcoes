from __future__ import annotations

import re
import pytest

from opcoes import finance, portfolio
from opcoes.holdings import upsert_holding
from opcoes.scraper.snapshots import SnapshotDB
from opcoes.web import create_app

pytestmark = pytest.mark.requires_postgres


def _ensure_snapshot_tables() -> None:
    snap = SnapshotDB()
    snap.close()


def _build_update_payload(**overrides) -> dict:
    data = {
        "ticker": "WIZCB103",
        "underlying": "WIZC3",
        "status": "closed",
        "trade_type": "swing",
        "side": "short",
        "strategy_tag": "covered_call",
        "parent_position_id": "",
        "is_simulated": "0",
        "trade_date": "2026-02-05",
        "qty": "300",
        "entry_price": "0.23",
        "fees": "0.07",
        "exit_date": "2026-02-18",
        "exit_price": "0.01",
        "notes": "",
        "partial_qty": "",
        "partial_price": "",
        "partial_date": "",
        "exit_reason": "recompra_encerramento",
        "irrf": "0",
        "next": "/positions",
    }
    data.update(overrides)
    return data


def _buyback_txs(position_id: int):
    txs = finance.get_transactions(limit=200)
    return [
        tx
        for tx in txs
        if tx.position_id == position_id
        and tx.type == finance.TransactionType.BUY
        and (tx.description or "").startswith("Recompra opção ")
    ]


def test_closing_short_option_creates_buyback_tx_and_is_idempotent() -> None:
    _ensure_snapshot_tables()

    pos_id = portfolio.add_position(
        ticker="WIZCB103",
        underlying="WIZC3",
        trade_date="2026-02-05",
        qty=300,
        entry_price=0.23,
        fees=0.07,
        trade_type="swing",
        side="short",
        strategy_tag="covered_call",
    )

    app = create_app()
    app.testing = True
    client = app.test_client()

    res = client.post(f"/positions/update/{pos_id}", data=_build_update_payload())
    assert res.status_code in (302, 303)

    buyback = _buyback_txs(pos_id)
    assert len(buyback) == 1
    assert buyback[0].date == "2026-02-18"
    assert abs(buyback[0].amount - (-3.0)) < 1e-6

    # Não duplica ao salvar novamente.
    res = client.post(f"/positions/update/{pos_id}", data=_build_update_payload())
    assert res.status_code in (302, 303)
    buyback = _buyback_txs(pos_id)
    assert len(buyback) == 1

    # Atualiza valor se preço de saída mudar.
    res = client.post(
        f"/positions/update/{pos_id}",
        data=_build_update_payload(exit_price="0.02"),
    )
    assert res.status_code in (302, 303)
    buyback = _buyback_txs(pos_id)
    assert len(buyback) == 1
    assert abs(buyback[0].amount - (-6.0)) < 1e-6

    # Remove recompra se reabrir a posição.
    res = client.post(
        f"/positions/update/{pos_id}",
        data=_build_update_payload(status="open", exit_date="", exit_price=""),
    )
    assert res.status_code in (302, 303)
    assert _buyback_txs(pos_id) == []


def test_stock_with_mismatched_underlying_is_not_treated_as_option() -> None:
    _ensure_snapshot_tables()

    pos_id = portfolio.add_position(
        ticker="WICZ3",
        underlying="WIZC3",
        trade_date="2026-02-05",
        qty=300,
        entry_price=7.16,
        trade_type="swing",
        side="long",
    )

    app = create_app()
    app.testing = True
    client = app.test_client()

    response = client.get("/positions")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    assert f"/positions/register-premium/{pos_id}" not in html
    assert f"/positions/recalc-premium/{pos_id}" not in html


def test_update_position_allows_underlying_edit_and_autofill_for_stock() -> None:
    _ensure_snapshot_tables()

    pos_id = portfolio.add_position(
        ticker="HYPE3",
        underlying="",
        trade_date="2026-02-19",
        qty=300,
        entry_price=26.14,
        trade_type="swing",
        side="long",
    )

    app = create_app()
    app.testing = True
    client = app.test_client()

    res = client.post(
        f"/positions/update/{pos_id}",
        data=_build_update_payload(
            ticker="HYPE3",
            underlying="",
            status="open",
            trade_type="swing",
            side="long",
            strategy_tag="",
            qty="300",
            entry_price="26.14",
            fees="0",
            trade_date="2026-02-19",
            exit_date="",
            exit_price="",
            partial_qty="",
            partial_price="",
            partial_date="",
            exit_reason="",
            irrf="",
        ),
    )
    assert res.status_code in (302, 303)
    assert portfolio.get_position(pos_id)["underlying"] == "HYPE3"

    res = client.post(
        f"/positions/update/{pos_id}",
        data=_build_update_payload(
            ticker="HYPE3",
            underlying="HYPE4",
            status="open",
            trade_type="swing",
            side="long",
            strategy_tag="",
            qty="300",
            entry_price="26.14",
            fees="0",
            trade_date="2026-02-19",
            exit_date="",
            exit_price="",
            partial_qty="",
            partial_price="",
            partial_date="",
            exit_reason="",
            irrf="",
        ),
    )
    assert res.status_code in (302, 303)
    assert portfolio.get_position(pos_id)["underlying"] == "HYPE4"


def test_migration_fills_blank_underlying_for_stock_positions() -> None:
    _ensure_snapshot_tables()

    pos_id = portfolio.add_position(
        ticker="BBSE3",
        underlying="",
        trade_date="2026-02-19",
        qty=1000,
        entry_price=35.27,
        trade_type="swing",
        side="long",
    )

    pos = portfolio.get_position(pos_id)
    assert pos is not None
    assert pos["underlying"] == "BBSE3"


def test_register_premium_ignores_non_option_ticker() -> None:
    _ensure_snapshot_tables()

    pos_id = portfolio.add_position(
        ticker="WICZ3",
        underlying="WIZC3",
        trade_date="2026-02-05",
        qty=300,
        entry_price=7.16,
        trade_type="swing",
        side="short",
    )

    app = create_app()
    app.testing = True
    client = app.test_client()

    res = client.post(f"/positions/register-premium/{pos_id}", data={"next": "/positions"})
    assert res.status_code in (302, 303)

    txs = finance.get_transactions(limit=50)
    linked = [t for t in txs if t.position_id == pos_id]
    assert linked == []


def test_add_covered_call_normalizes_short_side_and_registers_cash() -> None:
    _ensure_snapshot_tables()

    upsert_holding(
        ticker="TEST3",
        quantity=300,
        avg_price=10.0,
        is_simulated=False,
        notes="Estoque inicial para covered call",
    )

    app = create_app()
    app.testing = True
    client = app.test_client()

    res = client.post(
        "/positions/add",
        data={
            "ticker": "TESTC123",
            "underlying": "TEST3",
            "qty": "300",
            "entry_price": "0.09",
            "fees": "0.01",
            "trade_date": "2026-03-10",
            "trade_type": "swing",
            "side": "long",
            "strategy_tag": "covered_call",
            "parent_position_id": "",
            "record_premium": "1",
            "reserve_darf": "1",
            "is_simulated": "0",
        },
    )
    assert res.status_code in (302, 303)

    positions = portfolio.list_positions(include_closed=True, ticker="TESTC123")
    assert len(positions) == 1
    pos = positions[0]
    assert pos["side"] == "short"
    assert pos["strategy_tag"] == "covered_call"
    assert pos["parent_position_id"] is None

    txs = [t for t in finance.get_transactions(limit=50) if t.position_id == pos["id"]]
    assert len(txs) == 2
    premium = next(t for t in txs if t.type == finance.TransactionType.PREMIUM)
    darf = next(t for t in txs if t.type == finance.TransactionType.DARF)
    assert abs(premium.amount - 26.99) < 1e-6
    assert abs(darf.amount - (-4.05)) < 1e-6


def test_add_covered_call_without_stock_is_blocked() -> None:
    _ensure_snapshot_tables()

    app = create_app()
    app.testing = True
    client = app.test_client()

    res = client.post(
        "/positions/add",
        data={
            "ticker": "TESTC123",
            "underlying": "TEST3",
            "qty": "300",
            "entry_price": "0.09",
            "fees": "0.01",
            "trade_date": "2026-03-10",
            "trade_type": "swing",
            "side": "short",
            "strategy_tag": "covered_call",
            "record_premium": "1",
            "reserve_darf": "1",
            "is_simulated": "0",
        },
    )
    assert res.status_code in (302, 303)
    assert "/covered-call?underlying=TEST3" in (res.headers.get("Location") or "")

    positions = portfolio.list_positions(include_closed=True, ticker="TESTC123")
    assert positions == []


def test_covered_call_page_uses_stock_underlying_reference_for_mismatched_lot_ticker() -> None:
    _ensure_snapshot_tables()

    lot_id = portfolio.add_position(
        ticker="WICZ3",
        underlying="WIZC3",
        trade_date="2026-02-05",
        qty=300,
        entry_price=7.16,
        trade_type="swing",
        side="long",
        strategy_tag="estoque",
    )
    portfolio.add_position(
        ticker="WIZCC100",
        underlying="WIZC3",
        trade_date="2026-03-10",
        qty=300,
        entry_price=0.09,
        fees=0.01,
        trade_type="swing",
        side="short",
        strategy_tag="covered_call",
        parent_position_id=lot_id,
    )

    app = create_app()
    app.testing = True
    client = app.test_client()

    resp = client.get("/covered-call?underlying=WIZC3")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    assert "WIZCC100" in html
    assert "Nenhuma call real para resumir." not in html
    assert "Nenhuma call de WIZC3 em aberto nas posi" not in html
    assert "Cobertas (calls)" in html
    assert ">300<" in html


def test_audit_shows_operational_net_with_buyback() -> None:
    _ensure_snapshot_tables()

    pos_id = portfolio.add_position(
        ticker="WIZCB103",
        underlying="WIZC3",
        trade_date="2026-02-05",
        qty=300,
        entry_price=0.23,
        fees=0.07,
        trade_type="swing",
        side="short",
        strategy_tag="covered_call",
    )
    premium_amount = finance.calculate_option_premium(entry_price=0.23, qty=300, fees=0.07)
    finance.recalc_position_premium_and_darf(
        position_id=pos_id,
        trade_date="2026-02-05",
        ticker="WIZCB103",
        qty=300,
        premium_amount=premium_amount,
        trade_type="swing",
        is_simulated=False,
    )

    app = create_app()
    app.testing = True
    client = app.test_client()

    res = client.post(f"/positions/update/{pos_id}", data=_build_update_payload())
    assert res.status_code in (302, 303)

    resp = client.get("/audit?mode=real&include_closed=1")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    assert "Líquido operação (Prêmio + DARF + Recompra)" in html

    plain_text = re.sub(r"<[^>]+>", " ", html)
    plain_text = " ".join(plain_text.split())
    assert re.search(
        r"WIZCB103 .* -3\.00 -3\.00 0\.00 58\.59 58\.59 0\.00 55\.59 55\.59 0\.00",
        plain_text,
    )
