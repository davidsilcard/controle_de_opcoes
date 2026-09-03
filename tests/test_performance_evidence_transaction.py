from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy

import pytest

from opcoes import portfolio, web


def _performance_position(**changes) -> dict:
    return {
        "id": 701,
        "ticker": "PETRD521",
        "underlying": "PETR4",
        "trade_date": "2026-04-06",
        "qty": 100,
        "entry_price": 0.53,
        "side": "short",
        "strategy_tag": "covered_call",
        "status": "closed",
        "exit_date": "2026-04-17",
        "exit_price": 0.0,
        "exit_reason": "Expiração",
        "is_simulated": False,
        "parent_position_id": None,
        "contract_strike": None,
        "contract_expiry": "2026-04-17",
        "capital_committed": None,
        "capital_source": None,
        "performance_source_ref": "Calendário oficial B3",
        "performance_evidence_state": "pending",
        "performance_evidence_note": None,
        **changes,
    }


class _PerformanceMetadataStore:
    """Contrato em memória: apenas metadados podem mudar na transação bloqueada."""

    def __init__(self, monkeypatch, position: dict) -> None:
        self.position = deepcopy(position)
        self.ledger = [
            {"position_id": position["id"], "type": "PREMIUM", "amount": 53.0},
            {"position_id": position["id"], "type": "REALIZED", "amount": 53.0},
        ]
        self.holdings = {
            "PETR4": {"quantity": 100, "average_price": 31.90},
        }
        self.holding_events = [
            {"ticker": "PETR4", "event_type": "MANUAL_SET", "quantity": 100},
        ]
        self.conn = object()
        self.active = False
        self.events: list[str] = []
        self.updates: list[dict] = []

        monkeypatch.setattr(web, "db_transaction", self.transaction)
        monkeypatch.setattr(web, "get_position", self.get_position)
        monkeypatch.setattr(
            web,
            "update_position_performance_metadata",
            self.update_performance_metadata,
            raising=False,
        )
        monkeypatch.setattr(web, "update_position", self.reject_generic_update)
        monkeypatch.setattr(
            web.finance,
            "sync_position_closure_effects",
            self.reject_financial_write,
        )
        monkeypatch.setattr(web, "upsert_holding", self.reject_holding_write)

        self.app = web.create_app()
        self.app.testing = True

    @contextmanager
    def transaction(self):
        assert not self.active
        before = (
            deepcopy(self.position),
            deepcopy(self.ledger),
            deepcopy(self.holdings),
            deepcopy(self.holding_events),
        )
        self.active = True
        self.events.append("begin")
        try:
            yield self.conn
        except Exception:
            (
                self.position,
                self.ledger,
                self.holdings,
                self.holding_events,
            ) = before
            self.events.append("rollback")
            raise
        else:
            self.events.append("commit")
        finally:
            self.active = False

    def get_position(self, position_id, *, conn=None, for_update=False):
        assert self.active, "a posição deve ser lida dentro da transação"
        assert conn is self.conn, "a leitura deve reutilizar a conexão da transação"
        assert for_update is True, "a posição deve ser bloqueada antes da validação"
        assert position_id == self.position["id"]
        self.events.append("read_locked")
        return deepcopy(self.position)

    def update_performance_metadata(self, *, position_id, conn, **changes):
        assert self.active and conn is self.conn
        assert position_id == self.position["id"]
        allowed = {
            "contract_strike",
            "contract_expiry",
            "capital_committed",
            "capital_source",
            "performance_source_ref",
            "performance_evidence_state",
            "performance_evidence_note",
            "parent_position_id",
        }
        assert set(changes) <= allowed
        self.events.append("metadata_update")
        self.updates.append(deepcopy(changes))
        self.position.update(changes)

    @staticmethod
    def reject_generic_update(**_kwargs):
        pytest.fail("a auditoria não pode usar a atualização genérica de posições")

    @staticmethod
    def reject_financial_write(**_kwargs):
        pytest.fail("metadados de auditoria não podem sincronizar o ledger")

    @staticmethod
    def reject_holding_write(**_kwargs):
        pytest.fail("metadados de auditoria não podem alterar o estoque")

    def post(self, suffix: str = "", *, data: dict[str, str]):
        return self.app.test_client().post(
            f"/performance/contract/{self.position['id']}{suffix}", data=data
        )


