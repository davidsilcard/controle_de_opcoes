from __future__ import annotations

import datetime as dt
import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Iterable, Mapping
from urllib.parse import urlsplit, urlunsplit
from zoneinfo import ZoneInfo

import httpx

from .runtime_env import load_dotenv_once
from .utils import infer_option_type

logger = logging.getLogger(__name__)
_LOCAL_DISPLAY_TZ = ZoneInfo("America/Sao_Paulo")


@dataclass(frozen=True)
class MarketDataConfig:
    base_url: str
    bearer_token: str
    timeout_seconds: float = 15.0
    stale_after_seconds: int = 60

    @property
    def enabled(self) -> bool:
        return bool(self.base_url and self.bearer_token)


def _parse_token_map(raw: str | None) -> dict[str, str]:
    tokens: dict[str, str] = {}
    for chunk in (raw or "").split(","):
        item = chunk.strip()
        if not item or "=" not in item:
            continue
        label, token = item.split("=", 1)
        label = label.strip()
        token = token.strip()
        if label and token:
            tokens[label] = token
    return tokens


def load_market_data_config_from_env() -> MarketDataConfig:
    load_dotenv_once()
    base_url = (
        os.getenv("OPCOES_EDGE_BASE_URL")
        or os.getenv("OPCOES_MARKET_DATA_BASE_URL")
        or "http://127.0.0.1:8011"
    ).strip().rstrip("/")
    token = (os.getenv("OPCOES_MARKET_DATA_TOKEN") or "").strip()
    if not token:
        token_map = _parse_token_map(os.getenv("OPCOES_EDGE_API_TOKENS"))
        token = token_map.get("app") or next(iter(token_map.values()), "")
    timeout_raw = (os.getenv("OPCOES_MARKET_DATA_TIMEOUT_SECONDS") or "15").strip()
    stale_raw = (os.getenv("OPCOES_MARKET_DATA_STALE_AFTER_SECONDS") or "60").strip()
    try:
        timeout_seconds = max(float(timeout_raw), 1.0)
    except ValueError:
        timeout_seconds = 15.0
    try:
        stale_after_seconds = max(int(stale_raw), 15)
    except ValueError:
        stale_after_seconds = 60
    return MarketDataConfig(
        base_url=base_url,
        bearer_token=token,
        timeout_seconds=timeout_seconds,
        stale_after_seconds=stale_after_seconds,
    )


def _chunked(values: list[str], size: int) -> Iterable[list[str]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]


def _parse_iso_utc(value: Any) -> dt.datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            return dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
        parsed = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def _age_seconds(time_utc: Any) -> int | None:
    parsed = _parse_iso_utc(time_utc)
    if parsed is None:
        return None
    delta = dt.datetime.now(dt.timezone.utc) - parsed
    return max(int(delta.total_seconds()), 0)


def _parse_market_timestamp(value: Any) -> dt.datetime | None:
    parsed = _parse_iso_utc(value)
    if parsed is not None:
        return parsed
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed_date = dt.date.fromisoformat(text)
    except ValueError:
        return None
    return dt.datetime.combine(
        parsed_date,
        dt.time.min,
        tzinfo=dt.timezone.utc,
    )


def _market_status(time_utc: Any, *, stale_after_seconds: int) -> str:
    age = _age_seconds(time_utc)
    if age is None:
        return "offline"
    if age <= stale_after_seconds:
        return "live"
    return "stale"


def _normalize_quote_item(item: Mapping[str, Any], *, stale_after_seconds: int) -> dict[str, Any] | None:
    ok = item.get("ok")
    if ok is False:
        return {
            "symbol": str(item.get("requested_symbol") or item.get("symbol") or "").strip().upper(),
            "requested_symbol": str(item.get("requested_symbol") or item.get("symbol") or "").strip().upper(),
            "ok": False,
            "error": item.get("error"),
            "market_status": "offline",
            "stale_seconds": None,
        }

    quote_payload = item.get("quote")
    payload = dict(quote_payload) if isinstance(quote_payload, Mapping) else dict(item)
    symbol = str(payload.get("symbol") or item.get("requested_symbol") or "").strip().upper()
    if not symbol:
        return None
    time_utc = payload.get("time_utc")
    return {
        "symbol": symbol,
        "requested_symbol": str(item.get("requested_symbol") or symbol).strip().upper(),
        "ok": True,
        "bid": _to_float(payload.get("bid")),
        "ask": _to_float(payload.get("ask")),
        "last": _to_float(payload.get("last")),
        "time_utc": time_utc,
        "source": payload.get("source"),
        "raw": payload,
        "market_status": _market_status(time_utc, stale_after_seconds=stale_after_seconds),
        "stale_seconds": _age_seconds(time_utc),
    }


