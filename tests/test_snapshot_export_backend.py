from pathlib import Path

from opcoes import snapshot_export as se


class _FakeResult:
    def __init__(self, rows):
        self._rows = list(rows)

    def fetchone(self):
        if not self._rows:
            return None
        return self._rows[0]

    def fetchall(self):
        return list(self._rows)


class _FakeConn:
    def __init__(self):
        self.backend = "postgres"
        self.closed = False
        self.queries = []
        self.commit_calls = 0

    def execute(self, query, params=()):
        sql = str(query)
        self.queries.append((sql, tuple(params or ())))

        if "to_regclass" in sql:
            return _FakeResult([{"reg": "admin.option_snapshots"}])
        if "information_schema.columns" in sql:
            return _FakeResult([{"column_name": "snapshot_date"}, {"column_name": "ticker"}])
        if "MAX(snapshot_date)" in sql:
            return _FakeResult([{"snapshot_date": "2026-02-27"}])
        if "FROM option_snapshots" in sql and "WHERE snapshot_date" in sql:
            return _FakeResult(
                [
                    {
                        "ticker": "PETRA123",
                        "underlying": "PETR4",
                        "snapshot_date": "2026-02-27",
                    }
                ]
            )
        return _FakeResult([])

    def commit(self):
        self.commit_calls += 1

    def close(self):
        self.closed = True


def test_export_snapshot_uses_active_backend_connection(monkeypatch, workspace_tmp_path: Path):
    fake_conn = _FakeConn()
    monkeypatch.setattr(se, "open_db", lambda: fake_conn)

    out = workspace_tmp_path / "latest.csv"
    result = se.export_snapshot(output_csv=out, snapshot_date=None)

    assert result == out
    assert fake_conn.closed is True
    text = out.read_text(encoding="utf-8")
    assert "ticker" in text.splitlines()[0]
    assert "PETRA123" in text
    assert any("MAX(snapshot_date)" in sql for sql, _ in fake_conn.queries)
