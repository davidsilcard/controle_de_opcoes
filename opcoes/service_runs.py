from __future__ import annotations

import datetime as dt
import os
import re
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from .config import reset_pg_schema_override, set_pg_schema_override
from .db import open_db

DEFAULT_SERVICE_KEY = "scrape_cycle"
_LOCAL_TZ = ZoneInfo("America/Sao_Paulo")
_UTC = dt.timezone.utc
_SERVICE_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{1,63}$")


@dataclass(frozen=True)
class ServiceDefinition:
    key: str
    label: str
    description: str
    schedule_label: str
    weekdays: tuple[int, ...]
    run_hour_local: int
    run_minute_local: int
    timezone: ZoneInfo
    stale_after_seconds: int


def _sanitize_schema(value: str) -> str:
    text = (value or "").strip().lower()
    text = re.sub(r"[^a-z0-9_]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    if not text:
        return "public"
    if text[0].isdigit():
        text = f"u_{text}"
    return text[:63]


def _automation_schema() -> str:
    raw = (
        os.getenv("OPCOES_AUTOMATION_SCHEMA", "").strip()
        or os.getenv("OPCOES_PG_SCHEMA", "").strip()
        or "public"
    )
    return _sanitize_schema(raw)


def _connect():
    token = set_pg_schema_override(_automation_schema())
    try:
        conn = open_db()
    finally:
        reset_pg_schema_override(token)
    _ensure_tables(conn)
    return conn


def _ensure_tables(conn: Any) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS service_runs (
            id TEXT PRIMARY KEY,
            service_key TEXT NOT NULL,
            trigger_type TEXT NOT NULL DEFAULT 'systemd',
            status TEXT NOT NULL,
            started_at TIMESTAMPTZ NOT NULL,
            finished_at TIMESTAMPTZ NULL,
            scheduled_for TIMESTAMPTZ NULL,
            duration_seconds INTEGER NULL,
            step TEXT NULL,
            summary TEXT NULL,
            error_message TEXT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_service_runs_service_started
        ON service_runs (service_key, started_at DESC)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_service_runs_status_started
        ON service_runs (status, started_at DESC)
        """
    )
    conn.commit()


def _normalize_service_key(value: str) -> str:
    key = (value or "").strip().lower()
    if not _SERVICE_KEY_RE.fullmatch(key):
        raise ValueError(
            "Servico invalido. Use letras minusculas, numeros, ponto, hifen ou underscore."
        )
    return key


def _normalize_status(value: str) -> str:
    status = (value or "").strip().lower()
    if status not in {"running", "success", "failed"}:
        raise ValueError("Status invalido. Use running, success ou failed.")
    return status


def _coerce_datetime(value: Optional[dt.datetime]) -> Optional[dt.datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=_UTC)
    return value.astimezone(_UTC)


def _format_duration_label(seconds: Optional[int]) -> str:
    if seconds is None:
        return "-"
    total = max(int(seconds), 0)
    if total < 60:
        return f"{total}s"
    minutes, rem_seconds = divmod(total, 60)
    if minutes < 60:
        return f"{minutes}m {rem_seconds:02d}s"
    hours, rem_minutes = divmod(minutes, 60)
    return f"{hours}h {rem_minutes:02d}m"


def start_service_run(
    *,
    service_key: str,
    trigger_type: str = "systemd",
    scheduled_for: Optional[dt.datetime] = None,
    step: Optional[str] = None,
    summary: Optional[str] = None,
) -> str:
    run_id = uuid.uuid4().hex
    now = dt.datetime.now(_UTC)
    safe_service_key = _normalize_service_key(service_key)
    conn = _connect()
    try:
        conn.execute(
            """
            INSERT INTO service_runs (
                id, service_key, trigger_type, status, started_at,
                scheduled_for, step, summary, updated_at
            )
            VALUES (%s, %s, %s, 'running', %s, %s, %s, %s, %s)
            """,
            (
                run_id,
                safe_service_key,
                (trigger_type or "systemd").strip() or "systemd",
                now,
                _coerce_datetime(scheduled_for),
                (step or "").strip() or None,
                (summary or "").strip() or None,
                now,
            ),
        )
        conn.commit()
        return run_id
    finally:
        conn.close()


def finish_service_run(
    run_id: str,
    *,
    status: str,
    step: Optional[str] = None,
    summary: Optional[str] = None,
    error_message: Optional[str] = None,
) -> bool:
    safe_status = _normalize_status(status)
    now = dt.datetime.now(_UTC)
    conn = _connect()
    try:
        result = conn.execute(
            """
            UPDATE service_runs
            SET status = %s,
                finished_at = %s,
                duration_seconds = GREATEST(0, EXTRACT(EPOCH FROM (%s - started_at))::INT),
                step = %s,
                summary = %s,
                error_message = %s,
                updated_at = %s
            WHERE id = %s
            """,
            (
                safe_status,
                now,
                now,
                (step or "").strip() or None,
                (summary or "").strip() or None,
                (error_message or "").strip() or None,
                now,
                (run_id or "").strip(),
            ),
        )
        conn.commit()
        return bool(getattr(result, "rowcount", 0))
    finally:
        conn.close()


def fail_latest_running_service_run(
    *,
    service_key: str,
    step: Optional[str] = None,
    summary: Optional[str] = None,
    error_message: Optional[str] = None,
) -> Optional[str]:
    rows = list_service_runs(limit=1, service_key=service_key)
    if not rows:
        return None
    latest = rows[0]
    if str(latest.get("status") or "").strip().lower() != "running":
        return None
    run_id = str(latest.get("id") or "").strip()
    if not run_id:
        return None
    updated = finish_service_run(
        run_id,
        status="failed",
        step=step,
        summary=summary,
        error_message=error_message,
    )
    return run_id if updated else None


def list_service_runs(*, limit: int = 20, service_key: Optional[str] = None) -> List[Dict[str, Any]]:
    safe_limit = max(1, min(int(limit), 200))
    conn = _connect()
    try:
        if service_key:
            rows = conn.execute(
                """
                SELECT *
                FROM service_runs
                WHERE service_key = %s
                ORDER BY started_at DESC, id DESC
                LIMIT %s
                """,
                (_normalize_service_key(service_key), safe_limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT *
                FROM service_runs
                ORDER BY started_at DESC, id DESC
                LIMIT %s
                """,
                (safe_limit,),
            ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def _service_definitions() -> List[ServiceDefinition]:
    return [
        ServiceDefinition(
            key=DEFAULT_SERVICE_KEY,
            label="Ciclo diario do scraper",
            description=(
                "Executa scrape, exporta o CSV mais recente, atualiza Fundamentus "
                "e aplica a limpeza automatica dos dados de mercado."
            ),
            schedule_label="Dias uteis as 02:00 (America/Sao_Paulo)",
            weekdays=(0, 1, 2, 3, 4),
            run_hour_local=2,
            run_minute_local=0,
            timezone=_LOCAL_TZ,
            stale_after_seconds=4 * 60 * 60,
        )
    ]


def _compute_next_run(definition: ServiceDefinition, *, now_utc: Optional[dt.datetime] = None) -> dt.datetime:
    current = _coerce_datetime(now_utc) or dt.datetime.now(_UTC)
    current_local = current.astimezone(definition.timezone)
    base_local = current_local.replace(
        hour=definition.run_hour_local,
        minute=definition.run_minute_local,
        second=0,
        microsecond=0,
    )
    for day_offset in range(0, 8):
        candidate_local = base_local + dt.timedelta(days=day_offset)
        if candidate_local.weekday() not in definition.weekdays:
            continue
        if candidate_local <= current_local:
            continue
        return candidate_local.astimezone(_UTC)
    return (base_local + dt.timedelta(days=1)).astimezone(_UTC)


def _infer_scheduled_run(
    definition: ServiceDefinition,
    *,
    reference_utc: Optional[dt.datetime],
) -> Optional[dt.datetime]:
    reference = _coerce_datetime(reference_utc)
    if reference is None:
        return None
    reference_local = reference.astimezone(definition.timezone)
    base_local = reference_local.replace(
        hour=definition.run_hour_local,
        minute=definition.run_minute_local,
        second=0,
        microsecond=0,
    )
    for day_offset in range(0, 8):
        candidate_local = base_local - dt.timedelta(days=day_offset)
        if candidate_local.weekday() not in definition.weekdays:
            continue
        if candidate_local > reference_local:
            continue
        return candidate_local.astimezone(_UTC)
    return None


def _decorate_run_for_monitoring(
    row: Dict[str, Any],
    *,
    definition: Optional[ServiceDefinition],
    now_utc: Optional[dt.datetime] = None,
) -> Dict[str, Any]:
    decorated = dict(row)
    normalized_status = str(decorated.get("status") or "").strip().lower()
    decorated["monitor_status"] = normalized_status
    decorated["monitor_message"] = None

    stored_duration = decorated.get("duration_seconds")
    display_duration = stored_duration

    if normalized_status == "running":
        started_at = _coerce_datetime(decorated.get("started_at"))
        current = _coerce_datetime(now_utc) or dt.datetime.now(_UTC)
        runtime_seconds = None
        if started_at is not None:
            runtime_seconds = max(int((current - started_at).total_seconds()), 0)
            if display_duration is None:
                display_duration = runtime_seconds
        decorated["runtime_seconds"] = runtime_seconds

        if (
            definition is not None
            and runtime_seconds is not None
            and runtime_seconds > int(definition.stale_after_seconds)
        ):
            decorated["monitor_status"] = "stalled"
            decorated["monitor_message"] = (
                "Execucao sem finalizacao ha "
                f"{_format_duration_label(runtime_seconds)}, acima do limite esperado de "
                f"{_format_duration_label(definition.stale_after_seconds)}. "
                "Verifique logs e status do systemd."
            )

    decorated["display_duration_seconds"] = display_duration
    scheduled_for = _coerce_datetime(decorated.get("scheduled_for"))
    if scheduled_for is None and definition is not None:
        scheduled_for = _infer_scheduled_run(
            definition,
            reference_utc=_coerce_datetime(decorated.get("started_at")),
        )
    decorated["scheduled_for_display_utc"] = scheduled_for
    return decorated


def get_service_dashboard(*, limit: int = 20, now_utc: Optional[dt.datetime] = None) -> Dict[str, Any]:
    definitions = {definition.key: definition for definition in _service_definitions()}
    recent_runs = [
        _decorate_run_for_monitoring(
            row,
            definition=definitions.get(str(row.get("service_key") or "")),
            now_utc=now_utc,
        )
        for row in list_service_runs(limit=limit)
    ]
    by_service: Dict[str, List[Dict[str, Any]]] = {}
    for row in recent_runs:
        by_service.setdefault(str(row.get("service_key") or ""), []).append(row)

    services: List[Dict[str, Any]] = []
    for definition in definitions.values():
        next_run_utc = _compute_next_run(definition, now_utc=now_utc)
        services.append(
            {
                "key": definition.key,
                "label": definition.label,
                "description": definition.description,
                "schedule_label": definition.schedule_label,
                "stale_after_seconds": definition.stale_after_seconds,
                "next_run_utc": next_run_utc,
                "next_run_local": next_run_utc.astimezone(_LOCAL_TZ),
                "last_run": (by_service.get(definition.key) or [None])[0],
            }
        )

    return {
        "services": services,
        "recent_runs": recent_runs,
    }


__all__ = [
    "DEFAULT_SERVICE_KEY",
    "fail_latest_running_service_run",
    "finish_service_run",
    "get_service_dashboard",
    "list_service_runs",
    "start_service_run",
]
