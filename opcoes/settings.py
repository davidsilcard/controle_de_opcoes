from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from typing import Dict

from .config import (
    get_data_backend,
    get_db_path,
    get_postgres_schema,
    is_postgres_strict_mode,
)
from .db_health import resolve_postgres_target


@dataclass
class FeeSettings:
    equity_fixed: float = 0.0
    equity_percent: float = 0.0  # em % sobre o valor da operação
    option_fixed: float = 0.0
    option_percent_notional: float = 0.0  # em % sobre (strike * 100 * contratos)


@dataclass
class StrategySettings:
    min_score: int = 8
    limit_opportunities: int = 30
    recurring_days: int = 30


@dataclass
class RankingViewSettings:
    recurring_limit: int = 15
    underlying_filter: str = ""
    option_type_filter: str = ""


@dataclass
class CashCoveredPutSettings:
    underlying: str = "PETR4"
    min_yield_pct: float = 1.0
    min_buffer_pct: float = 5.0
    min_days: int = 7
    max_days: int = 120
    contract_size: int = 100
    limit: int = 50
    cash_mode: str = "real"
    buyback_target_pct: float = 50.0


@dataclass
class CoveredCallSettings:
    underlying: str = "CMIG4"
    min_extrinsic: float = 2.0
    min_days: int = 30
    max_days: int = 200
    min_dist_strike: float = 1.0
    buyback_target_pct: float = 50.0
    only_target_hits: bool = False


@dataclass
class FundamentusSettings:
    target_yield_pct: float = 8.0
    put_distance_limit_pct: float = 15.0
    put_min_premium_pct: float = 0.5
    put_target_monthly_yield_pct: float = 1.0
    put_min_score: float = 4.0


def _sqlite_timeout_seconds() -> float:
    raw = os.getenv("OPCOES_SQLITE_TIMEOUT_SECONDS", "30").strip()
    try:
        value = float(raw)
    except ValueError:
        value = 30.0
    if value <= 0:
        value = 30.0
    return value


def _quote_ident(value: str) -> str:
    return '"' + str(value).replace('"', '""') + '"'


def _connect_sqlite(*, ensure_table: bool = False) -> sqlite3.Connection:
    db_path = get_db_path()
    timeout_seconds = _sqlite_timeout_seconds()
    conn = sqlite3.connect(db_path, timeout=timeout_seconds)
    conn.row_factory = sqlite3.Row
    conn.execute(f"PRAGMA busy_timeout = {int(timeout_seconds * 1000)}")
    if ensure_table:
        _ensure_table_sqlite(conn)
    return conn


def _connect_postgres(*, ensure_table: bool = False):
    target, errors = resolve_postgres_target()
    if target is None:
        reasons = "; ".join(errors) if errors else "configuração ausente"
        raise RuntimeError(f"PostgreSQL não configurado: {reasons}")

    try:
        import psycopg
    except Exception as exc:
        raise RuntimeError(
            "Driver psycopg não encontrado. Instale com: uv add psycopg[binary]"
        ) from exc

    schema = get_postgres_schema()
    conn = psycopg.connect(target.dsn)
    with conn.cursor() as cur:
        cur.execute(f"SET search_path TO {_quote_ident(schema)}")
    if ensure_table:
        _ensure_table_postgres(conn)
    return conn


def _ensure_table_sqlite(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
        """
    )
    conn.commit()


def _ensure_table_postgres(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
            """
        )
    conn.commit()


def _load_raw_settings_sqlite() -> Dict[str, str]:
    conn = _connect_sqlite()
    try:
        try:
            rows = conn.execute("SELECT key, value FROM settings").fetchall()
        except sqlite3.OperationalError as exc:
            if "no such table: settings" in str(exc):
                return {}
            raise
    finally:
        conn.close()
    return {str(r["key"]): str(r["value"]) for r in rows}


def _load_raw_settings_postgres() -> Dict[str, str]:
    conn = _connect_postgres()
    try:
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT key, value FROM settings")
                rows = cur.fetchall()
        except Exception as exc:
            if 'relation "settings" does not exist' in str(exc):
                return {}
            raise
    finally:
        conn.close()
    return {str(r[0]): str(r[1]) for r in rows}


def _load_raw_settings() -> Dict[str, str]:
    if get_data_backend() == "postgres":
        try:
            return _load_raw_settings_postgres()
        except Exception:
            if is_postgres_strict_mode():
                raise
            return _load_raw_settings_sqlite()
    return _load_raw_settings_sqlite()