def _error_code_from_item(item: Mapping[str, Any]) -> str:
    error_payload = item.get("error")
    if isinstance(error_payload, Mapping):
        code = str(error_payload.get("code") or "").strip().lower()
        if code:
            return code
    return "unknown"


def _symbol_from_item(item: Mapping[str, Any]) -> str:
    return str(item.get("requested_symbol") or item.get("symbol") or "").strip().upper()


def _to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def market_source_label(source: str | None) -> str | None:
    normalized = (source or "").strip().lower()
    if not normalized:
        return None
    mapping = {
        "ask": "Ask",
        "bid": "Bid",
        "last": "Ultimo",
        "snapshot": "Snapshot",
    }
    return mapping.get(normalized, normalized.upper())


def format_market_timestamp_label(value: Any) -> str | None:
    text = str(value or "").strip()
    if text:
        try:
            parsed_date = dt.date.fromisoformat(text)
        except ValueError:
            parsed_date = None
        if parsed_date is not None and len(text) == 10:
            return parsed_date.strftime("%d/%m/%Y")
    try:
        parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        parsed = None
    if parsed is None:
        parsed = _parse_market_timestamp(value)
    if parsed is None:
        return None
    if parsed.time() == dt.time.min:
        return parsed.strftime("%d/%m/%Y")
    localized = parsed.astimezone(_LOCAL_DISPLAY_TZ)
    return localized.strftime("%d/%m %H:%M:%S")


