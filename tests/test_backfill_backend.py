import datetime as dt

from opcoes import backfill_yfinance as byf


class _FakeHistory:
    def __init__(self, rows):
        self._rows = list(rows)

    @property
    def empty(self):
        return not self._rows

    def iterrows(self):
        for row in self._rows:
            yield row

    def __len__(self):
        return len(self._rows)


class _FakeResult:
    def __init__(self, rows):
        self._rows = list(rows)

    def fetchall(self):
        return list(self._rows)


class _FakePostgresConn:
    def __init__(self, symbols=None):
        self.symbols = list(symbols or [])
        self.statements = []
        self.commit_calls = 0
        self.closed = False

    def execute(self, query, params=()):
        sql = str(query)
        self.statements.append((sql, tuple(params or ())))
        if "SELECT DISTINCT underlying FROM option_snapshots" in sql:
            return _FakeResult([{"underlying": symbol} for symbol in self.symbols])
        return _FakeResult([])

    def commit(self):
        self.commit_calls += 1

    def close(self):
        self.closed = True


def _fake_download(*_args, **_kwargs):
    return _FakeHistory(
        [
            (dt.datetime(2026, 2, 27, 10, 0, 0), {"Close": 10.25}),
            (dt.datetime(2026, 2, 28, 10, 0, 0), {"Close": 10.75}),
        ]
    )


def test_backfill_uses_postgres_upsert_and_closes_connection(monkeypatch):
    fake_conn = _FakePostgresConn()
    monkeypatch.setattr(byf, "open_db", lambda: fake_conn)
    monkeypatch.setattr(byf.yf, "download", _fake_download)

    byf.backfill_prices(days=5, underlyings=["PETR4"])

    sql_text = "\n".join(query for query, _ in fake_conn.statements)
    assert "ON CONFLICT (snapshot_date, underlying)" in sql_text
    assert "INSERT OR REPLACE INTO underlying_snapshots" not in sql_text
    assert fake_conn.commit_calls >= 2
    assert fake_conn.closed is True


def test_backfill_reads_symbols_from_database_when_not_provided(monkeypatch):
    fake_conn = _FakePostgresConn(symbols=["PETR4", "VALE3"])
    monkeypatch.setattr(byf, "open_db", lambda: fake_conn)
    monkeypatch.setattr(byf.yf, "download", _fake_download)

    byf.backfill_prices(days=5, underlyings=None)

    download_targets = [params for sql, params in fake_conn.statements if "INSERT INTO underlying_snapshots" in sql]
    assert len(download_targets) == 4
