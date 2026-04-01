from __future__ import annotations

import datetime as dt

from opcoes.service_runs import (
    finish_service_run,
    get_service_dashboard,
    list_service_runs,
    start_service_run,
)


class _FakeResult:
    def __init__(self, rows=None, *, rowcount: int = 0):
        self._rows = list(rows or [])
        self.rowcount = rowcount

    def fetchall(self):
        return list(self._rows)


class _FakeConn:
    def __init__(self):
        self.rows = []
        self.commits = 0
        self.closed = 0

    def execute(self, query: str, params=()):
        compact = " ".join(query.split())
        if compact.startswith("CREATE TABLE IF NOT EXISTS service_runs"):
            return _FakeResult([])
        if compact.startswith("CREATE INDEX IF NOT EXISTS idx_service_runs_service_started"):
            return _FakeResult([])
        if compact.startswith("CREATE INDEX IF NOT EXISTS idx_service_runs_status_started"):
            return _FakeResult([])
        if compact.startswith("INSERT INTO service_runs"):
            row = {
                "id": params[0],
                "service_key": params[1],
                "trigger_type": params[2],
                "status": "running",
                "started_at": params[3],
                "scheduled_for": params[4],
                "step": params[5],
                "summary": params[6],
                "error_message": None,
                "finished_at": None,
                "duration_seconds": None,
            }
            self.rows.insert(0, row)
            return _FakeResult([], rowcount=1)
        if compact.startswith("UPDATE service_runs SET status ="):
            run_id = params[7]
            for row in self.rows:
                if row["id"] == run_id:
                    row["status"] = params[0]
                    row["finished_at"] = params[1]
                    row["duration_seconds"] = max(
                        int((params[2] - row["started_at"]).total_seconds()),
                        0,
                    )
                    row["step"] = params[3]
                    row["summary"] = params[4]
                    row["error_message"] = params[5]
                    return _FakeResult([], rowcount=1)
            return _FakeResult([], rowcount=0)
        if "FROM service_runs WHERE service_key =" in compact:
            service_key = params[0]
            limit = params[1]
            rows = [dict(row) for row in self.rows if row["service_key"] == service_key]
            return _FakeResult(rows[:limit])
        if "FROM service_runs ORDER BY started_at DESC" in compact:
            limit = params[0]
            return _FakeResult([dict(row) for row in self.rows[:limit]])
        raise AssertionError(f"Unexpected query: {query}")

    def commit(self) -> None:
        self.commits += 1

    def close(self) -> None:
        self.closed += 1


def test_service_run_lifecycle_and_dashboard(monkeypatch) -> None:
    fake = _FakeConn()
    monkeypatch.setattr("opcoes.service_runs._connect", lambda: fake)

    run_id = start_service_run(
        service_key="scrape_cycle",
        trigger_type="systemd",
        summary="Ciclo iniciado",
        scheduled_for=dt.datetime(2026, 4, 1, 9, 0, tzinfo=dt.timezone.utc),
    )

    assert run_id
    assert fake.rows[0]["status"] == "running"
    assert fake.commits == 1

    updated = finish_service_run(
        run_id,
        status="success",
        step="done",
        summary="Ciclo concluido",
    )

    assert updated is True
    assert fake.rows[0]["status"] == "success"
    assert fake.rows[0]["summary"] == "Ciclo concluido"
    assert fake.rows[0]["duration_seconds"] is not None

    rows = list_service_runs(limit=5)
    assert len(rows) == 1
    assert rows[0]["service_key"] == "scrape_cycle"

    dashboard = get_service_dashboard(
        limit=5,
        now_utc=dt.datetime(2026, 4, 1, 12, 0, tzinfo=dt.timezone.utc),
    )
    assert dashboard["services"][0]["label"] == "Ciclo diario do scraper"
    assert dashboard["services"][0]["last_run"]["status"] == "success"
    assert dashboard["services"][0]["next_run_utc"].isoformat() == "2026-04-02T09:00:00+00:00"

    assert fake.closed >= 4
