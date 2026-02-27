from __future__ import annotations

import os
import socket
from dataclasses import dataclass
from typing import Optional, Tuple
from urllib.parse import quote, urlencode, urlparse, urlunparse

from .config import get_db_path

_POSTGRES_SCHEMES = {"postgres", "postgresql"}
_POSTGRES_ENV_KEYS = (
    "DATABASE_URL",
    "POSTGRES_DB",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "DB_HOST",
    "DB_PORT",
    "POSTGRES_HOST",
    "POSTGRES_PORT",
    "PGDATABASE",
    "PGUSER",
    "PGPASSWORD",
    "PGHOST",
    "PGPORT",
)


@dataclass(frozen=True)
class PostgresTarget:
    dsn: str
    redacted_dsn: str
    source: str
    host: str
    port: int


def _env_first(*names: str) -> str:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return ""


def _redact_dsn(dsn: str) -> str:
    parsed = urlparse(dsn)
    username = parsed.username or ""
    host = parsed.hostname or ""
    try:
        port = parsed.port
    except ValueError:
        port = None
    if port:
        host = f"{host}:{port}"
    password = "***" if parsed.password else ""
    auth = username
    if password:
        auth = f"{username}:{password}" if username else password
    netloc = f"{auth}@{host}" if auth else host
    return urlunparse(
        (
            parsed.scheme,
            netloc,
            parsed.path,
            parsed.params,
            parsed.query,
            parsed.fragment,
        )
    )


def _validate_database_url(raw: str) -> tuple[Optional[PostgresTarget], list[str]]:
    errors: list[str] = []
    parsed = urlparse(raw)
    scheme = (parsed.scheme or "").strip().lower()
    if scheme not in _POSTGRES_SCHEMES:
        errors.append(
            "DATABASE_URL inválida: use esquema postgres:// ou postgresql://."
        )
        return None, errors

    host = (parsed.hostname or "").strip()
    if not host:
        errors.append("DATABASE_URL inválida: host ausente.")
        return None, errors

    try:
        port = int(parsed.port or 5432)
    except ValueError:
        errors.append("DATABASE_URL inválida: porta não numérica.")
        return None, errors
    target = PostgresTarget(
        dsn=raw,
        redacted_dsn=_redact_dsn(raw),
        source="DATABASE_URL",
        host=host,
        port=port,
    )
    return target, errors


def _build_dsn_from_legacy_env() -> tuple[Optional[PostgresTarget], list[str]]:
    errors: list[str] = []
    host = _env_first("DB_HOST", "POSTGRES_HOST", "PGHOST")
    port_text = _env_first("DB_PORT", "POSTGRES_PORT", "PGPORT") or "5432"
    db_name = _env_first("POSTGRES_DB", "PGDATABASE")
    user = _env_first("POSTGRES_USER", "PGUSER")
    password = _env_first("POSTGRES_PASSWORD", "PGPASSWORD")
    sslmode = _env_first("POSTGRES_SSLMODE", "PGSSLMODE")

    if not host:
        errors.append("Variável ausente: DB_HOST ou POSTGRES_HOST.")
    if not db_name:
        errors.append("Variável ausente: POSTGRES_DB.")
    if not user:
        errors.append("Variável ausente: POSTGRES_USER.")
    if not password:
        errors.append("Variável ausente: POSTGRES_PASSWORD.")

    try:
        port = int(port_text)
    except ValueError:
        errors.append("DB_PORT/POSTGRES_PORT inválida: use um número inteiro.")
        port = 5432

    if errors:
        return None, errors

    auth = f"{quote(user, safe='')}:{quote(password, safe='')}"
    dsn = f"postgresql://{auth}@{host}:{port}/{quote(db_name, safe='')}"
    if sslmode:
        dsn = f"{dsn}?{urlencode({'sslmode': sslmode})}"

    target = PostgresTarget(
        dsn=dsn,
        redacted_dsn=_redact_dsn(dsn),
        source="POSTGRES_* / DB_*",
        host=host,
        port=port,
    )
    return target, []


def resolve_postgres_target() -> tuple[Optional[PostgresTarget], list[str]]:
    database_url = os.getenv("DATABASE_URL", "").strip()
    if database_url:
        return _validate_database_url(database_url)
    return _build_dsn_from_legacy_env()


def has_postgres_env() -> bool:
    return any(os.getenv(name, "").strip() for name in _POSTGRES_ENV_KEYS)


def _tcp_probe(host: str, port: int, timeout_seconds: float) -> Tuple[bool, str]:
    timeout = max(float(timeout_seconds), 0.1)
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True, "OK"
    except OSError as exc:
        return False, str(exc)


def _sql_probe(dsn: str, timeout_seconds: float) -> Tuple[bool, str]:
    try:
        import psycopg
    except Exception:
        return (
            False,
            "Driver não encontrado. Instale com: uv add psycopg[binary]",
        )

    connect_timeout = max(int(timeout_seconds), 1)
    try:
        with psycopg.connect(dsn, connect_timeout=connect_timeout) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        return True, "OK"
    except Exception as exc:
        return False, str(exc)


def run_db_check(timeout_seconds: float = 5.0) -> dict:
    runtime_path = get_db_path()
    report = {
        "runtime_backend": "sqlite",
        "runtime_target": str(runtime_path),
        "postgres_configured": False,
        "postgres_source": None,
        "postgres_target": None,
        "tcp_ok": None,
        "tcp_message": None,
        "sql_ok": None,
        "sql_message": None,
        "errors": [],
    }

    target, resolve_errors = resolve_postgres_target()
    report["errors"].extend(resolve_errors)
    if target is None:
        if not has_postgres_env():
            report["errors"].append(
                "Nenhuma configuração PostgreSQL encontrada (.env sem DATABASE_URL/POSTGRES_*)."
            )
        return report

    report["postgres_configured"] = True
    report["postgres_source"] = target.source
    report["postgres_target"] = target.redacted_dsn

    tcp_ok, tcp_msg = _tcp_probe(target.host, target.port, timeout_seconds)
    report["tcp_ok"] = tcp_ok
    report["tcp_message"] = tcp_msg
    if not tcp_ok:
        report["errors"].append(f"Falha de rede no host/porta do PostgreSQL: {tcp_msg}")

    sql_ok, sql_msg = _sql_probe(target.dsn, timeout_seconds)
    report["sql_ok"] = sql_ok
    report["sql_message"] = sql_msg
    if not sql_ok:
        report["errors"].append(f"Falha de conexão SQL: {sql_msg}")

    return report


def is_postgres_ready(report: dict) -> bool:
    return bool(report.get("postgres_configured") and report.get("sql_ok"))


__all__ = [
    "PostgresTarget",
    "resolve_postgres_target",
    "has_postgres_env",
    "run_db_check",
    "is_postgres_ready",
]
