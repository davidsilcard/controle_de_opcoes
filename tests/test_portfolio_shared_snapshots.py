from __future__ import annotations

from opcoes import portfolio


class _FakeResult:
    def __init__(self, rows):
        self._rows = list(rows)
        self.rowcount = len(self._rows)

    def fetchone(self):
        if not self._rows:
            return None
        return self._rows[0]

    def fetchall(self):
        return list(self._rows)


class _FakeDb:
    def execute(self, query, params=()):
        sql = " ".join(str(query).split())
        if "SELECT to_regclass" in sql:
            return _FakeResult([{"to_regclass": "positions"}])
        if "FROM positions p WHERE p.id =" in sql:
            return _FakeResult(
                [
                    {
                        "id": 1,
                        "ticker": "PETRA123",
                        "underlying": "PETR4",
                        "trade_date": "2026-04-07",
                        "qty": 100,
                        "entry_price": 1.2,
                        "fees": 0.0,
                        "status": "open",
                        "trade_type": "swing",
                        "side": "long",
                        "notes": "",
                    }
                ]
            )
        if "FROM positions p" in sql:
            return _FakeResult(
                [
                    {
                        "id": 1,
                        "ticker": "PETRA123",
                        "underlying": "PETR4",
                        "trade_date": "2026-04-07",
                        "qty": 100,
                        "entry_price": 1.2,
                        "fees": 0.0,
                        "status": "open",
                        "trade_type": "swing",
                        "side": "long",
                        "notes": "",
                    }
                ]
            )
        raise AssertionError(f"Consulta inesperada: {sql} {params}")

    def close(self):
        return None


def test_list_positions_uses_shared_snapshot_map(monkeypatch) -> None:
    fake_db = _FakeDb()
    monkeypatch.setattr(
        portfolio,
        "_resolve_conn",
        lambda conn=None, ensure_schema=False: (fake_db, False),
    )
    monkeypatch.setattr(
        portfolio,
        "fetch_latest_option_snapshots",
        lambda tickers: {
            "PETRA123": {
                "snapshot_date": "2026-04-07",
                "last_price_raw": "1,45",
                "last_score_total": "8,7",
                "last_trend_flag": "1",
                "last_vencimento": "17/04/2026",
                "last_dias_uteis": "8",
                "last_underlying_price": "34,10",
                "last_extrinsic_pct_spot": "2,5",
                "last_pct_2x": "12,0",
                "last_strike": "35,00",
            }
        },
    )

    rows = portfolio.list_positions(include_closed=True)

    assert len(rows) == 1
    assert rows[0]["last_price"] == 1.45
    assert rows[0]["score_total"] == 8.7
    assert rows[0]["underlying_price"] == 34.1
    assert rows[0]["strike"] == 35.0


def test_get_position_uses_shared_snapshot_map(monkeypatch) -> None:
    fake_db = _FakeDb()
    monkeypatch.setattr(
        portfolio,
        "_resolve_conn",
        lambda conn=None, ensure_schema=False: (fake_db, False),
    )
    monkeypatch.setattr(
        portfolio,
        "fetch_latest_option_snapshots",
        lambda tickers: {
            "PETRA123": {
                "snapshot_date": "2026-04-07",
                "last_price_raw": "1,45",
                "last_score_total": "8,7",
                "last_trend_flag": "1",
                "last_vencimento": "17/04/2026",
                "last_dias_uteis": "8",
                "last_underlying_price": "34,10",
                "last_extrinsic_pct_spot": "2,5",
                "last_pct_2x": "12,0",
                "last_strike": "35,00",
            }
        },
    )

    row = portfolio.get_position(1)

    assert row is not None
    assert row["last_price"] == 1.45
    assert row["vencimento"] == "17/04/2026"
