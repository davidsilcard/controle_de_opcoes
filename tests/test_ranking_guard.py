from __future__ import annotations

import pytest

from opcoes import finance, portfolio
from opcoes.ranking_guard import (
    RankingValidationError,
    audit_ranking_positions,
    validate_ranking_option_input,
)
from opcoes.scraper.snapshots import SnapshotDB
from opcoes.web import create_app


def _ensure_snapshot_tables() -> None:
    snap = SnapshotDB()
    snap.close()


def test_ranking_guard_blocks_non_option() -> None:
    with pytest.raises(RankingValidationError):
        validate_ranking_option_input(
            ticker="KLBN11",
            underlying="KLBN11",
            trade_date="2026-05-29",
            qty=100,
            entry_price=18.60,
            side="long",
            strategy_tag="ranking",
        )


def test_ranking_audit_flags_missing_buy_ledger() -> None:
    issues = audit_ranking_positions(
        [
            {
                "id": 57,
                "ticker": "KLBNK171",
                "underlying": "KLBN11",
                "trade_date": "2026-05-29",
                "qty": 100,
                "entry_price": 3.16,
                "fees": 0.40,
                "side": "long",
                "strategy_tag": "ranking",
            }
        ],
        ledger_sums={},
    )

    assert any(issue.code == "COMPRA_SEM_LEDGER" for issue in issues)


def test_ranking_audit_keeps_closed_option_buy_separate_from_exit_fees() -> None:
    issues = audit_ranking_positions(
        [
            {
                "id": 6,
                "ticker": "PETRA456",
                "underlying": "PETR4",
                "trade_date": "2025-11-19",
                "qty": 100,
                "entry_price": 1.95,
                "fees": 1.60,
                "side": "long",
                "status": "closed",
                "exit_date": "2026-03-30",
                "exit_price": 12.00,
                "strategy_tag": "ranking",
            }
        ],
        ledger_sums={6: {finance.TransactionType.BUY.value: -195.00}},
    )

    assert issues == []


@pytest.mark.requires_postgres
def test_ranking_web_add_records_buy_automatically() -> None:
    _ensure_snapshot_tables()
    app = create_app()
    app.testing = True
    client = app.test_client()

    res = client.post(
        "/positions/add",
        data={
            "ticker": "KLBNK171",
            "underlying": "KLBN11",
            "trade_date": "2026-05-29",
            "qty": "100",
            "entry_price": "3.16",
            "fees": "0.40",
            "trade_type": "swing",
            "side": "long",
            "strategy_tag": "ranking",
            "is_simulated": "0",
            "next": "/positions",
        },
    )

    assert res.status_code in (302, 303)
    positions = portfolio.list_positions(include_closed=True, ticker="KLBNK171")
    assert len(positions) == 1
    pos_id = int(positions[0]["id"])
    txs = [tx for tx in finance.get_transactions(limit=50) if tx.position_id == pos_id]
    assert len(txs) == 1
    assert txs[0].type == finance.TransactionType.BUY
    assert txs[0].amount == -316.40


@pytest.fixture
def ranking_position_id() -> int:
    _ensure_snapshot_tables()
    pos_id = portfolio.add_position(
        ticker="KLBNK171",
        underlying="KLBN11",
        trade_date="2026-05-29",
        qty=100,
        entry_price=3.16,
        fees=0.40,
        trade_type="swing",
        side="long",
        strategy_tag="ranking",
    )

    finance.sync_position_closure_effects(position_id=pos_id)
    return pos_id


def _ranking_update_payload() -> dict[str, str]:
    return {
        "ticker": "KLBNK171",
        "underlying": "KLBN11",
        "status": "open",
        "trade_type": "swing",
        "side": "long",
        "strategy_tag": "ranking",
        "parent_position_id": "",
        "is_simulated": "0",
        "trade_date": "2026-05-29",
        "qty": "100",
        "entry_price": "3.16",
        "fees": "0.50",
        "exit_date": "",
        "exit_price": "",
        "notes": "",
        "partial_qty": "",
        "partial_price": "",
        "partial_date": "",
        "exit_reason": "",
        "irrf": "",
        "next": "/positions",
    }


@pytest.mark.requires_postgres
def test_ranking_update_keeps_buy_idempotent(ranking_position_id: int) -> None:
    pos_id = ranking_position_id
    before = [
        tx for tx in finance.get_transactions(limit=50) if tx.position_id == pos_id
    ]
    assert len(before) == 1
    assert before[0].type == finance.TransactionType.BUY
    assert before[0].amount == pytest.approx(-316.40)

    app = create_app()
    app.testing = True
    client = app.test_client()
    payload = _ranking_update_payload()

    for _ in range(2):
        res = client.post(f"/positions/update/{pos_id}", data=payload)
        assert res.status_code in (302, 303)
        assert "position_error=" not in res.location
        position = portfolio.get_position(pos_id)
        assert position is not None
        assert position["status"] == "open"
        assert position["entry_price"] == pytest.approx(3.16)
        assert position["fees"] == pytest.approx(0.50)

    txs = [tx for tx in finance.get_transactions(limit=50) if tx.position_id == pos_id]
    assert len(txs) == 1
    assert txs[0].id == before[0].id
    assert txs[0].type == finance.TransactionType.BUY
    assert txs[0].amount == pytest.approx(-316.50)


@pytest.mark.requires_postgres
def test_ranking_update_rejects_entry_price_change_without_mutation(
    ranking_position_id: int,
) -> None:
    pos_id = ranking_position_id
    before = portfolio.get_position(pos_id)
    ledger_before = finance.get_transactions(limit=50)
    assert before is not None
    assert len([tx for tx in ledger_before if tx.position_id == pos_id]) == 1

    app = create_app()
    app.testing = True
    client = app.test_client()
    payload = _ranking_update_payload()
    payload["entry_price"] = "3.00"

    response = client.post(f"/positions/update/{pos_id}", data=payload)

    assert response.status_code in (302, 303)
    assert "position_error=" in response.location
    assert portfolio.get_position(pos_id) == before
    assert finance.get_transactions(limit=50) == ledger_before
