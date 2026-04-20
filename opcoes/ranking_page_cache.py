from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Mapping, Optional, Tuple

from .db import db_transaction, open_db
from .report import ReportData


def _ensure_tables(conn: Any) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ranking_page_cache (
            cache_key TEXT PRIMARY KEY,
            namespace TEXT NOT NULL,
            route_name TEXT NOT NULL,
            args_signature TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMPTZ NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_ranking_page_cache_namespace
        ON ranking_page_cache (namespace)
        """
    )


def _serialize_context(ctx: Mapping[str, Any]) -> str:
    payload = dict(ctx)
    data = payload.get("data")
    if isinstance(data, ReportData):
        payload["data"] = {
            "__type__": "ReportData",
            "value": asdict(data),
        }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _deserialize_context(payload_json: str) -> Dict[str, Any]:
    payload = json.loads(payload_json)
    data = payload.get("data")
    if isinstance(data, dict) and data.get("__type__") == "ReportData":
        payload["data"] = ReportData(**dict(data.get("value") or {}))
    return payload


def build_cache_key(*, route_name: str, namespace: str, args_signature: Tuple[Any, ...]) -> str:
    return json.dumps(
        {
            "route": route_name,
            "namespace": namespace,
            "args": args_signature,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def get_cached_context(*, cache_key: str, ttl_seconds: int) -> Optional[Dict[str, Any]]:
    if ttl_seconds <= 0:
        return None
    conn = open_db()
    try:
        _ensure_tables(conn)
        row = conn.execute(
            """
            SELECT payload_json
            FROM ranking_page_cache
            WHERE cache_key = ?
              AND expires_at > CURRENT_TIMESTAMP
            LIMIT 1
            """,
            (cache_key,),
        ).fetchone()
        if not row:
            return None
        payload_json = row.get("payload_json") if isinstance(row, Mapping) else None
        if not payload_json:
            return None
        return _deserialize_context(str(payload_json))
    finally:
        conn.close()


def set_cached_context(
    *,
    cache_key: str,
    namespace: str,
    route_name: str,
    args_signature: Tuple[Any, ...],
    ctx: Mapping[str, Any],
    ttl_seconds: int,
) -> None:
    if ttl_seconds <= 0:
        return
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
    with db_transaction() as conn:
        _ensure_tables(conn)
        conn.execute(
            """
            INSERT INTO ranking_page_cache (
                cache_key,
                namespace,
                route_name,
                args_signature,
                payload_json,
                expires_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (cache_key) DO UPDATE SET
                namespace = EXCLUDED.namespace,
                route_name = EXCLUDED.route_name,
                args_signature = EXCLUDED.args_signature,
                payload_json = EXCLUDED.payload_json,
                created_at = CURRENT_TIMESTAMP,
                expires_at = EXCLUDED.expires_at
            """,
            (
                cache_key,
                namespace,
                route_name,
                json.dumps(args_signature, ensure_ascii=False, separators=(",", ":")),
                _serialize_context(ctx),
                expires_at,
            ),
        )
        conn.execute(
            "DELETE FROM ranking_page_cache WHERE expires_at <= CURRENT_TIMESTAMP"
        )


def invalidate_namespace(namespace: str) -> None:
    if not namespace:
        return
    with db_transaction() as conn:
        _ensure_tables(conn)
        conn.execute(
            "DELETE FROM ranking_page_cache WHERE namespace = ?",
            (namespace,),
        )


def refresh_cached_context(
    *,
    route_name: str,
    namespace: str,
    args_signature: Tuple[Any, ...],
    ttl_seconds: int,
    ctx: Mapping[str, Any],
) -> str:
    cache_key = build_cache_key(
        route_name=route_name,
        namespace=namespace,
        args_signature=args_signature,
    )
    set_cached_context(
        cache_key=cache_key,
        namespace=namespace,
        route_name=route_name,
        args_signature=args_signature,
        ctx=ctx,
        ttl_seconds=ttl_seconds,
    )
    return cache_key


__all__ = [
    "build_cache_key",
    "get_cached_context",
    "invalidate_namespace",
    "refresh_cached_context",
    "set_cached_context",
]
