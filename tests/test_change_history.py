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
    finance.delete_transaction(
        tx_id,
        reason="lançamento de teste duplicado",
        actor="auditor_teste",
    )

    with db_transaction() as conn:
        position_history = list_change_history(
            conn,
            source_table="positions",
            source_id=position_id,
        )
        ledger_history = list_change_history(
            conn,
            source_table="ledger",
            source_id=tx_id,
        )

        assert position_history[-1]["change_kind"] == "UPDATE"
        assert position_history[-1]["prior_values"]["notes"] == "registro inicial"
        assert ledger_history[-1]["change_kind"] == "DELETE"
        assert ledger_history[-1]["actor"] == "auditor_teste"
        assert ledger_history[-1]["reason"] == "lançamento de teste duplicado"

        history_id = ledger_history[-1]["id"]
        with pytest.raises(Exception, match="imutável"):
            conn.execute(
                "UPDATE record_history SET actor = ? WHERE id = ?",
                ("alterado", history_id),
            )


def test_anulation_requires_a_reason() -> None:
    tx_id = finance.add_transaction(
        date="2026-09-15",
        type=finance.TransactionType.DEPOSIT,
        amount=10.0,
    )

    with pytest.raises(ValueError, match="motivo"):
        finance.delete_transaction(tx_id, reason="")

    assert any(item.id == tx_id for item in finance.list_transactions(limit=20))