def _upsert_settings_sqlite(params: Dict[str, object]) -> None:
    conn = _connect_sqlite(ensure_table=True)
    try:
        for key, value in params.items():
            conn.execute(
                """
                INSERT INTO settings (key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, str(value)),
            )
        conn.commit()
    finally:
        conn.close()


def _upsert_settings_postgres(params: Dict[str, object]) -> None:
    conn = _connect_postgres(ensure_table=True)
    try:
        with conn.cursor() as cur:
            for key, value in params.items():
                cur.execute(
                    """
                    INSERT INTO settings (key, value)
                    VALUES (%s, %s)
                    ON CONFLICT(key) DO UPDATE SET value = EXCLUDED.value
                    """,
                    (key, str(value)),
                )
        conn.commit()
    finally:
        conn.close()


def _upsert_settings(params: Dict[str, object]) -> None:
    if get_data_backend() == "postgres":
        try:
            _upsert_settings_postgres(params)
            return
        except Exception:
            if is_postgres_strict_mode():
                raise
            _upsert_settings_sqlite(params)
            return
    _upsert_settings_sqlite(params)


def get_fee_settings() -> FeeSettings:
    """Carrega configuração de taxas. Se não existir, retorna zeros."""

    raw = _load_raw_settings()

    def _parse(name: str) -> float:
        text = raw.get(name, "").strip()
        if not text:
            return 0.0
        # aceita vírgula ou ponto
        text = text.replace("%", "").replace(",", ".")
        try:
            return float(text)
        except ValueError:
            return 0.0

    return FeeSettings(
        equity_fixed=_parse("fee_equity_fixed"),
        equity_percent=_parse("fee_equity_percent"),
        option_fixed=_parse("fee_option_fixed"),
        option_percent_notional=_parse("fee_option_percent_notional"),
    )


def get_strategy_settings() -> StrategySettings:
    raw = _load_raw_settings()

    def _parse_int(name: str, default: int) -> int:
        text = raw.get(name, "").strip()
        if not text:
            return default
        try:
            return int(text)
        except ValueError:
            return default

    return StrategySettings(
        min_score=_parse_int("strat_min_score", 8),
        limit_opportunities=_parse_int("strat_limit_opportunities", 30),
        recurring_days=_parse_int("strat_recurring_days", 30),
    )


def get_ranking_view_settings() -> RankingViewSettings:
    raw = _load_raw_settings()

    def _parse_int(name: str, default: int) -> int:
        text = raw.get(name, "").strip()
        if not text:
            return default
        try:
            return int(text)
        except ValueError:
            return default

    option_type_filter = raw.get("rank_option_type_filter", "").strip().upper()
    if option_type_filter not in {"CALL", "PUT"}:
        option_type_filter = ""

    return RankingViewSettings(
        recurring_limit=_parse_int("rank_recurring_limit", 15),
        underlying_filter=raw.get("rank_underlying_filter", "").strip().upper(),
        option_type_filter=option_type_filter,
    )


def get_cash_put_settings() -> CashCoveredPutSettings:
    raw = _load_raw_settings()

    def _parse_float(name: str, default: float) -> float:
        text = raw.get(name, "").strip()
        if not text:
            return default
        text = text.replace("%", "").replace(",", ".")
        try:
            return float(text)
        except ValueError:
            return default

    def _parse_int(name: str, default: int) -> int:
        text = raw.get(name, "").strip()
        if not text:
            return default
        try:
            return int(text)
        except ValueError:
            return default

    underlying = raw.get("cash_put_underlying", "").strip().upper() or "PETR4"
    cash_mode = raw.get("cash_put_cash_mode", "real").strip().lower() or "real"

    return CashCoveredPutSettings(
        underlying=underlying,
        min_yield_pct=_parse_float("cash_put_min_yield_pct", 1.0),
        min_buffer_pct=_parse_float("cash_put_min_buffer_pct", 5.0),
        min_days=_parse_int("cash_put_min_days", 7),
        max_days=_parse_int("cash_put_max_days", 120),
        contract_size=_parse_int("cash_put_contract_size", 100),
        limit=_parse_int("cash_put_limit", 50),
        cash_mode=cash_mode,
        buyback_target_pct=_parse_float("cash_put_buyback_target_pct", 50.0),
    )


def get_covered_call_settings() -> CoveredCallSettings:
    raw = _load_raw_settings()

    def _parse_float(name: str, default: float) -> float:
        text = raw.get(name, "").strip()
        if not text:
            return default
        text = text.replace("%", "").replace(",", ".")
        try:
            return float(text)
        except ValueError:
            return default

    def _parse_int(name: str, default: int) -> int:
        text = raw.get(name, "").strip()
        if not text:
            return default
        try:
            return int(text)
        except ValueError:
            return default

    def _parse_bool(name: str, default: bool) -> bool:
        text = raw.get(name, "").strip().lower()
        if not text:
            return default
        if text in {"1", "true", "yes", "on", "sim"}:
            return True
        if text in {"0", "false", "no", "off", "nao", "não"}:
            return False
        return default

    underlying = raw.get("ccall_underlying", "").strip().upper() or "CMIG4"

    return CoveredCallSettings(
        underlying=underlying,
        min_extrinsic=_parse_float("ccall_min_extrinsic", 2.0),
        min_days=_parse_int("ccall_min_days", 30),
        max_days=_parse_int("ccall_max_days", 200),
        min_dist_strike=_parse_float("ccall_min_dist_strike", 1.0),
        buyback_target_pct=_parse_float("ccall_buyback_target_pct", 50.0),
        only_target_hits=_parse_bool("ccall_only_target_hits", False),
    )


def get_fundamentus_settings() -> FundamentusSettings:
    raw = _load_raw_settings()

    def _parse_float(name: str, default: float) -> float:
        text = raw.get(name, "").strip()
        if not text:
            return default
        text = text.replace("%", "").replace(",", ".")
        try:
            return float(text)
        except ValueError:
            return default

    return FundamentusSettings(
        target_yield_pct=_parse_float("fund_target_yield_pct", 8.0),
        put_distance_limit_pct=_parse_float("fund_put_distance_limit_pct", 15.0),
        put_min_premium_pct=_parse_float("fund_put_min_premium_pct", 0.5),
        put_target_monthly_yield_pct=_parse_float("fund_put_target_monthly_yield_pct", 1.0),
        put_min_score=_parse_float("fund_put_min_score", 4.0),
    )


def update_fee_settings(
    *,
    equity_fixed: float,
    equity_percent: float,
    option_fixed: float,
    option_percent_notional: float,
) -> None:
    """Atualiza configuração de taxas (substitui os valores atuais)."""

    params = {
        "fee_equity_fixed": equity_fixed,
        "fee_equity_percent": equity_percent,
        "fee_option_fixed": option_fixed,
        "fee_option_percent_notional": option_percent_notional,
    }
    _upsert_settings(params)


def update_strategy_settings(
    *,
    min_score: int,
    limit_opportunities: int,
    recurring_days: int,
) -> None:
    params = {
        "strat_min_score": min_score,
        "strat_limit_opportunities": limit_opportunities,
        "strat_recurring_days": recurring_days,
    }
    _upsert_settings(params)


def update_ranking_view_settings(
    *,
    recurring_limit: int,
    underlying_filter: str,
    option_type_filter: str,
) -> None:
    normalized_option_type = (option_type_filter or "").strip().upper()
    if normalized_option_type not in {"CALL", "PUT"}:
        normalized_option_type = ""

    params = {
        "rank_recurring_limit": int(recurring_limit),
        "rank_underlying_filter": (underlying_filter or "").strip().upper(),
        "rank_option_type_filter": normalized_option_type,
    }
    _upsert_settings(params)


def update_cash_put_settings(
    *,
    underlying: str,
    min_yield_pct: float,
    min_buffer_pct: float,
    min_days: int,
    max_days: int,
    contract_size: int,
    limit: int,
    cash_mode: str,
    buyback_target_pct: float,
) -> None:
    params = {
        "cash_put_underlying": (underlying or "").strip().upper() or "PETR4",
        "cash_put_min_yield_pct": float(min_yield_pct),
        "cash_put_min_buffer_pct": float(min_buffer_pct),
        "cash_put_min_days": int(min_days),
        "cash_put_max_days": int(max_days),
        "cash_put_contract_size": int(contract_size),
        "cash_put_limit": int(limit),
        "cash_put_cash_mode": (cash_mode or "real").strip().lower() or "real",
        "cash_put_buyback_target_pct": float(buyback_target_pct),
    }
    _upsert_settings(params)


def update_covered_call_settings(
    *,
    underlying: str,
    min_extrinsic: float,
    min_days: int,
    max_days: int,
    min_dist_strike: float,
    buyback_target_pct: float,
    only_target_hits: bool,
) -> None:
    params = {
        "ccall_underlying": (underlying or "").strip().upper() or "CMIG4",
        "ccall_min_extrinsic": float(min_extrinsic),
        "ccall_min_days": int(min_days),
        "ccall_max_days": int(max_days),
        "ccall_min_dist_strike": float(min_dist_strike),
        "ccall_buyback_target_pct": float(buyback_target_pct),
        "ccall_only_target_hits": "1" if bool(only_target_hits) else "0",
    }
    _upsert_settings(params)


def update_fundamentus_settings(
    *,
    target_yield_pct: float,
    put_distance_limit_pct: float,
    put_min_premium_pct: float,
    put_target_monthly_yield_pct: float,
    put_min_score: float,
) -> None:
    params = {
        "fund_target_yield_pct": float(target_yield_pct),
        "fund_put_distance_limit_pct": float(put_distance_limit_pct),
        "fund_put_min_premium_pct": float(put_min_premium_pct),
        "fund_put_target_monthly_yield_pct": float(put_target_monthly_yield_pct),
        "fund_put_min_score": float(put_min_score),
    }
    _upsert_settings(params)


__all__ = [
    "FeeSettings",
    "get_fee_settings",
    "update_fee_settings",
    "StrategySettings",
    "get_strategy_settings",
    "update_strategy_settings",
    "RankingViewSettings",
    "get_ranking_view_settings",
    "update_ranking_view_settings",
    "CashCoveredPutSettings",
    "get_cash_put_settings",
    "update_cash_put_settings",
    "CoveredCallSettings",
    "get_covered_call_settings",
    "update_covered_call_settings",
    "FundamentusSettings",
    "get_fundamentus_settings",
    "update_fundamentus_settings",
]
