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


@pytest.mark.requires_postgres
def test_ranking_update_keeps_buy_idempotent() -> None:
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

    app = create_app()
    app.testing = True
    client = app.test_client()
    payload = {
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
        "entry_price": "3.00",
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

    res = client.post(f"/positions/update/{pos_id}", data=payload)
    assert res.status_code in (302, 303)
    res = client.post(f"/positions/update/{pos_id}", data=payload)
    assert res.status_code in (302, 303)

    txs = [tx for tx in finance.get_transactions(limit=50) if tx.position_id == pos_id]
    assert len(txs) == 1
    assert txs[0].type == finance.TransactionType.BUY
    assert txs[0].amount == -300.50
