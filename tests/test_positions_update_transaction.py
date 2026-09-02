from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from html.parser import HTMLParser

import pytest
from flask import render_template

from opcoes import portfolio, web
from opcoes.holdings import HoldingValidationError
from opcoes.tax import build_position_tax_events


def _position(**changes) -> dict:
    return {
        "id": 501,
        "ticker": "BBASQ237",
        "underlying": "BBAS3",
        "trade_date": "2026-02-05",
        "qty": 100,
        "entry_price": 0.20,
        "fees": 0.07,
        "trade_type": "swing",
        "side": "short",
        "strategy_tag": "cash_put",
        "status": "closed",
        "exit_date": "2026-02-18",
        "exit_price": 0.0,
        "exit_reason": "Expiração",
        "partial_qty": 0,
        "partial_price": None,
        "partial_date": None,
        "irrf": 0.0,
        "is_simulated": False,
        "parent_position_id": None,
        "notes": "",
        "is_option": True,
        "premium_recorded": True,
        "last_price": None,
        "pl": None,
        "pl_pct": None,
        "breakeven_price": None,
        "score_total": None,
        "trend_flag": "",
        "realized_pl": None,
        "vencimento": None,
        "dias_uteis": None,
        **changes,
    }


class _FormPayload(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.values: dict[str, str] = {}
        self.select_name: str | None = None

    def handle_starttag(self, tag, attrs) -> None:
        attributes = dict(attrs)
        if tag == "input" and attributes.get("name"):
            self.values[attributes["name"]] = attributes.get("value", "")
        elif tag == "select":
            self.select_name = attributes.get("name")
        elif tag == "option" and self.select_name:
            if self.select_name not in self.values or "selected" in attributes:
                self.values[self.select_name] = attributes.get("value", "")

    def handle_endtag(self, tag) -> None:
        if tag == "select":
            self.select_name = None


class _TransactionalPosition:
    """Banco em memória que exige uma única transação para a rota inteira."""

    def __init__(self, monkeypatch, position: dict) -> None:
        self.position = deepcopy(position)
        self.ledger = {"premium": 19.93, "buyback": 0.0, "realized": 19.93}
        self.conn = object()
        self.active = False
        self.events: list[str] = []
        self.reads: list[dict] = []
        self.updates: list[dict] = []
        self.syncs: list[dict] = []
        self.fail_sync = False
        self.on_enter = None
        monkeypatch.setattr(web, "db_transaction", self.transaction)
        monkeypatch.setattr(web, "get_position", self.get_position)
        monkeypatch.setattr(web, "update_position", self.update_position)
        monkeypatch.setattr(web, "list_positions", lambda **_kwargs: [])
        monkeypatch.setattr(web, "validate_covered_call_availability", lambda **_kwargs: None)
        monkeypatch.setattr(web.finance, "sync_position_closure_effects", self.sync)
        self.app = web.create_app()
        self.app.testing = True

    @contextmanager
    def transaction(self):
        assert not self.active
        if self.on_enter is not None:
            self.on_enter()
        before_position = deepcopy(self.position)
        before_ledger = deepcopy(self.ledger)
        self.active = True
        self.events.append("begin")
        try:
            yield self.conn
        except Exception:
            self.position = before_position
            self.ledger = before_ledger
            self.events.append("rollback")
            raise
        else:
            self.events.append("commit")
        finally:
            self.active = False

    def get_position(self, position_id, *, conn=None, for_update=False):
        assert self.active and conn is self.conn
        assert position_id == self.position["id"]
        if not self.reads:
            assert for_update is True
        self.events.append("read_locked" if for_update else "read")
        self.reads.append({"for_update": for_update, "position": deepcopy(self.position)})
        result = deepcopy(self.position)
        result["partial_qty"] = int(result.get("partial_qty") or 0)
        return result

    def update_position(self, *, position_id, conn, **changes):
        assert self.active and conn is self.conn
        assert position_id == self.position["id"]
        # Reproduz a conversão real que falhava quando a rota passava fees=None.
        changes["fees"] = float(changes["fees"])
        self.events.append("update")
        self.updates.append(deepcopy(changes))
        self.position.update(changes)

    def sync(self, *, position_id, position, conn):
        assert self.active and conn is self.conn
        assert position_id == self.position["id"]
        self.events.append("sync")
        self.syncs.append(deepcopy(position))
        close_qty = max(int(position["qty"]) - int(position.get("partial_qty") or 0), 0)
        self.ledger["buyback"] = (
            -round(float(position.get("exit_price") or 0.0) * close_qty, 2)
            if position["status"] == "closed"
            else 0.0
        )
        self.ledger["realized"] = sum(event.amount for event in build_position_tax_events(position))
        if self.fail_sync:
            raise RuntimeError("Falha simulada no ledger")

    def payload(self, **changes) -> dict[str, str]:
        with self.app.test_request_context("/positions"):
            html = render_template(
                "partials/positions_table.html",
                positions=[self.position],
                next_url="/positions",
            )
        parser = _FormPayload()
        parser.feed(html)
        return {**parser.values, **changes}

    def post(self, payload):
        return self.app.test_client().post(
            f"/positions/update/{self.position['id']}", data=payload
        )


@pytest.mark.parametrize(
    ("strategy_tag", "ticker"),
    [("cash_put", "BBASQ237"), ("covered_call", "BBASC237")],
)
@pytest.mark.parametrize("exit_reason", ["Expiração", "Exercício"])
@pytest.mark.parametrize("is_simulated", [False, True])
def test_notes_roundtrip_preserves_zero_original_reason_and_ledger(
    monkeypatch, strategy_tag, ticker, exit_reason, is_simulated
) -> None:
    store = _TransactionalPosition(
        monkeypatch,
        _position(
            strategy_tag=strategy_tag,
            ticker=ticker,
            exit_reason=exit_reason,
            is_simulated=is_simulated,
        ),
    )
    ledger_before = deepcopy(store.ledger)
    payload = store.payload(notes="Conferido na nota")

    assert payload["exit_price"] == "0.0"
    assert payload["exit_reason"] == exit_reason
    assert store.post(payload).status_code == 302

    assert store.position["exit_price"] == 0.0
    assert store.position["exit_reason"] == exit_reason
    assert store.position["notes"] == "Conferido na nota"
    assert store.syncs == []
    assert store.ledger == ledger_before
    assert store.events == ["begin", "read_locked", "update", "read", "commit"]


@pytest.mark.parametrize(
    ("original", "alias"),
    [
        ("Expiração", "vencimento_sem_valor"),
        ("Expiração", "expiracao"),
        ("Exercício", "exercicio"),
        ("Expirou", "vencimento_sem_valor"),
    ],
)
def test_legacy_zero_blank_and_reason_alias_do_not_resynchronize(monkeypatch, original, alias) -> None:
    store = _TransactionalPosition(monkeypatch, _position(exit_reason=original))
    response = store.post(store.payload(exit_price="", exit_reason=alias, notes="Apenas nota"))

    assert response.status_code == 302
    assert store.position["exit_price"] == 0.0
    assert store.position["exit_reason"] == original
    assert store.syncs == []


def test_template_preserves_custom_reason_and_all_numeric_zeroes(monkeypatch) -> None:
    store = _TransactionalPosition(
        monkeypatch,
        _position(exit_reason="Baixa técnica documentada", fees=0.0, partial_price=0.0),
    )
    payload = store.payload()

    assert payload["exit_reason"] == "Baixa técnica documentada"
    for field in ("fees", "irrf", "partial_price", "exit_price"):
        assert payload[field] == "0.0"
    assert payload["partial_qty"] == "0"


@pytest.mark.parametrize(("previous_fees", "expected_syncs"), [(0.0, 0), (0.07, 1)])
def test_blank_fees_are_zero_not_none(monkeypatch, previous_fees, expected_syncs) -> None:
    store = _TransactionalPosition(monkeypatch, _position(fees=previous_fees))
    response = store.post(store.payload(fees="", notes="Sem despesas"))

    assert response.status_code == 302
    assert store.position["fees"] == 0.0
    assert len(store.syncs) == expected_syncs


def test_legacy_partial_zero_blank_is_preserved_for_notes(monkeypatch) -> None:
    store = _TransactionalPosition(
        monkeypatch,
        _position(partial_qty=25, partial_price=0.0, partial_date="2026-02-10"),
    )
    response = store.post(store.payload(partial_price="", notes="Parcial conferida"))

    assert response.status_code == 302
    assert store.position["partial_price"] == 0.0
    assert store.syncs == []


def test_buyback_change_synchronizes_in_the_locked_transaction(monkeypatch) -> None:
    store = _TransactionalPosition(
        monkeypatch, _position(exit_price=0.01, exit_reason="recompra_encerramento")
    )
    response = store.post(store.payload(exit_price="0.02"))

    assert response.status_code == 302
    assert len(store.syncs) == 1
    assert store.syncs[0]["exit_price"] == 0.02
    assert store.ledger["buyback"] == -2.0
    assert store.ledger["realized"] == pytest.approx(17.93)
    assert store.events == ["begin", "read_locked", "update", "read", "sync", "commit"]


def test_buyback_notes_only_do_not_synchronize(monkeypatch) -> None:
    store = _TransactionalPosition(
        monkeypatch, _position(exit_price=0.01, exit_reason="recompra_encerramento")
    )

    assert store.post(store.payload(notes="Recompra conferida")).status_code == 302
    assert store.syncs == []


def test_reopening_buyback_still_synchronizes_closure_effects(monkeypatch) -> None:
    store = _TransactionalPosition(
        monkeypatch, _position(exit_price=0.01, exit_reason="recompra_encerramento")
    )
    response = store.post(store.payload(status="open"))

    assert response.status_code == 302
    assert store.position["exit_date"] is None
    assert store.position["exit_price"] is None
    assert store.position["exit_reason"] is None
    assert len(store.syncs) == 1
    assert store.ledger["buyback"] == 0.0
    assert store.ledger["realized"] == 0.0


def test_reopening_covered_call_without_stock_keeps_position_and_ledger(monkeypatch) -> None:
    store = _TransactionalPosition(
        monkeypatch,
        _position(
            ticker="BBASC237",
            strategy_tag="covered_call",
            exit_price=0.01,
            exit_reason="recompra_encerramento",
        ),
    )
    position_before = deepcopy(store.position)
    ledger_before = deepcopy(store.ledger)

    def reject_uncovered_call(**_kwargs):
        raise HoldingValidationError("Primeiro informe o estoque consolidado.", ticker="BBAS3")

    monkeypatch.setattr(web, "validate_covered_call_availability", reject_uncovered_call)
    response = store.post(store.payload(status="open"))

    assert response.status_code == 302
    assert "holding_error=" in response.headers["Location"]
    assert store.position == position_before
    assert store.ledger == ledger_before
    assert store.updates == []
    assert store.syncs == []


def test_sync_failure_rolls_back_position_and_ledger(monkeypatch) -> None:
    store = _TransactionalPosition(
        monkeypatch, _position(exit_price=0.01, exit_reason="recompra_encerramento")
    )
    position_before = deepcopy(store.position)
    ledger_before = deepcopy(store.ledger)
    store.fail_sync = True

    with pytest.raises(RuntimeError, match="Falha simulada"):
        store.post(store.payload(exit_price="0.02", notes="Não pode persistir pela metade"))

    assert store.position == position_before
    assert store.ledger == ledger_before
    assert store.events[-1] == "rollback"
    assert "commit" not in store.events


def test_financial_comparison_uses_current_locked_row_after_concurrent_change(monkeypatch) -> None:
    store = _TransactionalPosition(
        monkeypatch, _position(exit_price=0.01, exit_reason="recompra_encerramento")
    )
    stale_payload = store.payload(notes="Formulário aberto antes da outra alteração")

    def concurrent_commit() -> None:
        store.position["exit_price"] = 0.02
        store.ledger["buyback"] = -2.0
        store.ledger["realized"] = 17.93

    store.on_enter = concurrent_commit
    response = store.post(stale_payload)

    assert response.status_code == 302
    assert store.reads[0]["position"]["exit_price"] == 0.02
    assert store.reads[0]["for_update"] is True
    assert len(store.syncs) == 1
    assert store.position["exit_price"] == 0.01
    assert store.ledger["buyback"] == -1.0
    assert store.ledger["realized"] == pytest.approx(18.93)


def test_locked_update_still_rejects_strategy_identity_changes(monkeypatch) -> None:
    store = _TransactionalPosition(monkeypatch, _position())
    response = store.post(store.payload(strategy_tag="ranking"))

    assert response.status_code == 302
    assert "position_error=" in response.headers["Location"]
    assert store.position["strategy_tag"] == "cash_put"
    assert store.updates == []
    assert store.syncs == []


def test_get_position_for_update_requires_existing_transaction() -> None:
    with pytest.raises(ValueError, match="transação existente"):
        portfolio.get_position(1, for_update=True)


def test_get_position_for_update_adds_row_lock_without_owning_connection(monkeypatch) -> None:
    queries = []
    row = {"id": 1, "ticker": "BBASQ237"}

    class Connection:
        def execute(self, query, params):
            queries.append((query, params))
            return self

        def fetchone(self):
            return row

        def close(self):
            pytest.fail("A conexão pertence à transação chamadora")

    conn = Connection()
    monkeypatch.setattr(portfolio, "_resolve_conn", lambda supplied: (supplied, False))
    monkeypatch.setattr(portfolio, "_table_exists", lambda *_args: True)
    monkeypatch.setattr(portfolio, "fetch_latest_option_snapshots", lambda _tickers: {})
    monkeypatch.setattr(portfolio, "_attach_snapshot_fields", lambda supplied, _snapshots: supplied)
    monkeypatch.setattr(portfolio, "_row_to_dict", dict)

    assert portfolio.get_position(1, conn=conn, for_update=True) == row
    assert queries == [("SELECT p.* FROM positions p WHERE p.id = ? FOR UPDATE", (1,))]
