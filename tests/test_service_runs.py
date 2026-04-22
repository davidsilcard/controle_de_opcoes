from __future__ import annotations

import datetime as dt

from opcoes.service_runs import (
    fail_latest_running_service_run,
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
                "updated_at": params[7],
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
                    row["updated_at"] = params[6]
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
        scheduled_for=dt.datetime(2026, 4, 1, 6, 0, tzinfo=dt.timezone.utc),
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
    assert dashboard["services"][0]["last_run"]["monitor_status"] == "success"
    assert dashboard["services"][0]["next_run_utc"].isoformat() == "2026-04-02T06:00:00+00:00"

    assert fake.closed >= 4


def test_service_dashboard_flags_possible_stall_and_watchdog_can_fail_run(monkeypatch) -> None:
    fake = _FakeConn()
    monkeypatch.setattr("opcoes.service_runs._connect", lambda: fake)

    run_id = start_service_run(
        service_key="scrape_cycle",
        trigger_type="systemd",
        summary="Ciclo iniciado",
        scheduled_for=dt.datetime(2026, 4, 1, 6, 0, tzinfo=dt.timezone.utc),
    )
    fake.rows[0]["started_at"] = dt.datetime(2026, 4, 1, 6, 0, tzinfo=dt.timezone.utc)

    dashboard = get_service_dashboard(
        limit=5,
        now_utc=dt.datetime(2026, 4, 1, 11, 15, tzinfo=dt.timezone.utc),
    )
    last_run = dashboard["services"][0]["last_run"]
    assert last_run["monitor_status"] == "stalled"
    assert "acima do limite esperado" in (last_run["monitor_message"] or "")
    assert last_run["display_duration_seconds"] == 18900

    reconciled = fail_latest_running_service_run(
        service_key="scrape_cycle",
        step="watchdog",
        summary="Watchdog marcou a execucao como interrompida.",
        error_message="Servico nao estava mais ativo.",
    )
    assert reconciled == run_id
    assert fake.rows[0]["status"] == "failed"
    assert fake.rows[0]["step"] == "watchdog"
    assert fake.rows[0]["error_message"] == "Servico nao estava mais ativo."


def test_service_dashboard_infers_scheduled_slot_in_local_timezone(monkeypatch) -> None:
    fake = _FakeConn()
    monkeypatch.setattr("opcoes.service_runs._connect", lambda: fake)

    run_id = start_service_run(
        service_key="scrape_cycle",
        trigger_type="systemd",
        summary="Ciclo iniciado",
    )

    assert run_id
    fake.rows[0]["scheduled_for"] = None
    fake.rows[0]["started_at"] = dt.datetime(2026, 4, 22, 9, 0, tzinfo=dt.timezone.utc)

    dashboard = get_service_dashboard(
        limit=5,
        now_utc=dt.datetime(2026, 4, 22, 12, 0, tzinfo=dt.timezone.utc),
    )
    last_run = dashboard["services"][0]["last_run"]

    assert last_run["scheduled_for_display_utc"].isoformat() == "2026-04-22T06:00:00+00:00"
