from __future__ import annotations

import logging
import os
import time
from contextlib import contextmanager
from typing import Iterator

from flask import g, has_request_context, request

logger = logging.getLogger(__name__)


def _perf_enabled() -> bool:
    raw = (os.getenv("OPCOES_PERF_TIMING_ENABLED", "1") or "1").strip().lower()
    return raw not in {"0", "false", "no", "off", "nao", "não"}


def start_request_timing() -> None:
    if not has_request_context() or not _perf_enabled():
        return
    g._perf_started_at = time.perf_counter()
    g._perf_stages = []


def add_stage_timing(name: str, duration_ms: float) -> None:
    if not has_request_context() or not _perf_enabled():
        return
    stages = getattr(g, "_perf_stages", None)
    if not isinstance(stages, list):
        stages = []
        g._perf_stages = stages
    stages.append((str(name).strip() or "stage", max(float(duration_ms), 0.0)))


@contextmanager
def timed_stage(name: str) -> Iterator[None]:
    started_at = time.perf_counter()
    try:
        yield
    finally:
        duration_ms = (time.perf_counter() - started_at) * 1000.0
        add_stage_timing(name, duration_ms)


def build_server_timing_header() -> str | None:
    if not has_request_context() or not _perf_enabled():
        return None
    stages = getattr(g, "_perf_stages", None)
    if not isinstance(stages, list) or not stages:
        return None
    parts: list[str] = []
    for name, duration_ms in stages:
        metric_name = str(name).replace(" ", "_").replace("/", "_")
        metric_name = "".join(ch for ch in metric_name if ch.isalnum() or ch in {"_", "-", "."})
        if not metric_name:
            continue
        parts.append(f'{metric_name};dur={duration_ms:.2f}')
    return ", ".join(parts) if parts else None


def finalize_request_timing() -> None:
    if not has_request_context() or not _perf_enabled():
        return
    started_at = getattr(g, "_perf_started_at", None)
    if started_at is None:
        return
    total_ms = (time.perf_counter() - started_at) * 1000.0
    add_stage_timing("request.total", total_ms)
    logger.info(
        "web_request_timing",
        extra={
            "method": request.method,
            "path": request.path,
            "endpoint": request.endpoint or "",
            "status_code": getattr(g, "_perf_status_code", None),
            "total_ms": round(total_ms, 2),
            "stages": [
                {"name": name, "duration_ms": round(duration_ms, 2)}
                for name, duration_ms in getattr(g, "_perf_stages", [])
            ],
        },
    )

