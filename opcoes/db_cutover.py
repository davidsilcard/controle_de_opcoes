from __future__ import annotations

from typing import Optional
from pathlib import Path

from . import darf, finance, portfolio, report, settings
from .config import reset_pg_schema_override, set_pg_schema_override
from .db_health import is_postgres_ready, run_db_check
from .db_migration import (
    resolve_user_source_databases,
    sanitize_schema_name,
    verify_sqlite_sources_in_postgres,
)


def _run_single_smoke_step(name: str, fn) -> dict:
    try:
        detail = str(fn() or "OK")
        return {"name": name, "ok": True, "detail": detail}
    except Exception as exc:
        return {"name": name, "ok": False, "detail": str(exc)}


def run_postgres_runtime_smoke(*, schema: str) -> list[dict]:
    schema_name = sanitize_schema_name(schema)
    token = set_pg_schema_override(schema_name)
    try:
        steps: list[dict] = []

        def _portfolio_smoke() -> str:
            conn = portfolio._connect_postgres(ensure_schema=True)  # type: ignore[attr-defined]
            try:
                row = conn.execute(
                    'SELECT 1 AS ok, 1 AS "%_Alta_p_2x"'
                ).fetchone()
                if not row or int(row.get("ok", 0)) != 1:
                    raise RuntimeError("SELECT de smoke retornou valor inválido.")
                return "connect + query OK"
            finally:
                conn.close()

        def _finance_smoke() -> str:
            conn = finance._connect_postgres(ensure_schema=True)  # type: ignore[attr-defined]
            try:
                row = conn.execute("SELECT COUNT(*) AS total FROM ledger").fetchone()
                total = int(row.get("total", 0)) if row else 0
                return f"ledger acessível (rows={total})"
            finally:
                conn.close()

        def _darf_smoke() -> str:
            conn = darf._connect_postgres(ensure_schema=True)  # type: ignore[attr-defined]
            try:
                row = conn.execute("SELECT COUNT(*) AS total FROM darf_months").fetchone()
                total = int(row.get("total", 0)) if row else 0
                return f"darf_months acessível (rows={total})"
            finally:
                conn.close()

        def _settings_smoke() -> str:
            conn = settings._connect_postgres(ensure_table=True)  # type: ignore[attr-defined]
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT COUNT(*) FROM settings")
                    row = cur.fetchone()
                total = int(row[0] or 0) if row else 0
                return f"settings acessível (rows={total})"
            finally:
                conn.close()

        def _report_smoke() -> str:
            conn = report._connect_postgres()  # type: ignore[attr-defined]
            try:
                row = conn.execute("SELECT 1 AS ok").fetchone()
                if not row or int(row.get("ok", 0)) != 1:
                    raise RuntimeError("SELECT de smoke retornou valor inválido.")
                return "connect + query OK"
            finally:
                conn.close()

        steps.append(_run_single_smoke_step("portfolio", _portfolio_smoke))
        steps.append(_run_single_smoke_step("finance", _finance_smoke))
        steps.append(_run_single_smoke_step("darf", _darf_smoke))
        steps.append(_run_single_smoke_step("settings", _settings_smoke))
        steps.append(_run_single_smoke_step("report", _report_smoke))
        return steps
    finally:
        reset_pg_schema_override(token)


def run_cutover_ready_check(
    *,
    username: str,
    schema: Optional[str],
    timeout_seconds: float,
    source_dir: Optional[Path],
    source_main: Optional[Path],
    source_iv: Optional[Path],
    source_flow: Optional[Path],
    include_aux: bool,
) -> dict:
    schema_name = sanitize_schema_name(schema or username)
    db_check = run_db_check(timeout_seconds=float(timeout_seconds))
    result = {
        "ok": False,
        "schema": schema_name,
        "db_check": db_check,
        "verify": None,
        "smoke": [],
        "sources": [],
        "errors": [],
    }

    if not is_postgres_ready(db_check):
        result["errors"].extend(db_check.get("errors", []))
        return result

    sources = resolve_user_source_databases(
        username=username,
        source_dir=source_dir,
        source_main=source_main,
        source_iv=source_iv,
        source_flow=source_flow,
        include_aux=include_aux,
    )
    result["sources"] = sources

    verify_report = verify_sqlite_sources_in_postgres(schema=schema_name, sources=sources)
    result["verify"] = verify_report
    if not verify_report.get("ok"):
        result["errors"].append(
            "Verificação SQLite x PostgreSQL encontrou divergências de contagem."
        )
        return result

    smoke = run_postgres_runtime_smoke(schema=schema_name)
    result["smoke"] = smoke
    failed = [step for step in smoke if not step.get("ok")]
    if failed:
        for item in failed:
            result["errors"].append(
                f"Falha no smoke de runtime ({item.get('name')}): {item.get('detail')}"
            )
        return result

    result["ok"] = True
    return result


__all__ = [
    "run_cutover_ready_check",
    "run_postgres_runtime_smoke",
]

