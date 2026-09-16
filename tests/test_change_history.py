from __future__ import annotations

import pytest

from opcoes import finance, portfolio
from opcoes.change_history import list_change_history
from opcoes.db import db_transaction


pytestmark = pytest.mark.requires_postgres


def test_history_preserves_prior_position_and_ledger_versions() -> None:
    position_id = portfolio.add_position(
        ticker="PETRS100",
        underlying="PETR4",
        trade_date="2026-09-15",
        qty=100,
        entry_price=0.50,
        notes="registro inicial",
    )
    portfolio.update_position(position_id=position_id, notes="registro corrigido")

    tx_id = finance.add_transaction(
        date="2026-09-15",
        type=finance.TransactionType.DEPOSIT,
        amount=1000.0,
        description="aporte informado por teste",
    )
    reversal_id = finance.delete_transaction(
        tx_id,
        reason="lançamento de teste duplicado",
        actor="auditor_teste",
        reversal_date="2026-09-16",
    )

    with db_transaction() as conn:
        position_history = list_change_history(
            conn,
            source_table="positions",
            source_id=position_id,
        )
        assert position_history[-1]["change_kind"] == "UPDATE"
        assert position_history[-1]["prior_values"]["notes"] == "registro inicial"
        original = conn.execute("SELECT * FROM ledger WHERE id = ?", (tx_id,)).fetchone()
        reversal = conn.execute("SELECT * FROM ledger WHERE id = ?", (reversal_id,)).fetchone()
        assert original is not None
        assert reversal is not None
        assert reversal["reversal_of_id"] == tx_id
        assert reversal["amount"] == -original["amount"]
        assert "lançamento de teste duplicado" in reversal["description"]
        history_id = position_history[-1]["id"]
        with pytest.raises(Exception, match="imutável"):
            conn.execute(
                "UPDATE record_history SET actor = ? WHERE id = ?",
                ("alterado", history_id),
            )
        conn.rollback()


def test_anulation_requires_a_reason() -> None:
    tx_id = finance.add_transaction(
        date="2026-09-15",
        type=finance.TransactionType.DEPOSIT,
        amount=10.0,
    )

    with pytest.raises(ValueError, match="motivo"):
        finance.delete_transaction(tx_id, reason="", reversal_date="2026-09-16")

    assert any(item.id == tx_id for item in finance.list_transactions(limit=20))


def test_manual_transaction_can_be_reversed_once_but_linked_transaction_is_blocked() -> None:
    tx_id = finance.add_transaction(
        date="2026-09-15",
        type=finance.TransactionType.DEPOSIT,
        amount=100.0,
        description="aporte duplicado",
    )
    reversal_id = finance.delete_transaction(
        tx_id,
        reason="aporte informado duas vezes",
        reversal_date="2026-09-16",
    )

    transactions = {tx.id: tx for tx in finance.get_transactions(limit=20)}
    assert transactions[tx_id].reversal_id == reversal_id
    assert transactions[reversal_id].reversal_of_id == tx_id
    with pytest.raises(ValueError, match="já possui o estorno"):
        finance.delete_transaction(
            tx_id,
            reason="nova tentativa",
            reversal_date="2026-09-16",
        )

    position_id = portfolio.add_position(
        ticker="PETRN312",
        underlying="PETR4",
        trade_date="2026-09-15",
        qty=100,
        entry_price=0.5,
    )
    linked_id = finance.add_transaction(
        date="2026-09-15",
        type=finance.TransactionType.PREMIUM,
        amount=50.0,
        position_id=position_id,
    )
    with pytest.raises(ValueError, match="vinculada a uma posição"):
        finance.delete_transaction(
            linked_id,
            reason="tentativa indevida",
            reversal_date="2026-09-16",
        )


def test_manual_transaction_correction_requires_reason_and_preserves_prior_version() -> None:
    tx_id = finance.add_transaction(
        date="2026-09-15",
        type=finance.TransactionType.DEPOSIT,
        amount=100.0,
        description="aporte com valor errado",
    )
    with pytest.raises(ValueError, match="motivo"):
        finance.update_transaction(tx_id, amount=120.0)

    finance.update_transaction(
        tx_id,
        amount=120.0,
        reason="valor informado sem centavos",
        actor="auditor_teste",
    )
    with db_transaction() as conn:
        history = list_change_history(
            conn,
            source_table="ledger",
            source_id=tx_id,
        )
    assert history[-1]["change_kind"] == "UPDATE"
    assert history[-1]["actor"] == "auditor_teste"
    assert history[-1]["reason"] == "valor informado sem centavos"
    assert history[-1]["prior_values"]["amount"] == 100.0


def test_position_without_financial_effect_is_voided_but_linked_position_is_blocked() -> None:
    position_id = portfolio.add_position(
        ticker="PETRN312",
        underlying="PETR4",
        trade_date="2026-09-15",
        qty=100,
        entry_price=0.5,
    )
    portfolio.delete_position(
        position_id=position_id,
        reason="cadastro de teste repetido",
        actor="auditor_teste",
    )

    assert portfolio.get_position(position_id)["status"] == "voided"
    assert portfolio.list_positions(include_closed=True) == []
    with db_transaction() as conn:
        history = list_change_history(
            conn,
            source_table="positions",
            source_id=position_id,
        )
    assert history[-1]["change_kind"] == "UPDATE"
    assert history[-1]["actor"] == "auditor_teste"

    linked_position_id = portfolio.add_position(
        ticker="PETRN313",
        underlying="PETR4",
        trade_date="2026-09-15",
        qty=100,
        entry_price=0.5,
    )
    finance.add_transaction(
        date="2026-09-15",
        type=finance.TransactionType.PREMIUM,
        amount=50.0,
        position_id=linked_position_id,
    )
    with pytest.raises(ValueError, match="lançamentos financeiros"):
        portfolio.delete_position(
            position_id=linked_position_id,
            reason="não pode anular isoladamente",
        )
