from __future__ import annotations

import re
from html import unescape

import pytest

from opcoes import finance, portfolio
from opcoes.db import open_db
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
    upsert_holding(
        ticker="WIZC3",
        quantity=300,
        avg_price=7.16,
        is_simulated=False,
        notes="Cobertura necessária para reabrir a CALL no teste",
    )

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
    assert "holding_error=" not in (res.headers.get("Location") or "")
    assert portfolio.get_position(pos_id)["status"] == "open"
    assert _buyback_txs(pos_id) == []


def test_notes_only_update_does_not_resynchronize_financial_ledger(monkeypatch) -> None:
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
    portfolio.close_position(
        position_id=pos_id,
        exit_date="2026-02-18",
        exit_price=0.01,
        exit_reason="recompra_encerramento",
    )
    calls: list[dict] = []
    monkeypatch.setattr(
        finance,
        "sync_position_closure_effects",
        lambda **kwargs: calls.append(kwargs),
    )

    app = create_app()
    app.testing = True
    response = app.test_client().post(
        f"/positions/update/{pos_id}",
        data=_build_update_payload(notes="Conferido na nota BTG"),
    )

    assert response.status_code in (302, 303)
    assert calls == []
    assert portfolio.get_position(pos_id)["notes"] == "Conferido na nota BTG"


def test_financial_update_syncs_inside_same_transaction(monkeypatch) -> None:
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
    calls: list[dict] = []
    monkeypatch.setattr(
        finance,
        "sync_position_closure_effects",
        lambda **kwargs: calls.append(kwargs),
    )

    app = create_app()
    app.testing = True
    response = app.test_client().post(
        f"/positions/update/{pos_id}",
        data=_build_update_payload(),
    )

    assert response.status_code in (302, 303)
    assert len(calls) == 1
    assert calls[0]["position_id"] == pos_id
    assert calls[0]["position"]["status"] == "closed"
    assert calls[0]["conn"] is not None


def test_financial_update_rolls_back_position_and_ledger_after_sync_failure(monkeypatch) -> None:
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
    finance.recalc_position_premium_and_darf(
        position_id=pos_id,
        trade_date="2026-02-05",
        ticker="WIZCB103",
        qty=300,
        premium_amount=finance.calculate_option_premium(entry_price=0.23, qty=300, fees=0.07),
        trade_type="swing",
        is_simulated=False,
    )
    app = create_app()
    app.testing = True
    client = app.test_client()
    response = client.post(
        f"/positions/update/{pos_id}",
        data=_build_update_payload(notes="Nota original"),
    )
    assert response.status_code in (302, 303)
    assert len(_buyback_txs(pos_id)) == 1

    def snapshot_state(conn):
        position = dict(
            conn.execute("SELECT * FROM positions WHERE id = %s", (pos_id,)).fetchone()
        )
        ledger = [dict(row) for row in conn.execute("SELECT * FROM ledger ORDER BY id").fetchall()]
        return position, ledger

    with open_db() as conn:
        before_position, before_ledger = snapshot_state(conn)

    original_sync = finance.sync_position_closure_effects
    synchronized_states = []

    def sync_then_fail(**kwargs):
        original_sync(**kwargs)
        synchronized_states.append(snapshot_state(kwargs["conn"]))
        raise RuntimeError("Falha após sincronização financeira")

    monkeypatch.setattr(finance, "sync_position_closure_effects", sync_then_fail)

    with pytest.raises(RuntimeError, match="Falha após sincronização financeira"):
        client.post(
            f"/positions/update/{pos_id}",
            data=_build_update_payload(exit_price="0.02", notes="Nota que não deve persistir"),
        )

    assert len(synchronized_states) == 1
    changed_position, changed_ledger = synchronized_states[0]
    assert changed_position["exit_price"] == pytest.approx(0.02)
    assert changed_position["notes"] == "Nota que não deve persistir"
    assert changed_ledger != before_ledger
    assert any(row["type"] == "BUY" and row["amount"] == -6.0 for row in changed_ledger)

    with open_db() as conn:
        after_position, after_ledger = snapshot_state(conn)
    assert after_position == before_position
    assert after_ledger == before_ledger


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
            "contract_strike": "12.34",
            "contract_expiry": "2026-04-17",
            "performance_source_ref": "nota teste",
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
    assert pos["contract_strike"] == pytest.approx(12.34)
    assert pos["contract_expiry"] == "2026-04-17"
    assert pos["capital_committed"] == pytest.approx(3000.0)

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
    assert 'hx-get="/covered-call/partial/audit?' in html
    assert ">300<" in html

    audit_response = client.get("/covered-call/partial/audit?underlying=WIZC3")
    assert audit_response.status_code == 200
    audit_html = audit_response.get_data(as_text=True)
    assert "Lotes legados de WIZC3 (real)" in audit_html
    assert "Qtd coberta" in audit_html
    assert "WIZCC100" in audit_html
    assert "7.16" in audit_html
    assert ">300<" in audit_html


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

    assert "Líquido operação antes de exercício" in html

    def cell_text(cell: str) -> str:
        return " ".join(unescape(re.sub(r"<[^>]+>", " ", cell)).split())

    table = next(
        table
        for table in re.findall(r"<table\b[^>]*>.*?</table>", html, re.DOTALL)
        if "Líquido operação esp." in table
    )
    headers = [cell_text(cell) for cell in re.findall(r"<th\b[^>]*>(.*?)</th>", table, re.DOTALL)]
    rows = [
        [cell_text(cell) for cell in re.findall(r"<td\b[^>]*>(.*?)</td>", row, re.DOTALL)]
        for row in re.findall(r"<tr\b[^>]*>(.*?)</tr>", table, re.DOTALL)
    ]
    values = dict(zip(headers, next(row for row in rows if len(row) > 1 and row[1] == "WIZCB103")))
    assert values["Recompra esp."] == values["Recompra caixa"] == "-3.00"
    assert values["Dif. recompra"] == "0.00"
    assert values["Líquido fiscal esp."] == values["Líquido fiscal caixa"] == "58.59"
    assert values["Dif. fiscal"] == "0.00"
    assert values["Líquido operação esp."] == values["Líquido operação caixa"] == "55.59"
    assert values["Dif. operação"] == "0.00"
    assert values["Realizado esp."] == values["Realizado ledger"] == "65.93"