class MarketDataClient:
    def __init__(
        self,
        *,
        config: MarketDataConfig | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.config = config or load_market_data_config_from_env()
        self._client = http_client or httpx.Client(
            base_url=self.config.base_url,
            timeout=self.config.timeout_seconds,
        )
        self._owns_client = http_client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    @property
    def websocket_quotes_url(self) -> str:
        base = self.config.base_url.rstrip("/")
        parts = urlsplit(base)
        scheme = "wss" if parts.scheme == "https" else "ws"
        path = "/v1/ws/quotes"
        return urlunsplit((scheme, parts.netloc, path, "", ""))

    def create_ws_token(self) -> dict[str, Any]:
        if not self.config.enabled:
            raise RuntimeError("Mercado ao vivo desabilitado.")
        headers = {"Authorization": f"Bearer {self.config.bearer_token}"}
        response = self._client.post("/v1/ws/token", headers=headers)
        response.raise_for_status()
        payload = response.json()
        token = str(payload.get("token") or "").strip()
        expires_in = int(payload.get("expires_in") or 0)
        if not token or expires_in <= 0:
            raise RuntimeError("Resposta inválida ao solicitar token de WebSocket.")
        return {
            "token": token,
            "expires_in": expires_in,
            "ws_url": self.websocket_quotes_url,
            "stale_after_seconds": self.config.stale_after_seconds,
        }

    def fetch_quotes(self, symbols: Iterable[str]) -> dict[str, dict[str, Any]]:
        normalized = sorted({str(symbol or "").strip().upper() for symbol in symbols if str(symbol or "").strip()})
        if not normalized or not self.config.enabled:
            return {}
        headers = {"Authorization": f"Bearer {self.config.bearer_token}"}
        results: dict[str, dict[str, Any]] = {}
        for chunk in _chunked(normalized, 100):
            try:
                response = self._client.post(
                    "/v1/quotes/batch",
                    headers=headers,
                    json={"symbols": chunk, "include_raw": False},
                )
                response.raise_for_status()
                payload = response.json()
            except Exception as exc:
                logger.warning(
                    "market_data_batch_failed",
                    extra={
                        "base_url": self.config.base_url,
                        "chunk_size": len(chunk),
                        "exception_type": exc.__class__.__name__,
                    },
                )
                return results
            items = payload.get("items") if isinstance(payload, Mapping) else None
            if not isinstance(items, list):
                logger.warning(
                    "market_data_batch_invalid_payload",
                    extra={
                        "base_url": self.config.base_url,
                        "chunk_size": len(chunk),
                        "payload_type": type(payload).__name__,
                    },
                )
                continue
            success_count = sum(1 for item in items if isinstance(item, Mapping) and item.get("ok", True))
            error_count = sum(1 for item in items if isinstance(item, Mapping) and item.get("ok") is False)
            error_items = [
                {
                    "symbol": _symbol_from_item(item),
                    "error_code": _error_code_from_item(item),
                }
                for item in items
                if isinstance(item, Mapping) and item.get("ok") is False
            ]
            logger.info(
                "market_data_batch_processed",
                extra={
                    "base_url": self.config.base_url,
                    "chunk_size": len(chunk),
                    "count_total": len(items),
                    "count_success": success_count,
                    "count_error": error_count,
                    "partial": bool(payload.get("partial")) if isinstance(payload, Mapping) else False,
                    "error_items": error_items,
                },
            )
            for item in items:
                if not isinstance(item, Mapping):
                    continue
                normalized_item = _normalize_quote_item(
                    item,
                    stale_after_seconds=self.config.stale_after_seconds,
                )
                if normalized_item is None:
                    continue
                results[normalized_item["symbol"]] = normalized_item
        return results


def market_price_for_position(position: Mapping[str, Any], quote: Mapping[str, Any] | None) -> tuple[float | None, str | None]:
    if not quote or not quote.get("ok", True):
        return None, None
    is_option = infer_option_type(position.get("ticker") or "") in {"CALL", "PUT"}
    side = str(position.get("side") or "").strip().lower()
    if not is_option:
        for field in ("last", "bid", "ask"):
            price = _to_float(quote.get(field))
            if price is not None and price > 0:
                return price, field
        return None, None
    if side == "short":
        priority = ("ask", "last", "bid")
    else:
        priority = ("bid", "last", "ask")
    for field in priority:
        price = _to_float(quote.get(field))
        if price is not None and price > 0:
            return price, field
    return None, None


def market_price_for_suggestion(quote: Mapping[str, Any] | None) -> tuple[float | None, str | None]:
    if not quote or not quote.get("ok", True):
        return None, None
    for field in ("bid", "last", "ask"):
        price = _to_float(quote.get(field))
        if price is not None and price > 0:
            return price, field
    return None, None


def _recompute_position_metrics(position: dict[str, Any]) -> None:
    status = str(position.get("status") or "").strip().lower()
    is_closed = status == "closed"
    open_qty = int(position.get("open_qty") or 0)
    qty = int(position.get("qty") or 0)
    entry_price = float(position.get("entry_price") or 0.0)
    fees = float(position.get("fees") or 0.0)
    realized_pl = _to_float(position.get("realized_pl"))
    last_price = _to_float(position.get("last_price"))
    side = str(position.get("side") or "").strip().lower()
    direction = -1 if side == "short" else 1

    pl_open = None
    if not is_closed and last_price is not None and entry_price and open_qty > 0:
        pl_open = direction * (last_price - entry_price) * open_qty

    pl = None
    if realized_pl is not None or pl_open is not None:
        pl = (realized_pl or 0.0) + (pl_open or 0.0) - fees
    position["pl"] = pl

    pl_pct = None
    invested = entry_price * qty
    if pl is not None and invested:
        pl_pct = (pl / invested) * 100.0
    position["pl_pct"] = pl_pct

    strike = _to_float(position.get("strike"))
    underlying_price = _to_float(position.get("underlying_price"))
    if infer_option_type(position.get("ticker") or "") == "CALL" and last_price is not None and underlying_price is not None and strike is not None and underlying_price > 0:
        intrinsic = max(underlying_price - strike, 0.0)
        position["extrinsic_pct_spot"] = max(last_price - intrinsic, 0.0) / underlying_price * 100.0


def enrich_positions_with_live_market_data(
    positions: list[dict[str, Any]],
    *,
    client: MarketDataClient | None = None,
) -> list[dict[str, Any]]:
    if not positions:
        return positions
    working = [dict(pos) for pos in positions]
    symbols: list[str] = []
    for pos in working:
        if str(pos.get("status") or "").strip().lower() == "closed":
            continue
        ticker = str(pos.get("ticker") or "").strip().upper()
        underlying = str(pos.get("underlying") or "").strip().upper()
        if ticker:
            symbols.append(ticker)
        if underlying and underlying != ticker:
            symbols.append(underlying)

    md_client = client or MarketDataClient()
    try:
        market_map = md_client.fetch_quotes(symbols)
    finally:
        if client is None:
            md_client.close()

    for pos in working:
        pos.setdefault("market_status", "snapshot")
        if pos.get("last_price") is not None:
            pos.setdefault("market_price_source", "snapshot")
            pos.setdefault("market_time_utc", pos.get("last_snapshot_date"))
        else:
            pos.setdefault("market_price_source", None)
            pos.setdefault("market_time_utc", None)
        if pos.get("underlying_price") is not None:
            pos.setdefault("underlying_market_status", "snapshot")
            pos.setdefault(
                "underlying_market_time_utc",
                pos.get("underlying_price_date") or pos.get("last_snapshot_date"),
            )
        else:
            pos.setdefault("underlying_market_status", None)
            pos.setdefault("underlying_market_time_utc", None)
        if str(pos.get("status") or "").strip().lower() == "closed":
            continue
        ticker = str(pos.get("ticker") or "").strip().upper()
        underlying = str(pos.get("underlying") or "").strip().upper()
        quote = market_map.get(ticker)
        price, source = market_price_for_position(pos, quote)
        if price is not None:
            pos["last_price"] = price
            pos["market_price_source"] = source
            pos["market_time_utc"] = quote.get("time_utc") if quote else None
            pos["market_status"] = quote.get("market_status") if quote else "snapshot"
            pos["market_stale_seconds"] = quote.get("stale_seconds") if quote else None
        if underlying and underlying != ticker:
            underlying_quote = market_map.get(underlying)
            if underlying_quote and underlying_quote.get("ok", True):
                underlying_last = _to_float(underlying_quote.get("last"))
                if underlying_last is not None:
                    pos["underlying_price"] = underlying_last
                    pos["underlying_market_status"] = underlying_quote.get("market_status")
                    pos["underlying_market_time_utc"] = underlying_quote.get("time_utc")
        _recompute_position_metrics(pos)
    return working


def enrich_underlying_quote_with_live_market_data(
    quote: dict[str, Any] | None,
    *,
    underlying: str,
    client: MarketDataClient | None = None,
) -> dict[str, Any] | None:
    normalized = str(underlying or "").strip().upper()
    if not normalized:
        return quote
    md_client = client or MarketDataClient()
    try:
        market_map = md_client.fetch_quotes([normalized])
    finally:
        if client is None:
            md_client.close()
    live = market_map.get(normalized)
    if not live or not live.get("ok", True):
        if quote is None:
            return None
        enriched = dict(quote)
        if enriched.get("price") is not None:
            enriched.setdefault("market_status", "snapshot")
            enriched.setdefault("market_price_source", "snapshot")
            enriched.setdefault(
                "market_time_utc",
                enriched.get("price_date") or enriched.get("snapshot_date"),
            )
        return enriched
    enriched = dict(quote or {})
    enriched["underlying"] = normalized
    enriched["price"] = _to_float(live.get("last"))
    enriched["price_date"] = live.get("time_utc") or enriched.get("price_date")
    enriched["market_status"] = live.get("market_status")
    enriched["market_price_source"] = "last"
    enriched["market_time_utc"] = live.get("time_utc")
    enriched["market_stale_seconds"] = live.get("stale_seconds")
    return enriched


def enrich_option_rows_with_live_market_data(
    rows: list[dict[str, Any]],
    *,
    underlying: str,
    client: MarketDataClient | None = None,
) -> list[dict[str, Any]]:
    if not rows:
        return rows
    normalized_underlying = str(underlying or "").strip().upper()
    symbols = [normalized_underlying] + [str(row.get("ticker") or "").strip().upper() for row in rows]
    md_client = client or MarketDataClient()
    try:
        market_map = md_client.fetch_quotes(symbols)
    finally:
        if client is None:
            md_client.close()
    underlying_quote = market_map.get(normalized_underlying)
    underlying_last = _to_float(underlying_quote.get("last")) if underlying_quote else None

    output: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        if (
            item.get("ultimo") is not None
            or item.get("best_bid") is not None
            or item.get("best_ask") is not None
        ):
            item.setdefault("market_status", "snapshot")
            item.setdefault("market_premium_source", "snapshot")
            item.setdefault(
                "market_time_utc",
                item.get("underlying_price_date") or item.get("snapshot_date"),
            )
        if item.get("underlying_price") is not None:
            item.setdefault("underlying_market_status", "snapshot")
            item.setdefault(
                "underlying_market_time_utc",
                item.get("underlying_price_date") or item.get("snapshot_date"),
            )
        ticker = str(item.get("ticker") or "").strip().upper()
        quote = market_map.get(ticker)
        premium_ref, premium_source = market_price_for_suggestion(quote)
        if premium_ref is not None:
            item["ultimo"] = premium_ref
            if premium_source == "bid":
                item["best_bid"] = premium_ref
            item["market_premium_ref"] = premium_ref
            item["market_premium_source"] = premium_source
            item["market_status"] = quote.get("market_status") if quote else "snapshot"
            item["market_time_utc"] = quote.get("time_utc") if quote else None
        if underlying_last is not None:
            item["underlying_price"] = underlying_last
            item["underlying_market_status"] = underlying_quote.get("market_status") if underlying_quote else None
        output.append(item)
    return output


def market_status_label(status: str | None) -> str:
    normalized = (status or "").strip().lower()
    if normalized == "live":
        return "Ao vivo"
    if normalized == "stale":
        return "Atrasado"
    if normalized == "snapshot":
        return "Snapshot"
    return "Offline"


__all__ = [
    "MarketDataClient",
    "MarketDataConfig",
    "enrich_option_rows_with_live_market_data",
    "enrich_positions_with_live_market_data",
    "enrich_underlying_quote_with_live_market_data",
    "load_market_data_config_from_env",
    "format_market_timestamp_label",
    "market_price_for_position",
    "market_price_for_suggestion",
    "market_source_label",
    "market_status_label",
]
