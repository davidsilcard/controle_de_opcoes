import datetime as dt

from opcoes.retention import RetentionPolicy, apply_retention


class _FakeResult:
    def __init__(self, rows=None, *, rowcount: int = 0):
        self._rows = list(rows or [])
        self.rowcount = rowcount

    def fetchone(self):
        if not self._rows:
            return None
        return self._rows[0]

    def fetchall(self):
        return list(self._rows)


class _FakeConn:
    def __init__(self):
        self.closed = False
        self.committed = False
        self.tables = {
            "ranking_entries",
            "ranking_runs",
            "option_snapshots",
            "underlying_snapshots",
            "iv_history",
            "flow_history",
            "fundamentus_snapshots",
            "fundamentus_runs",
            "fundamentus_signals",
            "fundamentus_filter_runs",
            "fundamentus_snapshot_integrity",
        }
        self.counts = {
            "ranking_entries": 10,
            "ranking_runs": 2,
            "option_snapshots_age": 100,
            "option_snapshots_expired": 25,
            "underlying_snapshots": 40,
            "iv_history_age": 15,
            "iv_history_expired": 4,
            "flow_history": 12,
            "fundamentus_snapshots": 7,
            "fundamentus_runs": 1,
            "fundamentus_signals": 9,
            "fundamentus_filter_runs": 1,
            "fundamentus_snapshot_integrity": 2,
        }

    def execute(self, query: str, params=()):
        if "information_schema.tables" in query:
            table = params[0]
            return _FakeResult([{"exists": 1}] if table in self.tables else [])

        label = self._label_for_query(query)
        if query.lstrip().startswith("SELECT COUNT(*) AS total"):
            return _FakeResult([{"total": self.counts.get(label, 0)}])
        if query.lstrip().startswith("DELETE FROM"):
            return _FakeResult([], rowcount=self.counts.get(label, 0))
        raise AssertionError(f"Unexpected query: {query}")

    def commit(self) -> None:
        self.committed = True

    def close(self) -> None:
        self.closed = True

    @staticmethod
    def _label_for_query(query: str) -> str:
        compact = " ".join(query.split())
        if '"option_snapshots"' in compact:
            return (
                "option_snapshots_expired"
                if "to_date(vencimento" in compact
                else "option_snapshots_age"
            )
        if '"iv_history"' in compact:
            return (
                "iv_history_expired"
                if "to_date(vencimento" in compact
                else "iv_history_age"
            )
        for name in (
            "ranking_entries",
            "ranking_runs",
            "underlying_snapshots",
            "flow_history",
            "fundamentus_snapshots",
            "fundamentus_runs",
            "fundamentus_signals",
            "fundamentus_filter_runs",
            "fundamentus_snapshot_integrity",
        ):
            if f'"{name}"' in compact:
                return name
        raise AssertionError(f"Could not identify query label: {query}")


def test_apply_retention_dry_run_reports_expected_counts(monkeypatch) -> None:
    fake = _FakeConn()
    monkeypatch.setattr("opcoes.retention._connect", lambda db_path=None: fake)

    report = apply_retention(
        policy=RetentionPolicy(),
        today=dt.date(2026, 4, 1),
        dry_run=True,
    )

    assert report["dry_run"] is True
    assert report["today"] == "2026-04-01"
    assert report["cutoffs"]["option_snapshot_before"] == "2025-12-02"
    assert report["cutoffs"]["underlying_snapshot_before"] == "2025-02-25"
    assert report["removed"]["option_snapshots"] == 125
    assert report["removed"]["iv_history"] == 19
    assert report["removed"]["fundamentus_snapshots"] == 7
    assert "positions" in report["preserved_forever"]
    assert fake.committed is False
    assert fake.closed is True


def test_apply_retention_executes_commit_when_not_dry_run(monkeypatch) -> None:
    fake = _FakeConn()
    monkeypatch.setattr("opcoes.retention._connect", lambda db_path=None: fake)

    report = apply_retention(
        policy=RetentionPolicy(flow_history_days=30, ranking_days=45),
        today=dt.date(2026, 4, 1),
        dry_run=False,
    )

    assert report["dry_run"] is False
    assert report["policy"]["flow_history_days"] == 30
    assert report["policy"]["ranking_days"] == 45
    assert report["removed"]["flow_history"] == 12
    assert report["removed"]["ranking_entries"] == 10
    assert fake.committed is True
    assert fake.closed is True
