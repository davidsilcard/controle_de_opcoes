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
    run_hour_utc: int
    run_minute_utc: int


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
            schedule_label="Dias uteis as 06:00 (America/Sao_Paulo)",
            weekdays=(0, 1, 2, 3, 4),
            run_hour_utc=9,
            run_minute_utc=0,
        )
    ]


def _compute_next_run(definition: ServiceDefinition, *, now_utc: Optional[dt.datetime] = None) -> dt.datetime:
    current = _coerce_datetime(now_utc) or dt.datetime.now(_UTC)
    base = current.replace(
        hour=definition.run_hour_utc,
        minute=definition.run_minute_utc,
        second=0,
        microsecond=0,
    )
    for day_offset in range(0, 8):
        candidate = base + dt.timedelta(days=day_offset)
        if candidate.weekday() not in definition.weekdays:
            continue
        if candidate <= current:
            continue
        return candidate
    return base + dt.timedelta(days=1)


def get_service_dashboard(*, limit: int = 20, now_utc: Optional[dt.datetime] = None) -> Dict[str, Any]:
    recent_runs = list_service_runs(limit=limit)
    by_service: Dict[str, List[Dict[str, Any]]] = {}
    for row in recent_runs:
        by_service.setdefault(str(row.get("service_key") or ""), []).append(row)

    services: List[Dict[str, Any]] = []
    for definition in _service_definitions():
        next_run_utc = _compute_next_run(definition, now_utc=now_utc)
        services.append(
            {
                "key": definition.key,
                "label": definition.label,
                "description": definition.description,
                "schedule_label": definition.schedule_label,
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
    "finish_service_run",
    "get_service_dashboard",
    "list_service_runs",
    "start_service_run",
]