def _financial_state(store: _PerformanceMetadataStore) -> tuple:
    return (
        deepcopy(store.ledger),
        deepcopy(store.holdings),
        deepcopy(store.holding_events),
    )


def test_performance_metadata_update_locks_row_and_preserves_financial_state(
    monkeypatch,
) -> None:
    store = _PerformanceMetadataStore(monkeypatch, _performance_position())
    before = _financial_state(store)

    response = store.post(data={"mode": "real", "capital_committed": "6600.00"})

    assert response.status_code == 302
    assert store.position["capital_committed"] == pytest.approx(6600.0)
    assert store.position["capital_source"] == "garantia_declarada_usuario"
    assert _financial_state(store) == before
    assert store.events == ["begin", "read_locked", "metadata_update", "commit"]


def test_documents_exhausted_locks_row_and_never_overwrites_previous_source(
    monkeypatch,
) -> None:
    store = _PerformanceMetadataStore(monkeypatch, _performance_position())
    before = _financial_state(store)

    response = store.post(
        "/documents-exhausted",
        data={
            "mode": "real",
            "performance_source_ref": "Notas BTG e Clear auditadas",
            "performance_evidence_note": "Strike não comprovado nos documentos disponíveis.",
        },
    )

    assert response.status_code == 302
    assert store.position["performance_source_ref"] == (
        "Calendário oficial B3 | Notas BTG e Clear auditadas"
    )
    assert store.position["performance_evidence_state"] == "documents_exhausted"
    assert store.position["performance_evidence_note"] == (
        "Strike não comprovado nos documentos disponíveis."
    )
    assert _financial_state(store) == before
    assert store.events == ["begin", "read_locked", "metadata_update", "commit"]


def test_reopen_evidence_locks_row_and_preserves_source_note_and_financial_state(
    monkeypatch,
) -> None:
    store = _PerformanceMetadataStore(
        monkeypatch,
        _performance_position(
            performance_evidence_state="documents_exhausted",
            performance_evidence_note="Strike não comprovado.",
        ),
    )
    before = _financial_state(store)

    response = store.post("/reopen-evidence", data={"mode": "real"})

    assert response.status_code == 302
    assert store.position["performance_evidence_state"] == "pending"
    assert store.position["performance_source_ref"] == "Calendário oficial B3"
    assert store.position["performance_evidence_note"] == "Strike não comprovado."
    assert _financial_state(store) == before
    assert store.events == ["begin", "read_locked", "metadata_update", "commit"]


def test_specific_performance_metadata_update_never_runs_schema_bootstrap(
    monkeypatch,
) -> None:
    queries: list[tuple[str, list[object]]] = []
    conn = object()

    class Result:
        rowcount = 1

    class Db:
        def execute(self, query, params):
            queries.append((query, list(params)))
            return Result()

    db = Db()

    def resolve_connection(supplied, *, ensure_schema=False):
        assert supplied is conn
        assert ensure_schema is False
        return db, False

    monkeypatch.setattr(portfolio, "_resolve_conn", resolve_connection)
    monkeypatch.setattr(
        portfolio,
        "_ensure_tables",
        lambda *_args, **_kwargs: pytest.fail(
            "a gravação específica não pode executar DDL ou migração global"
        ),
    )

    portfolio.update_position_performance_metadata(
        position_id=701,
        conn=conn,
        capital_committed=6600.0,
        capital_source="garantia_declarada_usuario",
    )

    assert len(queries) == 1
    query, params = queries[0]
    assert query.startswith("UPDATE positions SET ")
    assert "capital_committed = ?" in query
    assert "capital_source = ?" in query
    assert params == [6600.0, "garantia_declarada_usuario", 701]
