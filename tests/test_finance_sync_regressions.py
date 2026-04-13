from __future__ import annotations

from dataclasses import dataclass

from opcoes import finance
from opcoes.tax import TaxEvent


@dataclass
class _FakeResult:
    rows: list[dict]

    def fetchall(self):
        return list(self.rows)

    def fetchone(self):
        return self.rows[0] if self.rows else None


class _FakeConn:
    def __init__(self) -> None:
        self.queries: list[tuple[str, tuple[object, ...]]] = []

    def execute(self, query: str, params=()):
        self.queries.append((query, tuple(params)))
        return _FakeResult([])


def test_sync_position_closure_effects_reuses_current_transaction_conn(
    monkeypatch,
) -> None:
    fake_db = _FakeConn()
    seen: dict[str, object] = {}

    monkeypatch.setattr(
        "opcoes.finance._resolve_conn",
        lambda conn=None, ensure_schema=False: (fake_db, False),
    )

    def fake_get_position(position_id: int, conn=None):
        seen["conn"] = conn
        return {
            "id": position_id,
            "ticker": "PETRA456",
            "side": "long",
        }

    monkeypatch.setattr("opcoes.portfolio.get_position", fake_get_position)
    monkeypatch.setattr(
        "opcoes.finance.sync_position_realized_pnl",
        lambda **_kwargs: {"close": 1003.4},
    )

    result = finance.sync_position_closure_effects(position_id=6)

    assert seen["conn"] is fake_db
    assert result == {"buyback": 0.0, "realized": {"close": 1003.4}}


def test_sync_position_realized_pnl_reuses_current_transaction_conn(
    monkeypatch,
) -> None:
    fake_db = _FakeConn()
    seen: dict[str, object] = {}
    inserted: list[dict[str, object]] = []

    monkeypatch.setattr(
        "opcoes.finance._resolve_conn",
        lambda conn=None, ensure_schema=False: (fake_db, False),
    )

    def fake_get_position(position_id: int, conn=None):
        seen["conn"] = conn
        return {
            "id": position_id,
            "ticker": "PETRA456",
            "underlying": "PETR4",
            "trade_type": "swing",
            "is_simulated": False,
        }

    monkeypatch.setattr("opcoes.portfolio.get_position", fake_get_position)
    monkeypatch.setattr(
        "opcoes.tax.build_position_tax_events",
        lambda _pos: [
            TaxEvent(
                date="2026-03-30",
                period="2026-03",
                trade_type="swing",
                qty=100,
                amount=1003.4,
                irrf=0.06,
                phase="close",
                position_id=6,
                ticker="PETRA456",
                underlying="PETR4",
                is_simulated=False,
            )
        ],
    )
    monkeypatch.setattr(
        "opcoes.finance.add_transaction",
        lambda **kwargs: inserted.append(kwargs),
    )

    result = finance.sync_position_realized_pnl(position_id=6)

    assert seen["conn"] is fake_db
    assert result == {"close": 1003.4}
    assert inserted == [
        {
            "date": "2026-03-30",
            "type": finance.TransactionType.REALIZED,
            "amount": 1003.4,
            "description": "Resultado encerramento PETRA456 (100x, swing)",
            "position_id": 6,
            "is_simulated": False,
            "conn": fake_db,
        }
    ]
