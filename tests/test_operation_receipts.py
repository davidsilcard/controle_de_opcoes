from __future__ import annotations

import hashlib
import uuid

import pytest

from opcoes import finance
from opcoes.db import db_transaction
from opcoes.operation_receipts import (
    OperationReceiptError,
    claim_operation_receipt,
    complete_operation_receipt,
    ensure_operation_receipts,
)
from opcoes.web import create_app


class _Result:
    def __init__(self, row=None, *, rowcount: int = 1):
        self._row = row
        self.rowcount = rowcount

    def fetchone(self):
        return self._row


class _FakeConn:
    def __init__(self):
        self.queries: list[tuple[str, tuple[object, ...]]] = []

    def execute(self, query: str, params=()):
        self.queries.append((query, tuple(params)))
        if "INSERT INTO operation_receipts" in query:
            return _Result({"id": 41})
        return _Result()


def _fingerprint(value: str = "cadastro") -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def test_receipts_schema_has_unique_key_and_no_financial_mutation() -> None:
    conn = _FakeConn()

    ensure_operation_receipts(conn)
    receipt = claim_operation_receipt(
        conn,
        command_name="positions.add",
        idempotency_key=str(uuid.uuid4()),
        payload_hash=_fingerprint(),
        actor="david",
    )
    complete_operation_receipt(
        conn,
        receipt_id=receipt.id,
        result_entity_type="position",
        result_entity_id=88,
    )

    sql = "\n".join(query for query, _params in conn.queries)
    assert "CREATE TABLE IF NOT EXISTS operation_receipts" in sql
    assert "UNIQUE (command_name, idempotency_key)" in sql
    assert "INSERT INTO positions" not in sql
    assert "INSERT INTO ledger" not in sql
    assert receipt.id == 41


def test_receipt_rejects_invalid_or_reused_confirmation_data() -> None:
    conn = _FakeConn()

    with pytest.raises(OperationReceiptError, match="inválida"):
        claim_operation_receipt(
            conn,
            command_name="positions.add",
            idempotency_key="not-a-uuid",
            payload_hash=_fingerprint(),
        )
    with pytest.raises(OperationReceiptError, match="Conteúdo"):
        claim_operation_receipt(
            conn,
            command_name="positions.add",
            idempotency_key=str(uuid.uuid4()),
            payload_hash="invalid",
        )


@pytest.mark.requires_postgres
def test_repeated_receipt_returns_original_result_and_rejects_changed_payload() -> None:
    key = str(uuid.uuid4())
    original_hash = _fingerprint("primeiro cadastro")

    with db_transaction() as conn:
        first = claim_operation_receipt(
            conn,
            command_name="positions.add",
            idempotency_key=key,
            payload_hash=original_hash,
            actor="david",
        )
        complete_operation_receipt(
            conn,
            receipt_id=first.id,
            result_entity_type="position",
            result_entity_id=321,
        )

    with db_transaction() as conn:
        replay = claim_operation_receipt(
            conn,
            command_name="positions.add",
            idempotency_key=key,
            payload_hash=original_hash,
            actor="david",
        )
        assert replay.replayed is True
        assert replay.result_entity_type == "position"
        assert replay.result_entity_id == 321

    with db_transaction() as conn:
        with pytest.raises(OperationReceiptError, match="outros dados"):
            claim_operation_receipt(
                conn,
                command_name="positions.add",
                idempotency_key=key,
                payload_hash=_fingerprint("dados alterados"),
                actor="david",
            )


@pytest.mark.requires_postgres
def test_manual_finance_repeated_post_creates_one_ledger_entry_and_receipt() -> None:
    app = create_app()
    app.testing = True
    client = app.test_client()
    form = {
        "date": "2026-09-17",
        "type": finance.TransactionType.DEPOSIT.value,
        "amount": "100.00",
        "description": "Aporte de teste idempotente",
        "is_simulated": "0",
        "_operation_key": str(uuid.uuid4()),
    }

    first = client.post("/finance/add", data=form)
    repeated = client.post("/finance/add", data=form)

    assert first.status_code in (302, 303)
    assert repeated.status_code in (302, 303)
    entries = [
        tx
        for tx in finance.get_transactions(limit=20)
        if tx.description == "Aporte de teste idempotente"
    ]
    assert len(entries) == 1
    with db_transaction() as conn:
        receipts = conn.execute(
            "SELECT command_name, result_entity_type FROM operation_receipts"
        ).fetchall()
    assert [dict(row) for row in receipts] == [
        {"command_name": "finance.manual_add", "result_entity_type": "ledger"}
    ]
