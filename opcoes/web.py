from __future__ import annotations

import datetime
import math
import os
import re
import threading
import time
from pathlib import Path
from secrets import compare_digest, token_urlsafe
from typing import Any, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from flask import (
    Flask,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from markupsafe import Markup
from werkzeug.middleware.proxy_fix import ProxyFix

from .auth import (
    authenticate_login,
    change_password,
    clear_login_rate_limit,
    ensure_bootstrap_user_from_env,
    get_login_block_remaining_seconds,
    get_user_app_schema,
    normalize_username,
    record_failed_login_attempt,
)
from .config import (
    reset_pg_schema_override,
    set_pg_schema_override,
)
from .db import db_transaction, open_db
from .runtime_env import load_dotenv_once
from .portfolio import (
    add_position,
    delete_position,
    list_positions,
    summarize_realized_positions,
    update_position,
    close_position,
    get_position,
)
from .snapshot_repository import fetch_latest_option_snapshot
from .utils import infer_option_type, parse_ptbr_number
from .settings import (
    CashCoveredPutSettings,
    CoveredCallSettings,
    FeeSettings,
    StrategySettings,
    FundamentusSettings,
    get_cash_put_settings,
    get_covered_call_settings,
    get_fee_settings,
    get_strategy_settings,
    get_fundamentus_settings,
    update_cash_put_settings,
    update_covered_call_settings,
    update_fee_settings,
    update_strategy_settings,
    update_fundamentus_settings,
)
from .service_runs import get_service_dashboard
from .strategies import (
    get_cash_covered_put_context,
    get_covered_call_context,
    get_covered_call_shell_context,
    get_fundamentus_context,
    get_fundamentus_shell_context,
    get_ranking_context,
    get_ranking_shell_context,
)
from .flows import FlowError, assign_put, callaway
from .cash_put_guard import CashPutValidationError, validate_cash_put_input
from .covered_call_guard import (
    CoveredCallValidationError,
    find_duplicate_covered_call,
    validate_covered_call_input,
)
from .ranking_guard import RankingValidationError, validate_ranking_option_input
from .positions_guard import audit_positions_page
from .strategy_contracts import (
    StrategyContractError,
    validate_position_closure_update,
    validate_position_identity_update,
)
from .strategy_performance import STRATEGIES, build_strategy_performance
from .wheel_cycles import (
    LEG_TYPES as WHEEL_LEG_TYPES,
    WheelCycleError,
    add_wheel_cycle_leg,
    create_wheel_cycle,
    list_wheel_cycles,
)
from .audit_reconciliation import build_audit_reconciliation
from .holdings import (
    HoldingValidationError,
    get_holding_snapshot,
    list_holding_events,
    list_holding_snapshots,
    list_holdings,
    upsert_holding,
    validate_covered_call_availability,
)
from .market_data import (
    MarketDataClient,
    format_market_timestamp_label,
    market_source_label,
    market_status_label,
)
from .ranking_page_cache import (
    build_cache_key as build_persisted_page_cache_key,
    get_cached_context as get_persisted_page_cache,
    invalidate_namespace as invalidate_persisted_page_cache_namespace,
    set_cached_context as set_persisted_page_cache,
)
from .perf import (
    build_server_timing_header,
    finalize_request_timing,
    start_request_timing,
    timed_stage,
)
from . import finance, darf
from .tax import (
    compute_tax,
    list_monthly_tax_summaries,
    list_tax_events_for_period,
)

DEFAULT_SECRET_KEY = "troque-esta-chave-em-producao"
CSRF_FIELD_NAME = "_csrf_token"
LOCAL_DISPLAY_TZ = ZoneInfo("America/Sao_Paulo")


def _looks_like_equity_ticker_global(ticker: str | None) -> bool:
    text = (ticker or "").strip().upper()
    if not text:
        return False
    return re.fullmatch(r"[A-Z]{4}\d{1,2}", text) is not None


def _inventory_key_for_position_global(pos: dict[str, Any]) -> str:
    ticker = (pos.get("ticker") or "").strip().upper()
    underlying = (pos.get("underlying") or "").strip().upper()
    strategy_tag = (pos.get("strategy_tag") or "").strip().lower()
    trade_type = (pos.get("trade_type") or "").strip().lower()
    side = (pos.get("side") or "").strip().lower()
    if not ticker:
        return ""
    if side == "short":
        if infer_option_type(ticker) == "CALL" and strategy_tag == "covered_call":
            return underlying or ""
        return ""
    if strategy_tag == "ranking":
        return ""
    if strategy_tag == "estoque" or trade_type == "stock":
        return underlying or ticker
    if underlying and ticker == underlying:
        return underlying
    if _looks_like_equity_ticker_global(ticker) and not _is_option_ticker_global(
        ticker
    ):
        return underlying or ticker
    return ""


def _is_option_ticker_global(ticker: str | None) -> bool:
    return infer_option_type(ticker or "") in {"CALL", "PUT"}


def _is_inventory_stock_position_global(pos: dict[str, Any]) -> bool:
    ticker = (pos.get("ticker") or "").strip().upper()
    if not ticker or _is_option_ticker_global(ticker):
        return False
    side = (pos.get("side") or "").strip().lower()
    if side == "short":
        return False
    strategy_tag = (pos.get("strategy_tag") or "").strip().lower()
    trade_type = (pos.get("trade_type") or "").strip().lower()
    if strategy_tag == "ranking":
        return False
    underlying = (pos.get("underlying") or "").strip().upper()
    if strategy_tag == "estoque" or trade_type == "stock":
        return True
    if underlying and ticker == underlying:
        return True
    if _looks_like_equity_ticker_global(ticker) and not underlying:
        return True
    return False


def _hide_replaced_legacy_stock_positions_global(
    positions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    explicit_holdings = {
        (
            (item.get("ticker") or "").strip().upper(),
            bool(item.get("is_simulated") or 0),
        )
        for item in list_holdings()
    }
    if not explicit_holdings:
        return positions

    visible: list[dict[str, Any]] = []
    for pos in positions:
        key = _inventory_key_for_position_global(pos)
        mode = bool(pos.get("is_simulated") or 0)
        if (
            key
            and _is_inventory_stock_position_global(pos)
            and (pos.get("status") or "").strip().lower() == "open"
            and (key.strip().upper(), mode) in explicit_holdings
        ):
            continue
        visible.append(pos)
    return visible


def _build_inventory_overview_global(
    positions: list[dict[str, Any]],
    *,
    underlying_filter: str | None = None,
) -> list[dict[str, Any]]:
    return list_holding_snapshots(
        underlying_filter=underlying_filter,
        positions_open=positions,
    )


def _normalize_live_market_symbols(
    symbols: list[str] | tuple[str, ...] | set[str],
) -> list[str]:
    normalized = {
        str(symbol or "").strip().upper()
        for symbol in symbols
        if str(symbol or "").strip()
    }
    return sorted(normalized)


def _collect_position_live_market_symbols(
    positions: list[dict[str, Any]],
) -> list[str]:
    collected: list[str] = []
    for pos in positions:
        if (pos.get("status") or "").strip().lower() != "open":
            continue
        ticker = str(pos.get("ticker") or "").strip().upper()
        underlying = str(pos.get("underlying") or "").strip().upper()
        if ticker:
            collected.append(ticker)
        if underlying:
            collected.append(underlying)
    return _normalize_live_market_symbols(collected)


def _collect_covered_call_live_market_symbols(ctx: Mapping[str, Any]) -> list[str]:
    collected: list[str] = []
    underlying = str(ctx.get("underlying") or "").strip().upper()
    if underlying:
        collected.append(underlying)
    for key in ("covered_real", "covered_sim", "suggestions"):
        for row in ctx.get(key) or []:
            ticker = str((row or {}).get("ticker") or "").strip().upper()
            row_underlying = (
                str((row or {}).get("underlying") or underlying).strip().upper()
            )
            if ticker:
                collected.append(ticker)
            if row_underlying:
                collected.append(row_underlying)
    return _normalize_live_market_symbols(collected)


def _live_market_scope_config(
    *,
    scope: str,
    symbols: list[str],
    refresh_url: str,
    fallback_seconds: int = 60,
) -> dict[str, Any]:
    return {
        "scope": scope,
        "symbols": _normalize_live_market_symbols(symbols),
        "refresh_url": refresh_url,
        "fallback_seconds": max(int(fallback_seconds), 15),
    }


def _parse_requested_live_market_symbols(args: Any) -> list[str]:
    raw_items: list[str] = []
    for item in args.getlist("symbols"):
        raw_items.extend(str(item or "").split(","))
    for item in args.getlist("symbol"):
        raw_items.extend(str(item or "").split(","))
    if not raw_items:
        single = str(args.get("symbols") or "").strip()
        if single:
            raw_items.extend(single.split(","))
    return _normalize_live_market_symbols(raw_items)


def _mark_positions_snapshot_market_fields(
    positions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for pos in positions:
        item = dict(pos)
        if item.get("last_price") is not None and not item.get("market_status"):
            item["market_status"] = "snapshot"
        if item.get("market_status") == "snapshot" and not item.get(
            "market_price_source"
        ):
            item["market_price_source"] = "snapshot"
        if item.get("underlying_price") is not None and not item.get(
            "underlying_market_status"
        ):
            item["underlying_market_status"] = "snapshot"
        normalized.append(item)
    return normalized


def _build_positions_page_context(
    *,
    ticker_contains: str,
    underlying_contains: str,
    strategy_tag: str,
    trade_type: str,
    status: str,
    is_simulated_raw: str,
    result_year_raw: str,
    result_month_raw: str,
    market_data_client: MarketDataClient,
) -> dict[str, Any]:
    # Mantido na assinatura para não quebrar chamadas internas antigas. As telas
    # principais usam dados de scrape/snapshot como contrato oficial.
    _ = market_data_client
    include_closed = True
    only_closed = False
    if status == "open":
        include_closed = False
    elif status == "closed":
        only_closed = True

    is_simulated = None
    if is_simulated_raw in {"0", "1"}:
        is_simulated = is_simulated_raw == "1"

    result_year = None
    if result_year_raw:
        try:
            result_year = int(result_year_raw)
        except ValueError:
            result_year = None

    result_month = None
    if result_month_raw:
        try:
            month_candidate = int(result_month_raw)
        except ValueError:
            month_candidate = None
        if month_candidate is not None and 1 <= month_candidate <= 12:
            result_month = month_candidate

    with timed_stage("positions.list_positions"):
        positions = list_positions(
            include_closed=include_closed,
            only_closed=only_closed,
            ticker_contains=ticker_contains or None,
            underlying_contains=underlying_contains or None,
            strategy_tag=strategy_tag or None,
            trade_type=trade_type or None,
            is_simulated=is_simulated,
        )
    positions = _mark_positions_snapshot_market_fields(positions)
    position_ids = [int(p["id"]) for p in positions if p.get("id") is not None]
    with timed_stage("positions.get_premium_ids"):
        premium_ids = finance.get_premium_position_ids(position_ids)
    for pos in positions:
        pos_id = pos.get("id")
        pos["premium_recorded"] = bool(pos_id and int(pos_id) in premium_ids)
        pos["market_status_label"] = market_status_label(pos.get("market_status"))
        pos["market_source_label"] = market_source_label(pos.get("market_price_source"))
        pos["market_time_display"] = format_market_timestamp_label(
            pos.get("market_time_utc") or pos.get("last_snapshot_date")
        )
        pos["underlying_market_status_label"] = market_status_label(
            pos.get("underlying_market_status")
        )
        pos["underlying_market_time_display"] = format_market_timestamp_label(
            pos.get("underlying_market_time_utc")
            or pos.get("underlying_price_date")
            or pos.get("last_snapshot_date")
        )
    positions_view = _hide_replaced_legacy_stock_positions_global(positions)
    with timed_stage("positions.audit"):
        audit_positions = list_positions(include_closed=True)
        audit_open_positions = [
            p
            for p in audit_positions
            if (p.get("status") or "").strip().lower() == "open"
        ]
        audit_holding_snapshots = list_holding_snapshots(
            positions_open=audit_open_positions
        )
        audit_holding_events = list_holding_events(limit=500)
        ledger_sums = finance.get_ledger_sums_by_position(
            types=[
                finance.TransactionType.PREMIUM,
                finance.TransactionType.DARF,
                finance.TransactionType.BUY,
                finance.TransactionType.SELL,
                finance.TransactionType.ASSIGNMENT,
                finance.TransactionType.REALIZED,
            ]
        )
        positions_audit_issues = audit_positions_page(
            audit_positions,
            ledger_sums=ledger_sums,
            holding_snapshots=audit_holding_snapshots,
            holding_events=audit_holding_events,
        )
    realized_summary = summarize_realized_positions(
        ticker_contains=ticker_contains or None,
        underlying_contains=underlying_contains or None,
        strategy_tag=strategy_tag or None,
        trade_type=trade_type or None,
        is_simulated=is_simulated,
        selected_year=result_year,
        selected_month=result_month,
    )
    inventory_summary = _build_inventory_overview_global(positions)
    ctx = {
        "positions": positions_view,
        "filter_ticker": ticker_contains,
        "filter_underlying": underlying_contains,
        "filter_strategy_tag": strategy_tag,
        "filter_trade_type": trade_type,
        "filter_status": status,
        "filter_is_simulated": is_simulated_raw,
        "realized_summary": realized_summary,
        "inventory_summary": inventory_summary,
        "positions_audit_issues": positions_audit_issues,
    }
    return ctx


def _build_covered_call_page_context(
    *,
    args: Any,
    market_data_client: MarketDataClient,
    persist_settings: bool = True,
    include_financial_sections: bool = True,
    include_inventory_summary: bool = True,
) -> dict[str, Any]:
    ctx = get_covered_call_context(
        args,
        market_data_client=market_data_client,
        persist_settings=persist_settings,
        include_financial_sections=include_financial_sections,
    )
    if include_inventory_summary:
        ctx["inventory_summary"] = _build_inventory_overview_global(
            list_positions(include_closed=False),
            underlying_filter=ctx.get("underlying"),
        )
    else:
        ctx["inventory_summary"] = []
    ctx["holding_notice"] = (args.get("holding_notice") or "").strip()
    ctx["holding_error"] = (args.get("holding_error") or "").strip()
    return ctx


def _build_covered_call_shell_page_context(*, args: Any) -> dict[str, Any]:
    ctx = get_covered_call_shell_context(args, persist_settings=True)
    ctx["holding_notice"] = (args.get("holding_notice") or "").strip()
    ctx["holding_error"] = (args.get("holding_error") or "").strip()
    return ctx


def _build_ranking_shell_page_context(*, args: Any) -> dict[str, Any]:
    return get_ranking_shell_context(args)


def _build_fundamentus_shell_page_context(*, args: Any) -> dict[str, Any]:
    return get_fundamentus_shell_context(args)


def create_app() -> Flask:
    app = Flask(__name__, template_folder=str(Path(__file__).parent / "templates"))
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    def _env_bool(name: str, default: bool = False) -> bool:
        raw = os.getenv(name, "1" if default else "0").strip().lower()
        return raw in {"1", "true", "yes", "on", "sim", "s"}

    def _env_int(name: str, default: int, minimum: int) -> int:
        raw = os.getenv(name, str(default)).strip()
        try:
            value = int(raw)
        except ValueError:
            value = default
        return max(value, minimum)

    def _skip_production_checks() -> bool:
        return _env_bool("OPCOES_SKIP_PRODUCTION_CHECKS", False)

    def _is_debug_mode() -> bool:
        return _env_bool("OPCOES_WEB_DEBUG", False)

    secret_key = (os.getenv("OPCOES_SECRET_KEY") or "").strip() or DEFAULT_SECRET_KEY
    if not _is_debug_mode() and not _skip_production_checks():
        if secret_key == DEFAULT_SECRET_KEY:
            raise RuntimeError(
                "Defina OPCOES_SECRET_KEY com um valor forte e unico antes de iniciar a aplicacao em producao."
            )
    app.secret_key = secret_key
    ensure_bootstrap_user_from_env()
    market_data_client = MarketDataClient()
    live_market_asset = Path(app.static_folder or "") / "live_market.js"
    try:
        default_static_asset_version = str(int(live_market_asset.stat().st_mtime))
    except OSError:
        default_static_asset_version = "1"
    static_asset_version = (
        os.getenv("OPCOES_STATIC_ASSET_VERSION") or default_static_asset_version
    ).strip()
    ranking_cache: dict[str, tuple[float, dict]] = {}
    ranking_cache_lock = threading.Lock()
    strategy_page_cache: dict[str, tuple[float, dict]] = {}
    strategy_page_cache_lock = threading.Lock()
    ranking_cache_write_endpoints = {
        "darf_generate",
        "darf_pay",
        "finance_add",
        "finance_assign",
        "finance_callaway",
        "finance_expire",
        "finance_update",
        "finance_delete",
        "settings_view",
        "add_position_view",
        "register_position_premium",
        "recalc_position_premium",
        "update_position_view",
        "upsert_holding_view",
        "delete_position_view",
    }

    def _session_idle_timeout_seconds() -> int:
        raw = os.getenv("OPCOES_SESSION_IDLE_MINUTES", "15").strip()
        try:
            minutes = int(raw)
        except ValueError:
            minutes = 15
        if minutes <= 0:
            minutes = 15
        return minutes * 60

    def _utc_now_ts() -> int:
        return int(datetime.datetime.now(datetime.timezone.utc).timestamp())

    def _csp_connect_sources() -> str:
        sources = ["'self'"]
        if market_data_client.config.enabled:
            for base_url in {
                market_data_client.config.base_url,
                market_data_client.config.public_base_url,
            }:
                base_parts = urlsplit((base_url or "").strip())
                if base_parts.scheme and base_parts.netloc:
                    sources.append(f"{base_parts.scheme}://{base_parts.netloc}")
                    ws_scheme = "wss" if base_parts.scheme == "https" else "ws"
                    sources.append(f"{ws_scheme}://{base_parts.netloc}")
        return " ".join(dict.fromkeys(sources))

    def _ranking_cache_ttl_seconds() -> int:
        raw = os.getenv("OPCOES_RANKING_CACHE_SECONDS", "45").strip()
        try:
            ttl = int(raw)
        except ValueError:
            ttl = 45
        return max(ttl, 0)

    def _ranking_cache_namespace(username: str | None) -> str:
        normalized = normalize_username(username or "")
        if normalized:
            return f"user:{normalized}"
        return "global"

    def _current_ranking_cache_namespace() -> str:
        username = getattr(g, "current_username", None)
        if not username:
            username = normalize_username(session.get("username") or "")
        return _ranking_cache_namespace(username)

    def _ranking_args_signature() -> tuple:
        return tuple(
            (key, tuple(sorted(str(v) for v in request.args.getlist(key))))
            for key in sorted(request.args.keys())
        )

    def _ranking_cache_key() -> str:
        return build_persisted_page_cache_key(
            route_name="index",
            namespace=_current_ranking_cache_namespace(),
            args_signature=_ranking_args_signature(),
        )

    def _get_ranking_memory_cache(cache_key: str) -> Optional[dict]:
        ttl = _ranking_cache_ttl_seconds()
        if ttl <= 0:
            return None
        now = time.monotonic()
        with ranking_cache_lock:
            entry = ranking_cache.get(cache_key)
            if not entry:
                return None
            expires_at, payload = entry
            if expires_at <= now:
                ranking_cache.pop(cache_key, None)
                return None
            return payload

    def _get_ranking_cache(cache_key: str) -> Optional[dict]:
        payload = _get_ranking_memory_cache(cache_key)
        if payload is not None:
            return payload
        ttl = _ranking_cache_ttl_seconds()
        try:
            payload = get_persisted_page_cache(cache_key=cache_key, ttl_seconds=ttl)
        except Exception:
            payload = None
        if payload is not None:
            _set_ranking_memory_cache(cache_key, payload)
        return payload

    def _set_ranking_memory_cache(cache_key: str, payload: dict) -> None:
        ttl = _ranking_cache_ttl_seconds()
        if ttl <= 0:
            return
        now = time.monotonic()
        expires_at = now + float(ttl)
        with ranking_cache_lock:
            ranking_cache[cache_key] = (expires_at, payload)
            if len(ranking_cache) > 256:
                stale_keys = [
                    key for key, (exp, _ctx) in ranking_cache.items() if exp <= now
                ]
                for key in stale_keys:
                    ranking_cache.pop(key, None)

    def _set_ranking_cache(cache_key: str, payload: dict) -> None:
        ttl = _ranking_cache_ttl_seconds()
        if ttl <= 0:
            return
        _set_ranking_memory_cache(cache_key, payload)
        try:
            set_persisted_page_cache(
                cache_key=cache_key,
                namespace=_current_ranking_cache_namespace(),
                route_name="index",
                args_signature=_ranking_args_signature(),
                ctx=payload,
                ttl_seconds=ttl,
            )
        except Exception:
            pass

    def _invalidate_ranking_cache_for_namespace(namespace: str) -> None:
        if not namespace:
            return
        with ranking_cache_lock:
            keys = [
                key
                for key in ranking_cache.keys()
                if f'"namespace":"{namespace}"' in key
            ]
            for key in keys:
                ranking_cache.pop(key, None)
        try:
            invalidate_persisted_page_cache_namespace(namespace)
        except Exception:
            pass

    def _invalidate_ranking_cache_for_current_user() -> None:
        _invalidate_ranking_cache_for_namespace(_current_ranking_cache_namespace())

    def _strategy_page_cache_ttl_seconds() -> int:
        raw = os.getenv("OPCOES_STRATEGY_PAGE_CACHE_SECONDS", "30").strip()
        try:
            ttl = int(raw)
        except ValueError:
            ttl = 30
        return max(ttl, 0)

    def _strategy_page_args_signature(*, ignore_keys: set[str] | None = None) -> tuple:
        ignored = ignore_keys or set()
        return tuple(
            (key, tuple(sorted(str(v) for v in request.args.getlist(key))))
            for key in sorted(request.args.keys())
            if key not in ignored
        )

    def _strategy_page_cache_key(
        route_name: str, *, ignore_keys: set[str] | None = None
    ) -> str:
        return build_persisted_page_cache_key(
            route_name=route_name,
            namespace=_current_ranking_cache_namespace(),
            args_signature=_strategy_page_args_signature(ignore_keys=ignore_keys),
        )

    def _get_strategy_page_memory_cache(cache_key: str) -> Optional[dict]:
        ttl = _strategy_page_cache_ttl_seconds()
        if ttl <= 0:
            return None
        now = time.monotonic()
        with strategy_page_cache_lock:
            entry = strategy_page_cache.get(cache_key)
            if not entry:
                return None
            expires_at, payload = entry
            if expires_at <= now:
                strategy_page_cache.pop(cache_key, None)
                return None
            return payload

    def _get_strategy_page_cache(cache_key: str) -> Optional[dict]:
        payload = _get_strategy_page_memory_cache(cache_key)
        if payload is not None:
            return payload
        ttl = _strategy_page_cache_ttl_seconds()
        try:
            payload = get_persisted_page_cache(cache_key=cache_key, ttl_seconds=ttl)
        except Exception:
            payload = None
        if payload is not None:
            _set_strategy_page_memory_cache(cache_key, payload)
        return payload

    def _set_strategy_page_memory_cache(cache_key: str, payload: dict) -> None:
        ttl = _strategy_page_cache_ttl_seconds()
        if ttl <= 0:
            return
        now = time.monotonic()
        expires_at = now + float(ttl)
        with strategy_page_cache_lock:
            strategy_page_cache[cache_key] = (expires_at, payload)
            if len(strategy_page_cache) > 256:
                stale_keys = [
                    key
                    for key, (exp, _ctx) in strategy_page_cache.items()
                    if exp <= now
                ]
                for key in stale_keys:
                    strategy_page_cache.pop(key, None)

    def _set_strategy_page_cache(
        cache_key: str,
        payload: dict,
        *,
        route_name: str,
        ignore_keys: set[str] | None = None,
    ) -> None:
        ttl = _strategy_page_cache_ttl_seconds()
        if ttl <= 0:
            return
        _set_strategy_page_memory_cache(cache_key, payload)
        try:
            set_persisted_page_cache(
                cache_key=cache_key,
                namespace=_current_ranking_cache_namespace(),
                route_name=route_name,
                args_signature=_strategy_page_args_signature(ignore_keys=ignore_keys),
                ctx=payload,
                ttl_seconds=ttl,
            )
        except Exception:
            pass

    def _invalidate_strategy_page_cache_for_namespace(namespace: str) -> None:
        if not namespace:
            return
        with strategy_page_cache_lock:
            keys = [
                key
                for key in strategy_page_cache.keys()
                if f'"namespace":"{namespace}"' in key
            ]
            for key in keys:
                strategy_page_cache.pop(key, None)
        try:
            invalidate_persisted_page_cache_namespace(namespace)
        except Exception:
            pass

    def _invalidate_strategy_page_cache_for_current_user() -> None:
        _invalidate_strategy_page_cache_for_namespace(
            _current_ranking_cache_namespace()
        )

    def _csrf_token_value() -> str:
        token = session.get(CSRF_FIELD_NAME)
        if isinstance(token, str) and token.strip():
            return token
        token = token_urlsafe(32)
        session[CSRF_FIELD_NAME] = token
        return token

    def _csrf_input() -> Markup:
        token = _csrf_token_value()
        return Markup(f'<input type="hidden" name="{CSRF_FIELD_NAME}" value="{token}">')

    def _client_ip() -> str:
        # Com ProxyFix ativo, remote_addr já reflete o IP do cliente quando o
        # proxy frontal é confiável. Evitamos confiar em X-Forwarded-For cru.
        return request.remote_addr or "unknown"

    def _login_rate_limit_window_seconds() -> int:
        return _env_int("OPCOES_LOGIN_WINDOW_SECONDS", 900, 60)

    def _login_rate_limit_block_seconds() -> int:
        return _env_int("OPCOES_LOGIN_BLOCK_SECONDS", 900, 60)

    def _login_rate_limit_max_attempts() -> int:
        return _env_int("OPCOES_LOGIN_MAX_ATTEMPTS", 5, 1)

    def _login_rate_limit_message(blocked_for_seconds: int) -> str:
        minutes = max(1, math.ceil(float(blocked_for_seconds) / 60.0))
        return (
            "Muitas tentativas de login deste IP. "
            f"Aguarde cerca de {minutes} minuto(s) e tente novamente."
        )

    def _login_block_remaining_seconds() -> int | None:
        return get_login_block_remaining_seconds(
            client_key=_client_ip(),
            window_seconds=_login_rate_limit_window_seconds(),
        )

    def _record_failed_login() -> int | None:
        return record_failed_login_attempt(
            client_key=_client_ip(),
            window_seconds=_login_rate_limit_window_seconds(),
            block_seconds=_login_rate_limit_block_seconds(),
            max_attempts=_login_rate_limit_max_attempts(),
        )

    def _clear_failed_login() -> None:
        clear_login_rate_limit(client_key=_client_ip())

    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SECURE"] = _env_bool(
        "OPCOES_SESSION_COOKIE_SECURE", False
    )
    app.config["SESSION_COOKIE_SAMESITE"] = (
        os.getenv("OPCOES_SESSION_COOKIE_SAMESITE", "Lax") or "Lax"
    ).strip()
    # Session cookie (sem remember-me): ao fechar navegador, exige login novamente.
    app.config["SESSION_PERMANENT"] = False

    def _is_auth_enabled() -> bool:
        raw = os.getenv("OPCOES_AUTH_ENABLED", "1").strip().lower()
        return raw not in {"0", "false", "no", "off", "nao", "não"}

    def _safe_redirect_target(value: str | None) -> str:
        if not value:
            return url_for("index")
        candidate = value.strip()
        if not candidate.startswith("/") or candidate.startswith("//"):
            return url_for("index")
        if candidate.startswith("/login") or candidate.startswith("/logout"):
            return url_for("index")
        return candidate

    def _is_first_access_pending() -> bool:
        return bool(session.get("must_change_password"))

    @app.before_request
    def _start_request_timing():
        start_request_timing()
        return None

    @app.before_request
    def _protect_csrf():
        if app.testing:
            return None
        if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
            return None
        if (request.endpoint or "") == "static":
            return None
        expected = session.get(CSRF_FIELD_NAME)
        provided = (
            request.form.get(CSRF_FIELD_NAME)
            or request.headers.get("X-CSRF-Token")
            or request.headers.get("X-CSRFToken")
        )
        if not expected or not provided:
            return (
                "Formulario expirado ou invalido. Recarregue a pagina e tente novamente.",
                400,
            )
        if not compare_digest(str(expected), str(provided)):
            return (
                "Formulario expirado ou invalido. Recarregue a pagina e tente novamente.",
                400,
            )
        return None

    @app.before_request
    def _bind_user_context():
        g.pg_schema_override_token = None
        g.current_username = None

        if app.testing or not _is_auth_enabled():
            return None

        endpoint = request.endpoint or ""
        if endpoint in {"login", "logout", "first_access", "static"}:
            return None

        username = normalize_username(session.get("username") or "")
        if not username:
            if endpoint == "live_market_bootstrap":
                return jsonify({"error": "Sessao expirada ou nao autenticada."}), 401
            next_url = (
                request.full_path
                if request.full_path and request.full_path != "/?"
                else request.path
            )
            return redirect(url_for("login", next=next_url))

        now_ts = _utc_now_ts()
        idle_timeout_seconds = _session_idle_timeout_seconds()
        raw_last_activity = session.get("last_activity_at")
        try:
            last_activity_ts = (
                int(raw_last_activity) if raw_last_activity is not None else None
            )
        except (TypeError, ValueError):
            last_activity_ts = None

        if (
            last_activity_ts is not None
            and (now_ts - last_activity_ts) > idle_timeout_seconds
        ):
            next_url = (
                request.full_path
                if request.full_path and request.full_path != "/?"
                else request.path
            )
            session.clear()
            return redirect(url_for("login", next=next_url, reason="expired"))

        if "session_started_at" not in session:
            session["session_started_at"] = now_ts
        # Sliding session: renova enquanto usuário estiver ativo.
        session["last_activity_at"] = now_ts

        app_schema = (session.get("app_schema") or "").strip()
        if not app_schema:
            try:
                app_schema = get_user_app_schema(username) or ""
            except RuntimeError:
                next_url = (
                    request.full_path
                    if request.full_path and request.full_path != "/?"
                    else request.path
                )
                session.clear()
                return redirect(
                    url_for("login", next=next_url, reason="schema-migration")
                )
            if app_schema:
                session["app_schema"] = app_schema

        g.pg_schema_override_token = set_pg_schema_override(app_schema or username)
        g.current_username = username
        if _is_first_access_pending():
            return redirect(url_for("first_access"))
        return None

    @app.teardown_request
    def _clear_user_context(_exc):
        pg_token = getattr(g, "pg_schema_override_token", None)
        if pg_token is not None:
            reset_pg_schema_override(pg_token)
            g.pg_schema_override_token = None

    @app.after_request
    def _invalidate_ranking_cache_after_write(response):
        g._perf_status_code = response.status_code
        endpoint = request.endpoint or ""
        if request.method == "POST" and endpoint in ranking_cache_write_endpoints:
            _invalidate_ranking_cache_for_current_user()
            _invalidate_strategy_page_cache_for_current_user()
        if endpoint != "static":
            response.headers.setdefault("Cache-Control", "no-store")
            response.headers.setdefault("Pragma", "no-cache")
            response.headers.setdefault(
                "Referrer-Policy", "strict-origin-when-cross-origin"
            )
            response.headers.setdefault("X-Content-Type-Options", "nosniff")
            response.headers.setdefault("X-Frame-Options", "DENY")
            response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
            response.headers.setdefault(
                "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
            )
            response.headers.setdefault(
                "Content-Security-Policy",
                (
                    "default-src 'self'; "
                    "base-uri 'self'; "
                    "form-action 'self'; "
                    "frame-ancestors 'none'; "
                    "object-src 'none'; "
                    "img-src 'self' data: https:; "
                    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                    "font-src 'self' data: https://cdn.jsdelivr.net; "
                    f"connect-src {_csp_connect_sources()};"
                ),
            )
            if request.is_secure:
                response.headers.setdefault(
                    "Strict-Transport-Security",
                    "max-age=31536000; includeSubDomains",
                )
        finalize_request_timing()
        server_timing = build_server_timing_header()
        if server_timing:
            response.headers["Server-Timing"] = server_timing
        return response

    @app.context_processor
    def _inject_user_context():
        auth_active = not app.testing and _is_auth_enabled()
        return {
            "auth_enabled": auth_active,
            "current_username": (
                normalize_username(session.get("username") or "") if auth_active else ""
            ),
            "csrf_token": _csrf_token_value,
            "csrf_input": _csrf_input,
            "static_asset_version": static_asset_version,
        }

    @app.route("/login", methods=["GET", "POST"])
    def login() -> str:
        if app.testing or not _is_auth_enabled():
            return redirect(url_for("index"))

        error = None
        should_record_failed_login = False
        if request.method == "GET" and request.args.get("reason") == "expired":
            error = "Sessão expirada por inatividade. Entre novamente."
        elif (
            request.method == "GET" and request.args.get("reason") == "schema-migration"
        ):
            error = (
                "Seu acesso precisa de uma migração de schema para isolar os dados com segurança. "
                "Peça ao administrador para executar `opcoes user migrate-schemas`."
            )
        next_url = _safe_redirect_target(request.values.get("next"))
        if request.method == "POST":
            blocked_for = _login_block_remaining_seconds()
            if blocked_for is not None:
                return (
                    render_template(
                        "login.html",
                        error=_login_rate_limit_message(blocked_for),
                        next_url=next_url,
                    ),
                    429,
                )
            username = normalize_username(request.form.get("username") or "")
            password = request.form.get("password") or ""
            auth_result = authenticate_login(username=username, password=password)
            auth_user = auth_result.user
            if auth_user:
                _clear_failed_login()
                session.clear()
                session["username"] = auth_user.username
                session["app_schema"] = auth_user.app_schema
                session["must_change_password"] = bool(auth_user.must_change_password)
                now_ts = _utc_now_ts()
                session["session_started_at"] = now_ts
                session["last_activity_at"] = now_ts
                if auth_user.must_change_password:
                    session["post_login_redirect"] = next_url
                    return redirect(url_for("first_access"))
                return redirect(next_url)
            if auth_result.error_code == "temp_password_expired":
                error = (
                    "A senha temporaria expirou apos 3 horas. "
                    "Peca ao administrador para emitir uma nova senha de primeiro acesso."
                )
                should_record_failed_login = True
            elif auth_result.error_code == "schema_migration_required":
                error = (
                    "Seu acesso precisa de uma migração de schema para isolar os dados com segurança. "
                    "Peça ao administrador para executar `opcoes user migrate-schemas`."
                )
            else:
                error = "Usuário ou senha inválidos."
                should_record_failed_login = True

        if request.method == "POST" and error and should_record_failed_login:
            blocked_for = _record_failed_login()
            if blocked_for is not None:
                return (
                    render_template(
                        "login.html",
                        error=_login_rate_limit_message(blocked_for),
                        next_url=next_url,
                    ),
                    429,
                )
        return render_template("login.html", error=error, next_url=next_url)

    @app.route("/first-access", methods=["GET", "POST"])
    def first_access() -> str:
        if app.testing or not _is_auth_enabled():
            return redirect(url_for("index"))

        username = normalize_username(session.get("username") or "")
        if not username:
            return redirect(url_for("login"))
        if not _is_first_access_pending():
            return redirect(url_for("index"))

        error = None
        if request.method == "POST":
            password = request.form.get("password") or ""
            password_confirm = request.form.get("password_confirm") or ""
            if password != password_confirm:
                error = "As senhas nao conferem. Revise e tente novamente."
            else:
                try:
                    updated = change_password(username=username, password=password)
                except ValueError as exc:
                    error = str(exc)
                else:
                    if not updated:
                        session.clear()
                        return redirect(url_for("login"))
                    session["must_change_password"] = False
                    next_url = _safe_redirect_target(
                        session.pop("post_login_redirect", None)
                    )
                    return redirect(next_url)

        return render_template("first_access.html", error=error, username=username)

    @app.post("/logout")
    def logout():
        _invalidate_ranking_cache_for_namespace(
            _ranking_cache_namespace(session.get("username"))
        )
        _invalidate_strategy_page_cache_for_namespace(
            _ranking_cache_namespace(session.get("username"))
        )
        session.clear()
        return redirect(url_for("login"))

    @app.route("/")
    def index() -> str:
        with timed_stage("route.index.cache_key"):
            cache_key = _ranking_cache_key()
        with timed_stage("route.index.cache_lookup"):
            ctx = _get_ranking_cache(cache_key)
        if ctx is None:
            with timed_stage("route.index.context"):
                ctx = _build_ranking_shell_page_context(args=request.args)
            with timed_stage("route.index.cache_store"):
                _set_ranking_cache(cache_key, ctx)
        with timed_stage("route.index.render"):
            return render_template("index.html", **ctx)

    @app.route("/partial/ranking")
    def ranking_partial() -> str:
        with timed_stage("route.index_partial.context"):
            ctx = get_ranking_context(request.args)
        with timed_stage("route.index_partial.render"):
            return render_template("partials/ranking_dashboard.html", **ctx)

    @app.route("/covered-call")
    def covered_call() -> str:
        cacheable = not (
            request.args.get("holding_notice") or request.args.get("holding_error")
        )
        ctx = None
        cache_key = None
        if cacheable:
            with timed_stage("route.covered_call.cache_key"):
                cache_key = _strategy_page_cache_key(
                    "covered_call",
                    ignore_keys={"holding_notice", "holding_error"},
                )
            with timed_stage("route.covered_call.cache_lookup"):
                ctx = _get_strategy_page_cache(cache_key)
        if ctx is None:
            with timed_stage("route.covered_call.context"):
                ctx = _build_covered_call_shell_page_context(
                    args=request.args,
                )
            if cacheable and cache_key is not None:
                with timed_stage("route.covered_call.cache_store"):
                    _set_strategy_page_cache(
                        cache_key,
                        ctx,
                        route_name="covered_call",
                        ignore_keys={"holding_notice", "holding_error"},
                    )
        with timed_stage("route.covered_call.render"):
            return render_template("covered_call.html", **ctx)

    @app.get("/live-market/bootstrap")
    def live_market_bootstrap():
        requested_symbols = _parse_requested_live_market_symbols(request.args)
        try:
            fallback_seconds = max(
                int(request.args.get("fallback_seconds") or 60),
                15,
            )
        except (TypeError, ValueError):
            fallback_seconds = 60
        if not requested_symbols:
            return (
                jsonify(
                    {
                        "error": "Nenhum simbolo informado para bootstrap do mercado ao vivo.",
                    }
                ),
                400,
            )
        try:
            bootstrap = market_data_client.create_ws_token()
        except Exception as exc:
            return (
                jsonify(
                    {
                        "error": "Nao foi possivel inicializar o mercado ao vivo.",
                        "details": exc.__class__.__name__,
                    }
                ),
                503,
            )
        return jsonify(
            {
                "ws_url": bootstrap["ws_url"],
                "token": bootstrap["token"],
                "expires_in": bootstrap["expires_in"],
                "symbols": requested_symbols,
                "stale_after_seconds": bootstrap["stale_after_seconds"],
                "fallback_seconds": fallback_seconds,
                "scope": (request.args.get("scope") or "").strip(),
            }
        )

    @app.route("/covered-call/partial/live")
    def covered_call_partial_live() -> str:
        with timed_stage("route.covered_call_partial.context"):
            ctx = _build_covered_call_page_context(
                args=request.args,
                market_data_client=market_data_client,
                persist_settings=False,
                include_financial_sections=False,
                include_inventory_summary=False,
            )
        with timed_stage("route.covered_call_partial.render"):
            return render_template("partials/covered_call_live.html", **ctx)

    @app.route("/covered-call/partial/audit")
    def covered_call_partial_audit() -> str:
        with timed_stage("route.covered_call_audit_partial.context"):
            ctx = _build_covered_call_page_context(
                args=request.args,
                market_data_client=market_data_client,
                persist_settings=False,
                include_financial_sections=True,
                include_inventory_summary=True,
            )
        with timed_stage("route.covered_call_audit_partial.render"):
            return render_template("partials/covered_call_audit.html", **ctx)

    @app.route("/cash-covered-put")
    def cash_covered_put() -> str:
        with timed_stage("route.cash_put.cache_key"):
            cache_key = _strategy_page_cache_key("cash_covered_put")
        with timed_stage("route.cash_put.cache_lookup"):
            ctx = _get_strategy_page_cache(cache_key)
        if ctx is None:
            with timed_stage("route.cash_put.context"):
                ctx = get_cash_covered_put_context(request.args)
            with timed_stage("route.cash_put.cache_store"):
                _set_strategy_page_cache(
                    cache_key,
                    ctx,
                    route_name="cash_covered_put",
                )
        with timed_stage("route.cash_put.render"):
            ctx["position_error"] = (request.args.get("position_error") or "").strip()
            return render_template("cash_covered_put.html", **ctx)

    @app.route("/fundamentus")
    def fundamentus() -> str:
        with timed_stage("route.fundamentus.cache_key"):
            cache_key = _strategy_page_cache_key("fundamentus")
        with timed_stage("route.fundamentus.cache_lookup"):
            ctx = _get_strategy_page_cache(cache_key)
        if ctx is None:
            with timed_stage("route.fundamentus.context"):
                ctx = _build_fundamentus_shell_page_context(args=request.args)
            with timed_stage("route.fundamentus.cache_store"):
                _set_strategy_page_cache(
                    cache_key,
                    ctx,
                    route_name="fundamentus",
                )
        with timed_stage("route.fundamentus.render"):
            return render_template("fundamentus.html", **ctx)

    @app.route("/fundamentus/partial/dashboard")
    def fundamentus_partial_dashboard() -> str:
        with timed_stage("route.fundamentus_partial.context"):
            ctx = get_fundamentus_context(request.args)
        with timed_stage("route.fundamentus_partial.render"):
            return render_template("partials/fundamentus_dashboard.html", **ctx)

    @app.route("/favicon.ico")
    def favicon() -> tuple[str, int]:
        return ("", 204)

    @app.route("/darf")
    def darf_view() -> str:
        mode = (request.args.get("mode") or "real").strip().lower()
        is_simulated = mode == "simulated"
        selected_period = (request.args.get("period") or "").strip()

        def _safe_period(value: object) -> str:
            text = str(value or "").strip()
            if len(text) != 7 or text[4] != "-":
                return ""
            try:
                year = int(text[:4])
                month = int(text[5:7])
            except ValueError:
                return ""
            if month < 1 or month > 12:
                return ""
            return f"{year:04d}-{month:02d}"

        provisions = darf.get_monthly_darf_provisions(
            is_simulated=is_simulated, limit=36
        )
        records = darf.list_months(is_simulated=is_simulated, limit=36)
        record_by_period = {
            normalized: r
            for r in records
            for normalized in [_safe_period(getattr(r, "period", ""))]
            if normalized
        }
        provision_by_period = {
            normalized: float(amount or 0.0)
            for period, amount in provisions.items()
            for normalized in [_safe_period(period)]
            if normalized
        }
        tax_periods = sorted(
            {f"{today.year:04d}-{today.month:02d}" for today in [datetime.date.today()]}
            | set(provision_by_period.keys())
            | set(record_by_period.keys()),
            reverse=True,
        )
        if not tax_periods:
            today = datetime.date.today()
            tax_periods = [today.strftime("%Y-%m")]

        # Garante uma janela recente para o usuário conseguir navegar mesmo sem lançamentos.
        anchor_year = int(tax_periods[0][:4])
        anchor_month = int(tax_periods[0][5:7])
        recent_periods: list[str] = []
        year = anchor_year
        month = anchor_month
        for _ in range(12):
            recent_periods.append(f"{year:04d}-{month:02d}")
            month -= 1
            if month == 0:
                month = 12
                year -= 1
        periods = sorted(set(recent_periods) | set(tax_periods), reverse=True)

        tax_summaries = list_monthly_tax_summaries(
            periods=periods,
            is_simulated=is_simulated,
        )
        tax_by_period = {summary.period: summary for summary in tax_summaries}

        if not selected_period:
            if periods:
                selected_period = periods[0]
            else:
                selected_period = datetime.date.today().strftime("%Y-%m")

        summaries = []
        for p in periods:
            tax_summary = tax_by_period.get(p) or compute_tax(
                month=int(p[5:7]),
                year=int(p[:4]),
                is_simulated=is_simulated,
            )
            prov = float(provision_by_period.get(p, 0.0) or 0.0)
            rec = record_by_period.get(p)
            try:
                due_date = rec.due_date if rec else darf.last_business_day_next_month(p)
            except Exception:
                due_date = "-"

            generated = rec.amount if rec else None
            paid_date = rec.paid_date if rec else None
            paid_amount = rec.paid_amount if rec else None
            tax_due = float(tax_summary.net_ir_due or 0.0)

            status = "Sem movimento"
            if tax_due > 0 and not rec:
                status = "Pendente"
            if rec and not rec.paid_date:
                status = "Gerado"
            if rec and rec.paid_date:
                status = "Pago"

            diff = None
            if rec is not None:
                diff = tax_due - float(rec.amount or 0.0)

            summaries.append(
                {
                    "period": p,
                    "tax_summary": tax_summary,
                    "tax_due": tax_due,
                    "provisioned": prov,
                    "generated": generated,
                    "due_date": due_date,
                    "paid_date": paid_date,
                    "paid_amount": paid_amount,
                    "status": status,
                    "diff": diff,
                }
            )

        selected_record = None
        try:
            selected_record = darf.get_month(
                period=selected_period, is_simulated=is_simulated
            )
        except Exception:
            selected_record = None

        provision_entries = []
        try:
            provision_entries = darf.list_provision_entries(
                period=selected_period, is_simulated=is_simulated
            )
        except Exception:
            provision_entries = []

        selected_tax = tax_by_period.get(selected_period)
        if selected_tax is None:
            selected_tax = compute_tax(
                month=int(selected_period[5:7]),
                year=int(selected_period[:4]),
                is_simulated=is_simulated,
            )
        selected_tax_events = list_tax_events_for_period(
            period=selected_period,
            is_simulated=is_simulated,
        )
        selected_provisioned = float(
            provision_by_period.get(selected_period, 0.0) or 0.0
        )

        return render_template(
            "darf.html",
            mode=mode,
            is_simulated=is_simulated,
            selected_period=selected_period,
            periods=summaries,
            selected_tax=selected_tax,
            selected_tax_events=selected_tax_events,
            selected_provisioned=selected_provisioned,
            provision_entries=provision_entries,
            selected_record=selected_record,
        )

    @app.post("/darf/generate")
    def darf_generate():
        form = request.form
        period = (form.get("period") or "").strip()
        is_simulated = form.get("is_simulated") == "1"
        mode = "simulated" if is_simulated else "real"

        try:
            summary = compute_tax(
                month=int(period[5:7]),
                year=int(period[:4]),
                is_simulated=is_simulated,
            )
            due_date = darf.last_business_day_next_month(period)
        except Exception:
            return redirect(url_for("darf_view", mode=mode))

        if summary.net_ir_due > 0:
            darf.upsert_month(
                period=period,
                due_date=due_date,
                amount=summary.net_ir_due,
                is_simulated=is_simulated,
            )
        else:
            darf.delete_month(
                period=period,
                is_simulated=is_simulated,
                only_unpaid=True,
            )

        return redirect(url_for("darf_view", mode=mode, period=period))

    @app.post("/darf/pay")
    def darf_pay():
        form = request.form
        period = (form.get("period") or "").strip()
        is_simulated = form.get("is_simulated") == "1"
        mode = "simulated" if is_simulated else "real"
        paid_date = (
            _parse_form_date(form.get("paid_date")) or datetime.date.today().isoformat()
        )
        paid_amount = (
            _parse_form_float(form.get("paid_amount"))
            if form.get("paid_amount")
            else None
        )

        try:
            rec = darf.get_month(period=period, is_simulated=is_simulated)
            if not rec:
                summary = compute_tax(
                    month=int(period[5:7]),
                    year=int(period[:4]),
                    is_simulated=is_simulated,
                )
                if summary.net_ir_due <= 0:
                    return redirect(url_for("darf_view", mode=mode, period=period))
                due_date = darf.last_business_day_next_month(period)
                darf.upsert_month(
                    period=period,
                    due_date=due_date,
                    amount=summary.net_ir_due,
                    is_simulated=is_simulated,
                )
            darf.mark_paid(
                period=period,
                paid_date=paid_date,
                paid_amount=paid_amount,
                is_simulated=is_simulated,
            )
        except Exception:
            return redirect(url_for("darf_view", mode=mode, period=period))

        return redirect(url_for("darf_view", mode=mode, period=period))

    @app.post("/finance/add")
    def finance_add():
        form = request.form
        amount = _parse_form_float(form.get("amount"))
        type_str = form.get("type")
        desc = form.get("description") or "Movimentação manual"
        date = form.get("date") or datetime.date.today().isoformat()
        is_simulated = form.get("is_simulated") == "1"

        # Valid transaction type
        try:
            tx_type = finance.TransactionType(type_str)
        except ValueError:
            return redirect(url_for("cash_covered_put"))  # Or error page

        # Negative amount for withdrawal
        if tx_type == finance.TransactionType.WITHDRAWAL and amount > 0:
            amount = -amount

        finance.add_transaction(
            date=date,
            type=tx_type,
            amount=amount,
            description=desc,
            is_simulated=is_simulated,
        )
        return redirect(url_for("cash_covered_put"))

    @app.post("/finance/assign")
    def finance_assign():
        form = request.form
        position_id = int(form.get("position_id"))
        pos = get_position(position_id)
        underlying = (pos.get("underlying") or "").strip().upper() if pos else ""
        date = _parse_form_date(form.get("date"))
        purchase_fees = form.get("purchase_fees")
        if not date:
            return redirect(
                url_for(
                    "cash_covered_put",
                    underlying=underlying,
                    position_error=(
                        "Nao foi possivel confirmar a data de vencimento/exercicio da PUT. "
                        "A baixa foi bloqueada para evitar registro na data errada."
                    ),
                )
                if underlying
                else url_for("cash_covered_put")
            )
        if purchase_fees is None or not purchase_fees.strip():
            return redirect(
                url_for(
                    "cash_covered_put",
                    underlying=underlying,
                    position_error=(
                        "Informe as despesas da compra da nota, inclusive R$ 0,00 quando nao houver despesas."
                    ),
                )
                if underlying
                else url_for("cash_covered_put")
            )
        strike = _parse_form_float(form.get("strike"))
        try:
            qty = int(form.get("qty")) if form.get("qty") else None
        except (TypeError, ValueError):
            qty = None
        try:
            assign_put(
                position_id=position_id,
                strike=strike,
                qty=qty,
                date=date,
                purchase_fees=purchase_fees,
            )
        except (HoldingValidationError, FlowError) as exc:
            message = str(exc) or "Nao foi possivel registrar o exercicio da PUT."
            return redirect(
                url_for("cash_covered_put", underlying=underlying, position_error=message)
                if underlying
                else url_for("cash_covered_put")
            )
        return redirect(
            url_for("cash_covered_put", underlying=underlying)
            if underlying
            else url_for("cash_covered_put")
        )

    @app.post("/finance/callaway")
    def finance_callaway():
        form = request.form
        position_id = int(form.get("position_id"))
        pos = get_position(position_id)
        underlying = (pos.get("underlying") or "").strip().upper() if pos else ""
        date = _parse_form_date(form.get("date"))
        sale_fees = form.get("sale_fees")
        if not date:
            return redirect(
                url_for(
                    "covered_call",
                    underlying=underlying,
                    holding_error=(
                        "Nao foi possivel confirmar a data de vencimento/exercicio da CALL. "
                        "A baixa foi bloqueada para evitar registro na data errada."
                    ),
                )
            )
        if sale_fees is None or not sale_fees.strip():
            return redirect(
                url_for(
                    "covered_call",
                    underlying=underlying,
                    holding_error=(
                        "Informe as despesas da venda da nota, inclusive R$ 0,00 quando nao houver despesas."
                    ),
                )
            )
        try:
            underlying = callaway(
                position_id=position_id,
                date=date,
                sale_fees=sale_fees,
            )
        except FlowError as exc:
            if exc.underlying:
                return redirect(
                    url_for(
                        "covered_call",
                        underlying=exc.underlying,
                        holding_error=str(exc),
                    )
                )
            return redirect(url_for("covered_call", holding_error=str(exc)))

        if underlying:
            return redirect(url_for("covered_call", underlying=underlying))
        return redirect(url_for("covered_call"))

    @app.post("/finance/expire")
    def finance_expire():
        form = request.form
        try:
            position_id = int(form.get("position_id"))
        except (TypeError, ValueError):
            return redirect(url_for("positions"))

        parsed_date = _parse_form_date(form.get("date"))
        date = parsed_date or datetime.date.today().isoformat()

        pos = get_position(position_id)
        if not pos:
            return redirect(url_for("positions"))

        ticker = pos.get("ticker")
        underlying = (pos.get("underlying") or "").strip().upper()
        opt_type = infer_option_type(ticker)

        if not underlying or (ticker and (str(ticker).strip().upper() == underlying)):
            return redirect(url_for("positions"))

        if (pos.get("status") or "").strip().lower() != "open":
            if opt_type == "PUT":
                return redirect(
                    url_for("cash_covered_put", underlying=underlying)
                    if underlying
                    else url_for("cash_covered_put")
                )
            if opt_type == "CALL":
                return redirect(
                    url_for("covered_call", underlying=underlying)
                    if underlying
                    else url_for("covered_call")
                )
            return redirect(url_for("positions"))

        if opt_type not in {"PUT", "CALL"}:
            return redirect(url_for("positions"))
        if (
            opt_type == "PUT"
            and (pos.get("strategy_tag") or "").strip().lower() == "cash_put"
            and not parsed_date
        ):
            return redirect(
                url_for(
                    "cash_covered_put",
                    underlying=underlying,
                    position_error=(
                        "Nao foi possivel confirmar o vencimento da PUT. "
                        "A expiracao foi bloqueada para evitar fechamento na data errada."
                    ),
                )
            )
        if (
            opt_type == "CALL"
            and (pos.get("strategy_tag") or "").strip().lower() == "covered_call"
            and not parsed_date
        ):
            return redirect(
                url_for(
                    "covered_call",
                    underlying=underlying,
                    holding_error=(
                        "Nao foi possivel confirmar o vencimento da CALL. "
                        "A expiracao foi bloqueada para evitar fechamento na data errada."
                    ),
                )
            )

        close_position(
            position_id=position_id,
            exit_date=date,
            exit_price=0.0,
            exit_reason="Expiração",
        )
        finance.sync_position_closure_effects(position_id=position_id)

        if opt_type == "PUT":
            return redirect(
                url_for("cash_covered_put", underlying=underlying)
                if underlying
                else url_for("cash_covered_put")
            )
        return redirect(
            url_for("covered_call", underlying=underlying)
            if underlying
            else url_for("covered_call")
        )

    @app.post("/finance/update/<int:tx_id>")
    def finance_update(tx_id: int):
        form = request.form
        date = form.get("date") or None
        type_str = form.get("type") or None
        desc = form.get("description") or None
        amount = _parse_form_float(form.get("amount"))
        is_simulated = form.get("is_simulated") == "1"

        tx_type = None
        if type_str:
            try:
                tx_type = finance.TransactionType(type_str)
            except ValueError:
                tx_type = None

        # mesma regra: retirada em valor positivo vira negativo
        if tx_type == finance.TransactionType.WITHDRAWAL and amount > 0:
            amount = -amount

        finance.update_transaction(
            tx_id,
            date=date,
            type=tx_type,
            amount=amount,
            description=desc,
            is_simulated=is_simulated,
        )
        return redirect(url_for("cash_covered_put"))

    @app.post("/finance/delete/<int:tx_id>")
    def finance_delete(tx_id: int):
        finance.delete_transaction(tx_id)
        return redirect(url_for("cash_covered_put"))

    @app.route("/settings", methods=["GET", "POST"])
    def settings_view() -> str:
        def _format_panel_datetime(
            value: object,
            *,
            tz: datetime.tzinfo = LOCAL_DISPLAY_TZ,
        ) -> str:
            if value is None:
                return "-"
            if isinstance(value, datetime.datetime):
                current = value
            else:
                return str(value)
            if current.tzinfo is None:
                current = current.replace(tzinfo=datetime.timezone.utc)
            localized = current.astimezone(tz)
            return localized.strftime("%d/%m/%Y %H:%M")

        def _format_duration(seconds: object) -> str:
            if seconds is None:
                return "-"
            try:
                total = max(int(seconds), 0)
            except (TypeError, ValueError):
                return "-"
            if total < 60:
                return f"{total}s"
            minutes, rem_seconds = divmod(total, 60)
            if minutes < 60:
                return f"{minutes}m {rem_seconds:02d}s"
            hours, rem_minutes = divmod(minutes, 60)
            return f"{hours}h {rem_minutes:02d}m"

        def _status_meta(status: object) -> tuple[str, str]:
            normalized = str(status or "").strip().lower()
            mapping = {
                "running": ("Em andamento", "text-bg-warning"),
                "stalled": ("Possivel travamento", "text-bg-danger"),
                "success": ("Concluido", "text-bg-success"),
                "failed": ("Falhou", "text-bg-danger"),
            }
            return mapping.get(normalized, ("Sem registro", "text-bg-secondary"))

        if request.method == "POST":
            form = request.form

            # Fee Settings
            equity_fixed = _parse_form_float(form.get("equity_fixed"))
            equity_percent = _parse_form_float(form.get("equity_percent"))
            option_fixed = _parse_form_float(form.get("option_fixed"))
            option_percent_notional = _parse_form_float(
                form.get("option_percent_notional")
            )
            update_fee_settings(
                equity_fixed=equity_fixed,
                equity_percent=equity_percent,
                option_fixed=option_fixed,
                option_percent_notional=option_percent_notional,
            )

            # Strategy Settings
            min_score = int(form.get("strat_min_score", 8))
            limit_opp = int(form.get("strat_limit_opportunities", 30))
            recur_days = int(form.get("strat_recurring_days", 30))
            update_strategy_settings(
                min_score=min_score,
                limit_opportunities=limit_opp,
                recurring_days=recur_days,
            )

            fund_cfg = get_fundamentus_settings()

            def _form_float_or_default(name: str, current: float) -> float:
                raw = form.get(name)
                if raw is None or not str(raw).strip():
                    return current
                return _parse_form_float(raw)

            update_fundamentus_settings(
                target_yield_pct=_form_float_or_default(
                    "fund_target_yield_pct", fund_cfg.target_yield_pct
                ),
                put_distance_limit_pct=_form_float_or_default(
                    "fund_put_distance_limit_pct",
                    fund_cfg.put_distance_limit_pct,
                ),
                put_min_premium_pct=_form_float_or_default(
                    "fund_put_min_premium_pct",
                    fund_cfg.put_min_premium_pct,
                ),
                put_target_monthly_yield_pct=_form_float_or_default(
                    "fund_put_target_monthly_yield_pct",
                    fund_cfg.put_target_monthly_yield_pct,
                ),
                put_min_score=_form_float_or_default(
                    "fund_put_min_score", fund_cfg.put_min_score
                ),
            )

            cash_put_cfg = get_cash_put_settings()
            buyback_raw = form.get("cash_put_buyback_target_pct")
            if buyback_raw and buyback_raw.strip():
                buyback_target_pct = _parse_form_float(buyback_raw)
            else:
                buyback_target_pct = cash_put_cfg.buyback_target_pct
            update_cash_put_settings(
                underlying=cash_put_cfg.underlying,
                min_yield_pct=cash_put_cfg.min_yield_pct,
                min_buffer_pct=cash_put_cfg.min_buffer_pct,
                min_days=cash_put_cfg.min_days,
                max_days=cash_put_cfg.max_days,
                contract_size=cash_put_cfg.contract_size,
                limit=cash_put_cfg.limit,
                cash_mode=cash_put_cfg.cash_mode,
                buyback_target_pct=buyback_target_pct,
            )

            ccall_cfg = get_covered_call_settings()
            ccall_buyback_raw = form.get("ccall_buyback_target_pct")
            if ccall_buyback_raw and ccall_buyback_raw.strip():
                ccall_buyback_target_pct = _parse_form_float(ccall_buyback_raw)
            else:
                ccall_buyback_target_pct = ccall_cfg.buyback_target_pct
            update_covered_call_settings(
                underlying=ccall_cfg.underlying,
                min_extrinsic=ccall_cfg.min_extrinsic,
                min_days=ccall_cfg.min_days,
                max_days=ccall_cfg.max_days,
                min_dist_strike=ccall_cfg.min_dist_strike,
                buyback_target_pct=ccall_buyback_target_pct,
                only_target_hits=ccall_cfg.only_target_hits,
            )

            return redirect(url_for("settings_view"))

        fees_cfg: FeeSettings = get_fee_settings()
        strat_cfg: StrategySettings = get_strategy_settings()
        fund_cfg: FundamentusSettings = get_fundamentus_settings()
        ccall_cfg: CoveredCallSettings = get_covered_call_settings()
        cash_put_cfg: CashCoveredPutSettings = get_cash_put_settings()
        automation_dashboard = get_service_dashboard(limit=12)

        automation_services = []
        for service in automation_dashboard.get("services", []):
            last_run = service.get("last_run")
            last_run_view = None
            if isinstance(last_run, dict):
                status_label, status_class = _status_meta(
                    last_run.get("monitor_status") or last_run.get("status")
                )
                last_run_view = {
                    "status_label": status_label,
                    "status_class": status_class,
                    "scheduled_for_display": _format_panel_datetime(
                        last_run.get("scheduled_for_display_utc")
                    ),
                    "started_at_display": _format_panel_datetime(
                        last_run.get("started_at")
                    ),
                    "finished_at_display": _format_panel_datetime(
                        last_run.get("finished_at")
                    ),
                    "duration_display": _format_duration(
                        last_run.get("display_duration_seconds")
                    ),
                    "summary": (last_run.get("summary") or "").strip(),
                    "error_message": (last_run.get("error_message") or "").strip(),
                    "warning_message": (last_run.get("monitor_message") or "").strip(),
                }
            automation_services.append(
                {
                    **service,
                    "next_run_local_display": _format_panel_datetime(
                        service.get("next_run_local")
                    ),
                    "next_run_utc_display": _format_panel_datetime(
                        service.get("next_run_utc"),
                        tz=datetime.timezone.utc,
                    ),
                    "last_run_view": last_run_view,
                }
            )

        automation_runs = []
        for row in automation_dashboard.get("recent_runs", []):
            status_label, status_class = _status_meta(
                row.get("monitor_status") or row.get("status")
            )
            automation_runs.append(
                {
                    **row,
                    "status_label": status_label,
                    "status_class": status_class,
                    "scheduled_for_display": _format_panel_datetime(
                        row.get("scheduled_for_display_utc")
                    ),
                    "started_at_display": _format_panel_datetime(row.get("started_at")),
                    "finished_at_display": _format_panel_datetime(
                        row.get("finished_at")
                    ),
                    "duration_display": _format_duration(
                        row.get("display_duration_seconds")
                    ),
                    "summary_display": (row.get("summary") or "").strip(),
                    "error_display": (row.get("error_message") or "").strip(),
                    "warning_display": (row.get("monitor_message") or "").strip(),
                }
            )
        return render_template(
            "settings.html",
            fees=fees_cfg,
            strat=strat_cfg,
            fund=fund_cfg,
            covered_call=ccall_cfg,
            cash_put=cash_put_cfg,
            automation_services=automation_services,
            automation_runs=automation_runs,
        )

    @app.route("/positions")
    def positions() -> str:
        ticker_contains = (request.args.get("ticker") or "").strip().upper()
        underlying_contains = (request.args.get("underlying") or "").strip().upper()
        strategy_tag = (request.args.get("strategy_tag") or "").strip()
        trade_type = (request.args.get("trade_type") or "").strip().lower()
        status = (request.args.get("status") or "all").strip().lower()
        is_simulated_raw = (request.args.get("is_simulated") or "").strip()
        result_year_raw = (request.args.get("result_year") or "").strip()
        result_month_raw = (request.args.get("result_month") or "").strip()

        next_url = request.full_path
        if next_url.endswith("?"):
            next_url = request.path

        with timed_stage("route.positions.cache_key"):
            cache_key = _strategy_page_cache_key("positions")
        with timed_stage("route.positions.cache_lookup"):
            ctx = _get_strategy_page_cache(cache_key)
        if ctx is None:
            with timed_stage("route.positions.context"):
                ctx = _build_positions_page_context(
                    ticker_contains=ticker_contains,
                    underlying_contains=underlying_contains,
                    strategy_tag=strategy_tag,
                    trade_type=trade_type,
                    status=status,
                    is_simulated_raw=is_simulated_raw,
                    result_year_raw=result_year_raw,
                    result_month_raw=result_month_raw,
                    market_data_client=market_data_client,
                )
            with timed_stage("route.positions.cache_store"):
                _set_strategy_page_cache(
                    cache_key,
                    ctx,
                    route_name="positions",
                )
        ctx["next_url"] = next_url
        ctx["position_error"] = (request.args.get("position_error") or "").strip()
        ctx["holding_notice"] = (request.args.get("holding_notice") or "").strip()
        ctx["holding_error"] = (request.args.get("holding_error") or "").strip()
        with timed_stage("route.positions.render"):
            return render_template("positions.html", **ctx)

    @app.route("/positions/partial/live")
    def positions_partial_live() -> str:
        ticker_contains = (request.args.get("ticker") or "").strip().upper()
        underlying_contains = (request.args.get("underlying") or "").strip().upper()
        strategy_tag = (request.args.get("strategy_tag") or "").strip()
        trade_type = (request.args.get("trade_type") or "").strip().lower()
        status = (request.args.get("status") or "all").strip().lower()
        is_simulated_raw = (request.args.get("is_simulated") or "").strip()
        result_year_raw = (request.args.get("result_year") or "").strip()
        result_month_raw = (request.args.get("result_month") or "").strip()
        next_url = request.args.get("next_url") or "/positions"
        with timed_stage("route.positions_partial.context"):
            ctx = _build_positions_page_context(
                ticker_contains=ticker_contains,
                underlying_contains=underlying_contains,
                strategy_tag=strategy_tag,
                trade_type=trade_type,
                status=status,
                is_simulated_raw=is_simulated_raw,
                result_year_raw=result_year_raw,
                result_month_raw=result_month_raw,
                market_data_client=market_data_client,
            )
        ctx["next_url"] = next_url
        with timed_stage("route.positions_partial.render"):
            return render_template("partials/positions_live.html", **ctx)

    @app.route("/audit")
    def audit_view() -> str:
        mode = (request.args.get("mode") or "real").strip().lower()
        include_closed = (request.args.get("include_closed") or "1") == "1"

        is_simulated: Optional[bool]
        if mode == "simulated":
            is_simulated = True
        elif mode == "all":
            is_simulated = None
        else:
            mode = "real"
            is_simulated = False

        positions_all = list_positions(include_closed=True)
        if is_simulated is not None:
            positions_all = [
                p for p in positions_all if bool(p.get("is_simulated")) == is_simulated
            ]

        inventory_summary = _build_inventory_overview_global(positions_all)

        ledger_sums = finance.get_ledger_sums_by_position(
            types=[
                finance.TransactionType.PREMIUM,
                finance.TransactionType.DARF,
                finance.TransactionType.BUY,
                finance.TransactionType.SELL,
                finance.TransactionType.ASSIGNMENT,
                finance.TransactionType.REALIZED,
            ],
            is_simulated=is_simulated,
        )
        audit_context = build_audit_reconciliation(
            positions_all,
            ledger_sums=ledger_sums,
            include_closed=include_closed,
            holding_events=list_holding_events(limit=1000),
        )

        return render_template(
            "audit.html",
            rows=audit_context["rows"],
            totals=audit_context["totals"],
            mode=mode,
            include_closed=include_closed,
            orphan_rows=audit_context["orphan_rows"],
            audit_issues=audit_context["audit_issues"],
            inventory_summary=inventory_summary,
        )

    @app.route("/performance")
    def performance_view() -> str:
        mode = (request.args.get("mode") or "real").strip().lower()
        if mode not in {"real", "simulated"}:
            mode = "real"
        is_simulated = mode == "simulated"
        positions_all = list_positions(include_closed=True)
        ledger_sums = finance.get_ledger_sums_by_position(
            types=[
                finance.TransactionType.PREMIUM,
                finance.TransactionType.DARF,
                finance.TransactionType.REALIZED,
            ],
            is_simulated=is_simulated,
        )
        context = build_strategy_performance(
            positions_all,
            ledger_sums=ledger_sums,
            is_simulated=is_simulated,
        )
        evidence_pending_cycles = []
        documents_exhausted_cycles = []
        shared_fee_pending_cycles = []
        for cycle in context["incomplete_cycles"]:
            reasons = list(cycle.get("missing_reasons") or [])
            has_non_fee_pending = any(
                "taxas compartilhadas da nota" not in str(reason).lower()
                for reason in reasons
            )
            if (
                has_non_fee_pending
                and cycle.get("performance_evidence_state") == "documents_exhausted"
            ):
                documents_exhausted_cycles.append(cycle)
            elif has_non_fee_pending:
                evidence_pending_cycles.append(cycle)
            else:
                shared_fee_pending_cycles.append(cycle)
        context["evidence_pending_cycles"] = evidence_pending_cycles
        context["documents_exhausted_cycles"] = documents_exhausted_cycles
        context["shared_fee_pending_cycles"] = shared_fee_pending_cycles
        try:
            wheel_cycles = list_wheel_cycles(is_simulated=is_simulated)
        except (RuntimeError, WheelCycleError) as exc:
            wheel_cycles = []
            wheel_error = f"Nao foi possivel carregar os ciclos Wheel: {exc}"
        else:
            wheel_error = (request.args.get("wheel_error") or "").strip()
        return render_template(
            "performance.html",
            mode=mode,
            performance=context,
            wheel_cycles=wheel_cycles,
            wheel_leg_types=WHEEL_LEG_TYPES,
            wheel_error=wheel_error,
            wheel_notice=(request.args.get("wheel_notice") or "").strip(),
            performance_error=(request.args.get("performance_error") or "").strip(),
            performance_notice=(request.args.get("performance_notice") or "").strip(),
        )

    @app.post("/performance/contract/<int:position_id>")
    def update_performance_contract(position_id: int):
        position = get_position(position_id)
        mode = (request.form.get("mode") or "real").strip().lower()
        if mode not in {"real", "simulated"}:
            mode = "real"
        if not _is_short_strategy_performance_position(position):
            return redirect(
                url_for(
                    "performance_view",
                    mode=mode,
                    performance_error="Somente vendas de PUT/Call das estrategias podem receber dados de desempenho.",
                )
            )
        if bool(position.get("is_simulated") or 0) != (mode == "simulated"):
            return redirect(
                url_for(
                    "performance_view",
                    mode=mode,
                    performance_error="A posicao informada pertence a outro modo.",
                )
            )

        def resolve_optional_positive_currency(
            field_name: str,
            current_value: Any,
            *,
            label: str,
        ) -> float | None:
            submitted = (request.form.get(field_name) or "").strip()
            if submitted:
                return _parse_required_positive_currency(submitted, label=label)
            try:
                existing = float(current_value)
            except (TypeError, ValueError):
                existing = 0.0
            if existing > 0 and math.isfinite(existing):
                return existing
            return None

        try:
            strike = resolve_optional_positive_currency(
                "contract_strike",
                position.get("contract_strike"),
                label="Strike",
            )
            capital = resolve_optional_positive_currency(
                "capital_committed",
                position.get("capital_committed"),
                label="Capital comprometido",
            )
        except ValueError as exc:
            return redirect(
                url_for("performance_view", mode=mode, performance_error=str(exc))
            )

        submitted_expiry = (request.form.get("contract_expiry") or "").strip()
        expiry = (
            _parse_form_date(submitted_expiry)
            if submitted_expiry
            else (position.get("contract_expiry") or "").strip()
        )
        source_ref = (
            (request.form.get("performance_source_ref") or "").strip()
            or (position.get("performance_source_ref") or "").strip()
        )
        submitted_strike = (request.form.get("contract_strike") or "").strip()
        submitted_capital = (request.form.get("capital_committed") or "").strip()
        submitted_source_ref = (request.form.get("performance_source_ref") or "").strip()
        if not any((submitted_strike, submitted_capital, submitted_expiry, submitted_source_ref)):
            return redirect(
                url_for(
                    "performance_view",
                    mode=mode,
                    performance_error="Informe ao menos uma evidência para atualizar.",
                )
            )
        if (submitted_expiry and not expiry) or (
            any((submitted_strike, submitted_expiry)) and not source_ref
        ):
            return redirect(
                url_for(
                    "performance_view",
                    mode=mode,
                    performance_error="Informe uma fonte verificável para cada evidência e use vencimento válido quando preenchido.",
                )
            )

        parent_position_id = _parse_optional_positive_int(
            request.form.get("stock_position_id")
        )
        if _is_call_exercise_position(position):
            if parent_position_id is None:
                return redirect(
                    url_for(
                        "performance_view",
                        mode=mode,
                        performance_error="CALL exercida exige o ID do historico de venda da acao para calcular o resultado completo.",
                    )
                )
            stock_position = get_position(parent_position_id)
            if not _is_matching_exercised_call_stock(position, stock_position):
                return redirect(
                    url_for(
                        "performance_view",
                        mode=mode,
                        performance_error="O ID informado nao e a venda de acao correspondente a esta CALL exercida.",
                    )
                )
            linked_parent_id = _parse_optional_positive_int(
                str(stock_position.get("parent_position_id") or "")
            )
            if linked_parent_id not in {None, position_id}:
                return redirect(
                    url_for(
                        "performance_view",
                        mode=mode,
                        performance_error="O historico de acao ja esta vinculado a outra CALL.",
                    )
                )
        elif parent_position_id is not None:
            return redirect(
                url_for(
                    "performance_view",
                    mode=mode,
                    performance_error="O vinculo de acao so pode ser informado para CALL exercida.",
                )
            )

        try:
            with db_transaction() as conn:
                position_changes: dict[str, Any] = {
                    "contract_strike": strike,
                    "contract_expiry": expiry or None,
                    "capital_committed": capital,
                    "performance_source_ref": source_ref or None,
                    "performance_evidence_state": "pending",
                }
                if submitted_capital:
                    position_changes["capital_source"] = "garantia_declarada_usuario"
                update_position(
                    position_id=position_id,
                    conn=conn,
                    **position_changes,
                )
                if parent_position_id is not None:
                    update_position(
                        position_id=parent_position_id,
                        parent_position_id=position_id,
                        conn=conn,
                    )
        except ValueError as exc:
            return redirect(
                url_for("performance_view", mode=mode, performance_error=str(exc))
            )
        return redirect(
            url_for(
                "performance_view",
                mode=mode,
                performance_notice=f"Contrato da posicao #{position_id} atualizado para a apuracao.",
            )
        )

    @app.post("/performance/contract/<int:position_id>/documents-exhausted")
    def mark_performance_documents_exhausted(position_id: int):
        position = get_position(position_id)
        mode = (request.form.get("mode") or "real").strip().lower()
        if mode not in {"real", "simulated"}:
            mode = "real"
        if not _is_short_strategy_performance_position(position):
            return redirect(
                url_for(
                    "performance_view",
                    mode=mode,
                    performance_error="Somente vendas de PUT/Call das estrategias podem receber auditoria de desempenho.",
                )
            )
        if bool(position.get("is_simulated") or 0) != (mode == "simulated"):
            return redirect(
                url_for(
                    "performance_view",
                    mode=mode,
                    performance_error="A posicao informada pertence a outro modo.",
                )
            )

        source_ref = (
            (request.form.get("performance_source_ref") or "").strip()
            or (position.get("performance_source_ref") or "").strip()
        )
        evidence_note = (request.form.get("performance_evidence_note") or "").strip()
        if not source_ref or not evidence_note:
            return redirect(
                url_for(
                    "performance_view",
                    mode=mode,
                    performance_error="Informe a fonte e a justificativa da auditoria antes de concluir que o documento não está disponível.",
                )
            )

        def is_missing_positive_value(value: Any) -> bool:
            try:
                return not (float(value) > 0 and math.isfinite(float(value)))
            except (TypeError, ValueError):
                return True

        has_missing_contract_data = (
            is_missing_positive_value(position.get("contract_strike"))
            or not str(position.get("contract_expiry") or "").strip()
        )
        if not has_missing_contract_data:
            return redirect(
                url_for(
                    "performance_view",
                    mode=mode,
                    performance_error="Strike e vencimento já estão completos; capital de garantia deve ser declarado no campo próprio, não encerrado como falta documental.",
                )
            )

        with db_transaction() as conn:
            update_position(
                position_id=position_id,
                performance_source_ref=source_ref,
                performance_evidence_state="documents_exhausted",
                performance_evidence_note=evidence_note,
                conn=conn,
            )
        return redirect(
            url_for(
                "performance_view",
                mode=mode,
                performance_notice=f"Auditoria da posicao #{position_id} concluida sem documento para os campos pendentes.",
            )
        )

    @app.post("/performance/contract/<int:position_id>/reopen-evidence")
    def reopen_performance_evidence(position_id: int):
        position = get_position(position_id)
        mode = (request.form.get("mode") or "real").strip().lower()
        if mode not in {"real", "simulated"}:
            mode = "real"
        if not _is_short_strategy_performance_position(position):
            return redirect(
                url_for(
                    "performance_view",
                    mode=mode,
                    performance_error="Somente vendas de PUT/Call das estrategias podem receber auditoria de desempenho.",
                )
            )
        if bool(position.get("is_simulated") or 0) != (mode == "simulated"):
            return redirect(
                url_for(
                    "performance_view",
                    mode=mode,
                    performance_error="A posicao informada pertence a outro modo.",
                )
            )
        with db_transaction() as conn:
            update_position(
                position_id=position_id,
                performance_evidence_state="pending",
                conn=conn,
            )
        return redirect(
            url_for(
                "performance_view",
                mode=mode,
                performance_notice=f"Auditoria da posicao #{position_id} reaberta para nova evidência.",
            )
        )

    @app.post("/performance/wheel/cycles")
    def create_wheel_cycle_view():
        mode = (request.form.get("mode") or "real").strip().lower()
        if mode not in {"real", "simulated"}:
            mode = "real"
        try:
            cycle_id = create_wheel_cycle(
                underlying=(request.form.get("underlying") or ""),
                is_simulated=mode == "simulated",
                opened_at=(request.form.get("opened_at") or ""),
                source_ref=(request.form.get("source_ref") or ""),
                notes=(request.form.get("notes") or ""),
            )
        except WheelCycleError as exc:
            return redirect(url_for("performance_view", mode=mode, wheel_error=str(exc)))
        return redirect(
            url_for(
                "performance_view",
                mode=mode,
                wheel_notice=f"Ciclo Wheel #{cycle_id} criado. Vincule as pernas confirmadas abaixo.",
            )
        )

    @app.post("/performance/wheel/cycles/<int:cycle_id>/legs")
    def add_wheel_cycle_leg_view(cycle_id: int):
        mode = (request.form.get("mode") or "real").strip().lower()
        if mode not in {"real", "simulated"}:
            mode = "real"
        leg_type = (request.form.get("leg_type") or "").strip().lower()
        raw_position_id = (request.form.get("position_id") or "").strip()
        raw_holding_event_id = (request.form.get("holding_event_id") or "").strip()
        raw_quantity = (request.form.get("quantity") or "").strip()
        raw_amount = (request.form.get("amount_override") or "").strip()
        try:
            amount_override = _parse_form_float(raw_amount) if raw_amount else None
            add_wheel_cycle_leg(
                cycle_id=cycle_id,
                leg_type=leg_type,
                position_id=int(raw_position_id) if raw_position_id else None,
                holding_event_id=int(raw_holding_event_id) if raw_holding_event_id else None,
                quantity=int(raw_quantity) if raw_quantity else None,
                amount_override=amount_override,
                source_ref=(request.form.get("source_ref") or ""),
                notes=(request.form.get("notes") or ""),
            )
        except (ValueError, WheelCycleError) as exc:
            return redirect(url_for("performance_view", mode=mode, wheel_error=str(exc)))
        return redirect(
            url_for(
                "performance_view",
                mode=mode,
                wheel_notice=f"Perna adicionada ao ciclo Wheel #{cycle_id}.",
            )
        )

    @app.post("/positions/add")
    def add_position_view():
        form = request.form
        ticker = form.get("ticker", "").strip()
        underlying_input = form.get("underlying", "").strip()
        is_simulated = form.get("is_simulated") == "1"
        qty = int(form.get("qty", 0) or 0)
        entry_price = _parse_form_float(form.get("entry_price"))
        fees_input = form.get("fees")
        parent_raw = form.get("parent_position_id")
        parent_id = int(parent_raw) if parent_raw and parent_raw.strip() else None
        side_raw = (form.get("side") or "").strip()
        if not side_raw:
            # Se marcou prêmio, assume venda (short). Caso contrário, default long.
            side_raw = "short" if form.get("record_premium") == "1" else "long"
        strategy_tag_raw = form.get("strategy_tag") or None
        strategy_norm = (strategy_tag_raw or "").strip().lower()
        side_raw = _normalize_form_side(
            ticker=ticker,
            side=side_raw,
            strategy_tag=strategy_tag_raw,
            record_premium=form.get("record_premium") == "1"
            or strategy_norm == "cash_put",
        )
        trade_date = _parse_form_date(form.get("trade_date"))
        underlying = _resolve_underlying_for_position(
            ticker=ticker,
            underlying=underlying_input,
            side=side_raw,
            strategy_tag=strategy_tag_raw,
        )
        try:
            _validate_covered_call_stock(
                ticker=ticker,
                underlying=underlying,
                qty=qty,
                side=side_raw,
                strategy_tag=strategy_tag_raw,
                status="open",
                is_simulated=is_simulated,
            )
        except HoldingValidationError as exc:
            return redirect(
                url_for(
                    "covered_call",
                    underlying=exc.ticker or underlying or ticker,
                    holding_error=str(exc),
                )
            )
        try:
            _validate_covered_call_position_input(
                ticker=ticker,
                underlying=underlying,
                trade_date=trade_date,
                qty=qty,
                entry_price=entry_price,
                side=side_raw,
                strategy_tag=strategy_tag_raw,
                status="open",
                is_simulated=is_simulated,
            )
        except CoveredCallValidationError as exc:
            return redirect(
                url_for(
                    "covered_call",
                    underlying=underlying or ticker,
                    holding_error=str(exc),
                )
            )
        try:
            validate_cash_put_input(
                ticker=ticker,
                underlying=underlying,
                trade_date=trade_date,
                qty=qty,
                entry_price=entry_price,
                side=side_raw,
                strategy_tag=strategy_tag_raw,
                status="open",
            )
        except CashPutValidationError as exc:
            return redirect(url_for("positions", position_error=str(exc)))
        try:
            validate_ranking_option_input(
                ticker=ticker,
                underlying=underlying,
                trade_date=trade_date,
                qty=qty,
                entry_price=entry_price,
                side=side_raw,
                strategy_tag=strategy_tag_raw,
            )
        except RankingValidationError as exc:
            return redirect(
                url_for("positions", strategy_tag="ranking", position_error=str(exc))
            )
        if fees_input:
            fees = _parse_form_float(fees_input)
        else:
            fees = _auto_fees(
                ticker=ticker,
                underlying=underlying or ticker,
                qty=qty,
                entry_price=entry_price,
            )

        try:
            performance_contract = _build_new_position_performance_contract(
                form=form,
                ticker=ticker,
                underlying=underlying,
                qty=qty,
                side=side_raw,
                strategy_tag=strategy_tag_raw,
                is_simulated=is_simulated,
            )
        except ValueError as exc:
            if strategy_norm == "covered_call":
                return redirect(
                    url_for(
                        "covered_call",
                        underlying=underlying or ticker,
                        holding_error=str(exc),
                    )
                )
            return redirect(url_for("positions", position_error=str(exc)))

        def _insert_position_and_optional_premium(conn: Any = None) -> int:
            pos_id_inner = add_position(
                ticker=ticker,
                underlying=underlying,
                trade_date=trade_date or form.get("trade_date", ""),
                qty=qty,
                entry_price=entry_price,
                fees=fees,
                trade_type=form.get("trade_type", "swing"),
                side=side_raw,
                irrf=float(form["irrf"]) if form.get("irrf") else None,
                notes=form.get("notes") or None,
                is_simulated=is_simulated,
                parent_position_id=parent_id,
                strategy_tag=strategy_tag_raw,
                **performance_contract,
                conn=conn,
            )

            # Registro opcional: prêmio no caixa (venda) + provisão DARF (saldo limpo).
            if (
                entry_price > 0
                and qty > 0
                and (form.get("record_premium") == "1" or strategy_norm == "cash_put")
            ):
                t = (ticker or "").strip().upper()
                is_option = _is_option_ticker(t)

                if is_option:
                    total_premium = finance.calculate_option_premium(
                        entry_price=entry_price,
                        qty=qty,
                        fees=fees,
                    )
                    finance.add_transaction(
                        date=trade_date or form.get("trade_date", ""),
                        type=finance.TransactionType.PREMIUM,
                        amount=total_premium,
                        description=f"Prêmio {ticker} ({qty}x)",
                        position_id=pos_id_inner,
                        is_simulated=is_simulated,
                        conn=conn,
                    )

                    if form.get("reserve_darf") == "1" or strategy_norm == "cash_put":
                        trade_type = (form.get("trade_type") or "swing").strip().lower()
                        darf_amount = finance.calculate_darf_provision(
                            premium_amount=total_premium,
                            trade_type=trade_type,
                        )
                        if darf_amount != 0.0:
                            aliquota_opts = finance.option_tax_rate(trade_type)
                            finance.add_transaction(
                                date=trade_date or form.get("trade_date", ""),
                                type=finance.TransactionType.DARF,
                                amount=darf_amount,
                                description=f"Provisão DARF {ticker} ({int(aliquota_opts*100)}%)",
                                position_id=pos_id_inner,
                                is_simulated=is_simulated,
                                conn=conn,
                            )
            if (
                strategy_norm == "ranking"
                and _is_option_ticker(ticker)
                and side_raw == "long"
            ):
                finance.sync_long_option_entry_buy(
                    position_id=pos_id_inner,
                    ticker=ticker,
                    trade_date=trade_date or form.get("trade_date", ""),
                    qty=qty,
                    entry_price=entry_price,
                    fees=fees,
                    side=side_raw,
                    strategy_tag=strategy_tag_raw,
                    is_simulated=is_simulated,
                    conn=conn,
                )
            return pos_id_inner

        if strategy_norm in {"cash_put", "covered_call", "ranking"}:
            with db_transaction() as conn:
                _insert_position_and_optional_premium(conn)
        else:
            _insert_position_and_optional_premium()

        return redirect(_safe_next_url(form.get("next")) or url_for("positions"))

    @app.post("/positions/register-premium/<int:position_id>")
    def register_position_premium(position_id: int):
        next_url = _safe_next_url(request.form.get("next")) or url_for("positions")
        pos = get_position(position_id)
        if not pos:
            return redirect(next_url)

        ticker = (pos.get("ticker") or "").strip()
        underlying = (pos.get("underlying") or "").strip()
        if not underlying:
            underlying = _lookup_underlying_from_snapshot(ticker) or ""
        if not ticker or not _is_option_ticker(ticker):
            return redirect(next_url)

        side = (pos.get("side") or "").strip().lower()
        if side != "short":
            return redirect(next_url)

        try:
            entry_price = float(pos.get("entry_price") or 0.0)
        except (TypeError, ValueError):
            entry_price = 0.0
        try:
            qty = int(pos.get("qty") or 0)
        except (TypeError, ValueError):
            qty = 0
        if entry_price <= 0 or qty <= 0:
            return redirect(next_url)

        if finance.has_position_premium(position_id):
            return redirect(next_url)

        try:
            fees = float(pos.get("fees") or 0.0)
        except (TypeError, ValueError):
            fees = 0.0

        total_premium = finance.calculate_option_premium(
            entry_price=entry_price,
            qty=qty,
            fees=fees,
        )
        if total_premium <= 0:
            return redirect(next_url)

        trade_date = pos.get("trade_date") or datetime.date.today().isoformat()
        is_simulated = bool(pos.get("is_simulated") or 0)

        finance.add_transaction(
            date=trade_date,
            type=finance.TransactionType.PREMIUM,
            amount=total_premium,
            description=f"Prêmio {ticker} ({qty}x)",
            position_id=position_id,
            is_simulated=is_simulated,
        )

        reserve_darf = request.form.get("reserve_darf", "1") == "1"
        if reserve_darf:
            trade_type = (pos.get("trade_type") or "swing").strip().lower()
            darf_amount = finance.calculate_darf_provision(
                premium_amount=total_premium,
                trade_type=trade_type,
            )
            if darf_amount != 0.0:
                aliquota_opts = finance.option_tax_rate(trade_type)
                finance.add_transaction(
                    date=trade_date,
                    type=finance.TransactionType.DARF,
                    amount=darf_amount,
                    description=f"Provisão DARF {ticker} ({int(aliquota_opts*100)}%)",
                    position_id=position_id,
                    is_simulated=is_simulated,
                )

        return redirect(next_url)

    @app.post("/positions/recalc-premium/<int:position_id>")
    def recalc_position_premium(position_id: int):
        next_url = _safe_next_url(request.form.get("next")) or url_for("positions")
        pos = get_position(position_id)
        if not pos:
            return redirect(next_url)

        ticker = (pos.get("ticker") or "").strip()
        if not ticker or not _is_option_ticker(ticker):
            return redirect(next_url)

        side = (pos.get("side") or "").strip().lower()
        if side != "short":
            return redirect(next_url)

        try:
            entry_price = float(pos.get("entry_price") or 0.0)
        except (TypeError, ValueError):
            entry_price = 0.0
        try:
            qty = int(pos.get("qty") or 0)
        except (TypeError, ValueError):
            qty = 0
        try:
            fees = float(pos.get("fees") or 0.0)
        except (TypeError, ValueError):
            fees = 0.0

        if entry_price <= 0 or qty <= 0:
            return redirect(next_url)

        total_premium = finance.calculate_option_premium(
            entry_price=entry_price,
            qty=qty,
            fees=fees,
        )
        trade_date = pos.get("trade_date") or datetime.date.today().isoformat()
        trade_type = (pos.get("trade_type") or "swing").strip().lower()
        is_simulated = bool(pos.get("is_simulated") or 0)

        finance.recalc_position_premium_and_darf(
            position_id=position_id,
            trade_date=trade_date,
            ticker=ticker,
            qty=qty,
            premium_amount=total_premium,
            trade_type=trade_type,
            is_simulated=is_simulated,
        )
        return redirect(next_url)

    @app.post("/positions/update/<int:position_id>")
    def update_position_view(position_id: int):
        form = request.form
        persisted_pos = get_position(position_id)
        if not persisted_pos:
            return redirect(_safe_next_url(form.get("next")) or url_for("positions"))
        status = (form.get("status") or "").strip() or None
        ticker = (form.get("ticker") or "").strip()
        side_raw = form.get("side") or None
        strategy_tag_raw = form.get("strategy_tag") or None
        strategy_norm = (strategy_tag_raw or "").strip().lower()
        side_raw = _normalize_form_side(
            ticker=ticker,
            side=side_raw,
            strategy_tag=strategy_tag_raw,
            record_premium=strategy_norm == "cash_put",
        )
        trade_date = _parse_form_date(form.get("trade_date"))
        underlying = _resolve_underlying_for_position(
            ticker=ticker,
            underlying=form.get("underlying") or "",
            side=side_raw,
            strategy_tag=strategy_tag_raw,
        )
        is_simulated = None
        if form.get("is_simulated") is not None:
            is_simulated = form.get("is_simulated") == "1"
        parent_id = None
        if form.get("parent_position_id"):
            try:
                parent_id = int(form.get("parent_position_id"))
            except ValueError:
                parent_id = None
        exit_date = (form.get("exit_date") or "").strip() or None
        exit_price = (
            _parse_form_float(form.get("exit_price"))
            if form.get("exit_price")
            else None
        )
        partial_date = (form.get("partial_date") or "").strip() or None
        partial_price = (
            _parse_form_float(form.get("partial_price"))
            if form.get("partial_price")
            else None
        )
        partial_qty = int(form["partial_qty"]) if form.get("partial_qty") else None
        exit_reason = (form.get("exit_reason") or "").strip() or None
        if status == "open":
            exit_date = None
            exit_price = None
            exit_reason = None
        proposed_identity = {
            "ticker": ticker,
            "underlying": underlying,
            "trade_date": trade_date or form.get("trade_date") or None,
            "qty": int(form["qty"]) if form.get("qty") else None,
            "entry_price": (
                _parse_form_float(form.get("entry_price"))
                if form.get("entry_price")
                else None
            ),
            "trade_type": form.get("trade_type") or None,
            "side": side_raw,
            "strategy_tag": (strategy_tag_raw or "").strip() or None,
            "is_simulated": is_simulated,
            "parent_position_id": parent_id,
        }
        try:
            validate_position_identity_update(
                existing=persisted_pos,
                proposed=proposed_identity,
            )
            validate_position_closure_update(
                existing=persisted_pos,
                proposed={
                    "status": status,
                    "exit_reason": exit_reason,
                },
            )
        except StrategyContractError as exc:
            return redirect(
                url_for(
                    "positions",
                    strategy_tag=(persisted_pos.get("strategy_tag") or "").strip(),
                    position_error=str(exc),
                )
            )
        try:
            validate_cash_put_input(
                ticker=ticker,
                underlying=underlying,
                trade_date=trade_date,
                qty=int(form["qty"]) if form.get("qty") else 0,
                entry_price=(
                    _parse_form_float(form.get("entry_price"))
                    if form.get("entry_price")
                    else 0.0
                ),
                side=side_raw,
                strategy_tag=strategy_tag_raw,
                status=status or "open",
                exit_date=exit_date,
                exit_price=exit_price,
                exit_reason=exit_reason,
            )
        except CashPutValidationError as exc:
            return redirect(
                url_for(
                    "positions",
                    strategy_tag="cash_put",
                    position_error=str(exc),
                )
            )
        try:
            validate_ranking_option_input(
                ticker=ticker,
                underlying=underlying,
                trade_date=trade_date,
                qty=int(form["qty"]) if form.get("qty") else 0,
                entry_price=(
                    _parse_form_float(form.get("entry_price"))
                    if form.get("entry_price")
                    else 0.0
                ),
                side=side_raw,
                strategy_tag=strategy_tag_raw,
            )
        except RankingValidationError as exc:
            return redirect(
                url_for(
                    "positions",
                    strategy_tag="ranking",
                    position_error=str(exc),
                )
            )
        try:
            _validate_covered_call_stock(
                ticker=ticker,
                underlying=underlying,
                qty=int(form["qty"]) if form.get("qty") else 0,
                side=side_raw,
                strategy_tag=strategy_tag_raw,
                status=status or "open",
                is_simulated=(
                    form.get("is_simulated") == "1"
                    if form.get("is_simulated") is not None
                    else bool((persisted_pos or {}).get("is_simulated") or 0)
                ),
                current_position_id=position_id,
            )
        except HoldingValidationError as exc:
            return redirect(
                url_for(
                    "covered_call",
                    underlying=exc.ticker or underlying or ticker,
                    holding_error=str(exc),
                )
            )
        try:
            _validate_covered_call_position_input(
                ticker=ticker,
                underlying=underlying,
                trade_date=trade_date,
                qty=int(form["qty"]) if form.get("qty") else 0,
                entry_price=(
                    _parse_form_float(form.get("entry_price"))
                    if form.get("entry_price")
                    else 0.0
                ),
                side=side_raw,
                strategy_tag=strategy_tag_raw,
                status=status or "open",
                exit_date=exit_date,
                exit_price=exit_price,
                exit_reason=exit_reason,
                is_simulated=(
                    form.get("is_simulated") == "1"
                    if form.get("is_simulated") is not None
                    else bool((persisted_pos or {}).get("is_simulated") or 0)
                ),
                current_position_id=position_id,
            )
        except CoveredCallValidationError as exc:
            return redirect(
                url_for(
                    "covered_call",
                    underlying=underlying or ticker,
                    holding_error=str(exc),
                )
            )
        update_position(
            position_id=position_id,
            ticker=ticker or None,
            underlying=underlying,
            trade_date=trade_date or form.get("trade_date") or None,
            qty=int(form["qty"]) if form.get("qty") else None,
            entry_price=(
                _parse_form_float(form.get("entry_price"))
                if form.get("entry_price")
                else None
            ),
            fees=_parse_form_float(form.get("fees")) if form.get("fees") else None,
            status=status,
            exit_date=exit_date,
            exit_price=exit_price,
            notes=(form.get("notes") or "").strip() or None,
            trade_type=form.get("trade_type") or None,
            side=side_raw,
            irrf=_parse_form_float(form.get("irrf")) if form.get("irrf") else None,
            partial_date=partial_date,
            partial_price=partial_price,
            partial_qty=partial_qty,
            exit_reason=exit_reason,
            is_simulated=is_simulated,
            parent_position_id=parent_id,
            strategy_tag=(strategy_tag_raw or "").strip() or None,
        )
        finance.sync_position_closure_effects(position_id=position_id)
        return redirect(_safe_next_url(form.get("next")) or url_for("positions"))

    @app.post("/holdings/upsert")
    def upsert_holding_view():
        form = request.form
        ticker = _resolve_underlying_for_position(
            ticker=form.get("ticker") or form.get("underlying") or "",
            underlying=form.get("underlying") or form.get("ticker") or "",
        )
        next_url = _safe_next_url(form.get("next"))
        try:
            quantity = int(form.get("quantity") or 0)
        except (TypeError, ValueError):
            quantity = -1
        avg_price = _parse_form_float(form.get("avg_price"))
        is_simulated = form.get("is_simulated") == "1"
        notes = (form.get("notes") or "").strip() or None
        event_date = (
            _parse_form_date(form.get("event_date"))
            or datetime.date.today().isoformat()
        )
        try:
            snapshot = upsert_holding(
                ticker=ticker,
                quantity=quantity,
                avg_price=avg_price,
                is_simulated=is_simulated,
                notes=notes,
                event_date=event_date,
            )
        except HoldingValidationError as exc:
            if next_url:
                return redirect(
                    _url_with_query(
                        next_url,
                        holding_error=str(exc),
                    )
                )
            return redirect(
                url_for(
                    "covered_call",
                    underlying=exc.ticker or ticker,
                    holding_error=str(exc),
                )
            )
        mode_label = "simulado" if is_simulated else "real"
        avg_display = (
            float(snapshot.get("avg_price") or 0.0)
            if int(snapshot.get("shares_total") or 0) > 0
            else 0.0
        )
        notice = (
            f"Estoque consolidado {mode_label} de {ticker} salvo: "
            f"{int(snapshot.get('shares_total') or 0)} acoes a PM R$ {avg_display:.2f}."
        )
        if next_url:
            return redirect(
                _url_with_query(
                    next_url,
                    holding_notice=notice,
                )
            )
        return redirect(
            url_for(
                "covered_call",
                underlying=ticker,
                holding_notice=notice,
            )
        )

    @app.post("/positions/delete/<int:position_id>")
    def delete_position_view(position_id: int):
        delete_position(position_id=position_id)
        return redirect(
            _safe_next_url(request.form.get("next")) or url_for("positions")
        )

    def _parse_form_float(value: str | None) -> float:
        if not value:
            return 0.0
        text = value.strip().replace("%", "").replace(",", ".")
        if not text:
            return 0.0
        try:
            return float(text)
        except ValueError:
            return 0.0

    def _parse_form_date(value: str | None) -> str | None:
        if not value:
            return None
        text = value.strip()
        if not text:
            return None
        # Aceita ISO (YYYY-MM-DD)
        try:
            return datetime.date.fromisoformat(text).isoformat()
        except ValueError:
            pass
        # Aceita dd/mm/YYYY (vencimento da B3 no snapshot)
        try:
            return datetime.datetime.strptime(text, "%d/%m/%Y").date().isoformat()
        except ValueError:
            return None

    def _parse_required_positive_currency(value: str | None, *, label: str) -> float:
        parsed = _parse_form_float(value)
        if parsed <= 0 or not math.isfinite(parsed):
            raise ValueError(f"{label} deve ser maior que zero.")
        return parsed

    def _parse_optional_positive_int(value: str | None) -> int | None:
        text = (value or "").strip()
        if not text:
            return None
        try:
            parsed = int(text)
        except ValueError:
            return None
        return parsed if parsed > 0 else None

    def _is_short_strategy_performance_position(position: dict[str, Any] | None) -> bool:
        if not position:
            return False
        return (
            (position.get("strategy_tag") or "").strip().lower() in STRATEGIES
            and (position.get("side") or "").strip().lower() == "short"
            and _is_option_ticker(position.get("ticker"))
        )

    def _is_call_exercise_position(position: dict[str, Any]) -> bool:
        return (
            (position.get("strategy_tag") or "").strip().lower() == "covered_call"
            and infer_option_type(position.get("ticker") or "") == "CALL"
            and (position.get("status") or "").strip().lower() == "closed"
            and "exerc" in (position.get("exit_reason") or "").strip().lower()
        )

    def _is_matching_exercised_call_stock(
        call_position: dict[str, Any], stock_position: dict[str, Any] | None
    ) -> bool:
        if not stock_position:
            return False
        return (
            not _is_option_ticker(stock_position.get("ticker"))
            and (stock_position.get("strategy_tag") or "").strip().lower()
            == "covered_call"
            and (stock_position.get("underlying") or "").strip().upper()
            == (call_position.get("underlying") or "").strip().upper()
            and bool(stock_position.get("is_simulated") or 0)
            == bool(call_position.get("is_simulated") or 0)
            and int(stock_position.get("qty") or 0)
            == int(call_position.get("qty") or 0)
            and (stock_position.get("status") or "").strip().lower() == "closed"
            and "exerc" in (stock_position.get("exit_reason") or "").strip().lower()
        )

    def _lookup_underlying_from_snapshot(ticker: str) -> str | None:
        if not ticker:
            return None
        t = ticker.strip().upper()
        row = fetch_latest_option_snapshot(t)
        if not row:
            return None
        return str(row.get("underlying") or "").strip().upper() or None

    def _safe_next_url(value: str | None) -> str | None:
        if not value:
            return None
        candidate = value.strip()
        if not candidate.startswith("/positions"):
            return None
        return candidate

    def _url_with_query(base_url: str, **params: str) -> str:
        parts = urlsplit(base_url)
        query = dict(parse_qsl(parts.query, keep_blank_values=True))
        for key, value in params.items():
            if value:
                query[key] = value
        return urlunsplit(
            (
                "",
                "",
                parts.path or "/positions",
                urlencode(query),
                "",
            )
        )

    def _is_option_ticker(ticker: str | None) -> bool:
        return infer_option_type(ticker or "") in {"CALL", "PUT"}

    def _normalize_form_side(
        *,
        ticker: str | None,
        side: str | None,
        strategy_tag: str | None,
        record_premium: bool = False,
    ) -> str:
        side_norm = (side or "").strip().lower()
        if side_norm in {"short", "vendida", "vendido", "v"}:
            return "short"
        strategy_norm = (strategy_tag or "").strip().lower()
        if record_premium:
            return "short"
        if strategy_norm in {"cash_put", "covered_call"} and _is_option_ticker(ticker):
            return "short"
        return "long"

    def _looks_like_equity_ticker(ticker: str | None) -> bool:
        text = (ticker or "").strip().upper()
        if not text:
            return False
        return re.fullmatch(r"[A-Z]{4}\d{1,2}", text) is not None

    def _resolve_underlying_for_position(
        *,
        ticker: str | None,
        underlying: str | None,
        side: str | None = None,
        strategy_tag: str | None = None,
    ) -> str:
        t = (ticker or "").strip().upper()
        u = (underlying or "").strip().upper()
        if u:
            return u

        snap_underlying = _lookup_underlying_from_snapshot(t)
        if snap_underlying:
            return snap_underlying.strip().upper()

        side_norm = (side or "").strip().lower()
        strat_norm = (strategy_tag or "").strip().lower()
        # Fallback para ações em estoque: quando o usuário não informar "Ativo",
        # usamos o próprio ticker da ação.
        if (
            t
            and _looks_like_equity_ticker(t)
            and side_norm != "short"
            and strat_norm not in {"cash_put", "covered_call", "ranking"}
        ):
            return t
        return u

    def _lookup_option_strike(ticker: str) -> float | None:
        """Recupera o strike do ticker de opção a partir do último snapshot."""

        if not ticker:
            return None
        t = ticker.strip().upper()
        row = fetch_latest_option_snapshot(t)
        if not row:
            return None
        return float(parse_ptbr_number(row.get("last_strike")) or 0.0)

    def _build_new_position_performance_contract(
        *,
        form: Any,
        ticker: str,
        underlying: str,
        qty: int,
        side: str,
        strategy_tag: str | None,
        is_simulated: bool,
    ) -> dict[str, Any]:
        """Preserva o contrato e o capital no instante da venda da estrategia."""

        strategy = (strategy_tag or "").strip().lower()
        if (
            strategy not in STRATEGIES
            or side.strip().lower() != "short"
            or not _is_option_ticker(ticker)
        ):
            return {}

        if strategy == "covered_call" and form.get("record_premium") != "1":
            raise ValueError(
                "Covered Call exige registrar o premio no caixa; uma venda sem premio impede a apuracao auditavel."
            )

        manual_strike = _parse_form_float(form.get("contract_strike"))
        manual_expiry = _parse_form_date(form.get("contract_expiry"))
        source_ref = (form.get("performance_source_ref") or "").strip()
        snapshot = fetch_latest_option_snapshot(ticker)
        snapshot_strike = (
            float(parse_ptbr_number(snapshot.get("last_strike")) or 0.0)
            if snapshot
            else 0.0
        )
        snapshot_expiry = (
            _parse_form_date(str(snapshot.get("last_vencimento") or ""))
            if snapshot
            else None
        )
        strike = manual_strike if manual_strike > 0 else snapshot_strike
        expiry = manual_expiry or snapshot_expiry
        if strike <= 0 or not expiry:
            raise ValueError(
                "Informe strike e vencimento da nota. Sem esses dados o sistema nao cadastra a estrategia."
            )

        if strategy == "cash_put":
            capital = strike * int(qty or 0)
            capital_source = "strike_x_quantidade"
        else:
            holding = get_holding_snapshot(
                ticker=underlying,
                is_simulated=is_simulated,
            )
            avg_price = float(holding.get("avg_price") or 0.0)
            if holding.get("price_status") != "ok" or avg_price <= 0:
                raise ValueError(
                    "O preco medio do estoque consolidado precisa estar confirmado antes de vender Covered Call."
                )
            capital = avg_price * int(qty or 0)
            capital_source = "preco_medio_estoque_no_cadastro"

        if not source_ref:
            if snapshot and snapshot.get("snapshot_date"):
                source_ref = f"snapshot:{snapshot['snapshot_date']}"
            else:
                raise ValueError(
                    "Sem snapshot, informe a referencia da nota de corretagem do contrato."
                )
        return {
            "contract_strike": strike,
            "contract_expiry": expiry,
            "capital_committed": capital,
            "capital_source": capital_source,
            "performance_source_ref": source_ref,
        }

    def _is_inventory_reserved_call(pos: dict[str, Any]) -> bool:
        ticker = (pos.get("ticker") or "").strip().upper()
        underlying = (pos.get("underlying") or "").strip().upper()
        if not ticker or not underlying:
            return False
        if infer_option_type(ticker) != "CALL":
            return False
        if (pos.get("side") or "").strip().lower() != "short":
            return False
        if (pos.get("strategy_tag") or "").strip().lower() != "covered_call":
            return False
        return True

    def _validate_covered_call_stock(
        *,
        ticker: str,
        underlying: str,
        qty: int,
        side: str | None,
        strategy_tag: str | None,
        status: str | None,
        is_simulated: bool,
        current_position_id: int | None = None,
    ) -> None:
        if (status or "open").strip().lower() != "open":
            return
        if (side or "").strip().lower() != "short":
            return
        if (strategy_tag or "").strip().lower() != "covered_call":
            return
        if infer_option_type(ticker or "") != "CALL":
            return

        normalized_underlying = (underlying or "").strip().upper()
        if not normalized_underlying:
            raise HoldingValidationError(
                "Nao foi possivel identificar o ativo-base da covered call.",
                ticker=normalized_underlying or None,
            )
        validate_covered_call_availability(
            ticker=normalized_underlying,
            qty=int(qty or 0),
            is_simulated=is_simulated,
            exclude_position_id=current_position_id,
        )

    def _validate_covered_call_position_input(
        *,
        ticker: str,
        underlying: str,
        trade_date: str | None,
        qty: int,
        entry_price: float,
        side: str | None,
        strategy_tag: str | None,
        status: str | None,
        is_simulated: bool,
        exit_date: str | None = None,
        exit_price: float | None = None,
        exit_reason: str | None = None,
        current_position_id: int | None = None,
    ) -> None:
        validate_covered_call_input(
            ticker=ticker,
            underlying=underlying,
            trade_date=trade_date,
            qty=qty,
            entry_price=entry_price,
            side=side,
            strategy_tag=strategy_tag,
            status=status or "open",
            exit_date=exit_date,
            exit_price=exit_price,
            exit_reason=exit_reason,
        )
        candidate = {
            "ticker": ticker,
            "underlying": underlying,
            "trade_date": trade_date,
            "qty": qty,
            "entry_price": entry_price,
            "side": side,
            "strategy_tag": strategy_tag,
            "is_simulated": 1 if is_simulated else 0,
        }
        duplicate = find_duplicate_covered_call(
            list_positions(include_closed=True),
            candidate=candidate,
            current_position_id=current_position_id,
        )
        if duplicate is not None:
            raise CoveredCallValidationError(
                (
                    "Ja existe uma covered_call com mesmo ticker, data, quantidade e preco "
                    f"(posicao #{duplicate.get('id')}). Revise a posicao existente antes de salvar."
                )
            )

    def _auto_fees(
        *,
        ticker: str,
        underlying: str,
        qty: int,
        entry_price: float,
    ) -> float:
        """Calcula taxas padrão a partir das configurações, se possível."""

        fees_cfg: FeeSettings = get_fee_settings()
        t = (ticker or "").strip().upper()
        u = (underlying or "").strip().upper()
        qty = max(int(qty or 0), 0)
        entry_price = float(entry_price or 0.0)

        if not t or qty <= 0 or entry_price <= 0:
            return 0.0

        # Se ticker == underlying, tratamos como ação/ETF.
        if u and t == u:
            value = entry_price * qty
            return max(
                0.0,
                float(fees_cfg.equity_fixed)
                + (float(fees_cfg.equity_percent) / 100.0) * value,
            )

        # Caso contrário, usamos regra de opções.
        strike = _lookup_option_strike(t)
        if not strike or strike <= 0:
            # Sem strike conhecido, pelo menos aplicamos a parte fixa.
            return max(0.0, float(fees_cfg.option_fixed))
        # Interpretação: qty = número de opções (mesmo número de ações expostas).
        # Valor nocional aproximado = strike * qty.
        notional = strike * qty
        return max(
            0.0,
            float(fees_cfg.option_fixed)
            + (float(fees_cfg.option_percent_notional) / 100.0) * notional,
        )

    return app


if __name__ == "__main__":
    load_dotenv_once()
    app = create_app()
    debug_mode = os.getenv("OPCOES_WEB_DEBUG", "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
        "sim",
    }
    app.run(debug=debug_mode)
