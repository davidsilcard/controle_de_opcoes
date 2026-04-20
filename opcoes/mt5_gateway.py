from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import uuid
from dataclasses import dataclass
from typing import Any, Iterable, Mapping
from urllib.parse import urlencode

import httpx

from .runtime_env import load_dotenv_once


class Mt5GatewayError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload or {}


@dataclass(frozen=True)
class Mt5GatewayConfig:
    base_url: str
    key_id: str
    shared_secret: str
    timeout_seconds: float = 10.0
    scopes: frozenset[str] = frozenset()


def parse_gateway_scopes(raw: str | None) -> frozenset[str]:
    values = {
        item.strip()
        for item in (raw or "").split(",")
        if item and item.strip()
    }
    return frozenset(values)


def load_gateway_config_from_env() -> Mt5GatewayConfig:
    load_dotenv_once()
    base_url = (os.getenv("MT5_GATEWAY_BASE_URL") or "").strip().rstrip("/")
    key_id = (os.getenv("MT5_GATEWAY_KEY_ID") or "").strip()
    shared_secret = (os.getenv("MT5_GATEWAY_SHARED_SECRET") or "").strip()
    timeout_raw = (os.getenv("MT5_GATEWAY_TIMEOUT_SECONDS") or "10").strip()
    scopes = parse_gateway_scopes(os.getenv("MT5_GATEWAY_SCOPES"))
    try:
        timeout_seconds = float(timeout_raw)
    except ValueError:
        timeout_seconds = 10.0

    if not base_url:
        raise RuntimeError("Defina MT5_GATEWAY_BASE_URL para acessar o mt5-gateway.")
    if not key_id:
        raise RuntimeError("Defina MT5_GATEWAY_KEY_ID para autenticar no mt5-gateway.")
    if not shared_secret:
        raise RuntimeError("Defina MT5_GATEWAY_SHARED_SECRET para autenticar no mt5-gateway.")
    return Mt5GatewayConfig(
        base_url=base_url,
        key_id=key_id,
        shared_secret=shared_secret,
        timeout_seconds=max(timeout_seconds, 1.0),
        scopes=scopes,
    )


def sha256_hex(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def build_canonical_message(
    *,
    method: str,
    path: str,
    query: str,
    timestamp: str,
    nonce: str,
    body_hash: str,
) -> str:
    return "\n".join(
        [
            method.upper(),
            path,
            query,
            timestamp,
            nonce,
            body_hash,
        ]
    )


def build_hmac_headers(
    *,
    key_id: str,
    shared_secret: str,
    method: str,
    path: str,
    query: str = "",
    body: bytes = b"",
    timestamp: str | None = None,
    nonce: str | None = None,
) -> dict[str, str]:
    timestamp = timestamp or str(int(time.time()))
    nonce = nonce or uuid.uuid4().hex
    canonical_message = build_canonical_message(
        method=method,
        path=path,
        query=query,
        timestamp=timestamp,
        nonce=nonce,
        body_hash=sha256_hex(body),
    )
    signature = hmac.new(
        shared_secret.encode("utf-8"),
        canonical_message.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return {
        "X-Key-Id": key_id,
        "X-Timestamp": timestamp,
        "X-Nonce": nonce,
        "X-Signature": signature,
    }


def _json_bytes(payload: Mapping[str, Any] | None) -> bytes:
    if payload is None:
        return b""
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _normalized_symbol(value: Any) -> str:
    return str(value or "").strip().upper()


def _build_query_string(params: Mapping[str, Any] | None = None) -> str:
    if not params:
        return ""
    pairs: list[tuple[str, str]] = []
    for key, value in params.items():
        if value is None:
            continue
        if isinstance(value, bool):
            rendered = "true" if value else "false"
        else:
            rendered = str(value)
        pairs.append((str(key), rendered))
    return urlencode(pairs)


def normalize_quotes_batch_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        raw_items = payload.get("results")
    if not isinstance(raw_items, list):
        raw_items = []

    normalized_items: list[dict[str, Any]] = []
    for raw_item in raw_items:
        if not isinstance(raw_item, Mapping):
            continue
        requested_symbol = _normalized_symbol(
            raw_item.get("requested_symbol")
            or raw_item.get("symbol")
            or raw_item.get("requested")
            or raw_item.get("request_symbol")
        )
        quote_payload = raw_item.get("quote")
        error_payload = raw_item.get("error")
        is_ok = raw_item.get("ok")

        if isinstance(quote_payload, Mapping):
            item = dict(quote_payload)
            item["requested_symbol"] = _normalized_symbol(
                item.get("requested_symbol") or requested_symbol or item.get("symbol")
            )
            item["symbol"] = _normalized_symbol(item.get("symbol") or requested_symbol)
            item["ok"] = True if is_ok is None else bool(is_ok)
            normalized_items.append(item)
            continue

        if is_ok is False or isinstance(error_payload, Mapping):
            item = dict(raw_item)
            item["requested_symbol"] = requested_symbol
            item["symbol"] = _normalized_symbol(item.get("symbol") or requested_symbol)
            item["ok"] = False
            if not isinstance(error_payload, Mapping):
                item["error"] = {"message": str(error_payload or "Quote indisponivel.")}
            normalized_items.append(item)
            continue

        item = dict(raw_item)
        item["requested_symbol"] = _normalized_symbol(
            item.get("requested_symbol") or requested_symbol or item.get("symbol")
        )
        item["symbol"] = _normalized_symbol(item.get("symbol") or requested_symbol)
        item["ok"] = True if is_ok is None else bool(is_ok)
        normalized_items.append(item)

    success_count = sum(1 for item in normalized_items if item.get("ok", True))
    error_count = len(normalized_items) - success_count
    normalized = dict(payload)
    normalized["items"] = normalized_items
    normalized["count"] = len(normalized_items)
    normalized["success_count"] = success_count
    normalized["error_count"] = error_count
    normalized["partial"] = bool(payload.get("partial")) or (success_count > 0 and error_count > 0)
    return normalized


def iter_successful_quote_items(payload: Mapping[str, Any]) -> Iterable[dict[str, Any]]:
    normalized = normalize_quotes_batch_payload(payload)
    for item in normalized.get("items", []):
        if isinstance(item, dict) and item.get("ok", True):
            yield item


class Mt5GatewayClient:
    def __init__(
        self,
        *,
        config: Mt5GatewayConfig | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.config = config or load_gateway_config_from_env()
        self._client = http_client or httpx.Client(
            base_url=self.config.base_url,
            timeout=self.config.timeout_seconds,
        )
        self._owns_client = http_client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def get_health(self) -> dict[str, Any]:
        response = self._client.get("/health")
        return self._decode_response(response)

    def health(self) -> dict[str, Any]:
        return self.get_health()

    def ready(self) -> dict[str, Any]:
        response = self._client.get("/ready")
        return self._decode_response(response)

    def metrics(self) -> dict[str, Any]:
        response = self._request("GET", "/internal/v1/metrics")
        return self._decode_response(response)

    def has_scope(self, scope: str) -> bool:
        configured_scopes = self.config.scopes
        return not configured_scopes or scope in configured_scopes

    def _require_scope(self, scope: str) -> None:
        if self.has_scope(scope):
            return
        raise Mt5GatewayError(
            f"A chave configurada nao possui o escopo obrigatorio: {scope}.",
            status_code=403,
            payload={"error": {"message": "scope_forbidden", "scope": scope}},
        )

    def get_quote(self, symbol: str, *, include_raw: bool = False) -> dict[str, Any]:
        self._require_scope("quotes:read")
        path = f"/internal/v1/quotes/{_normalized_symbol(symbol)}"
        query = _build_query_string({"include_raw": include_raw})
        response = self._request("GET", path, query=query)
        return self._decode_response(response)

    def get_quotes_batch(
        self,
        symbols: list[str],
        *,
        include_raw: bool = False,
    ) -> dict[str, Any]:
        self._require_scope("quotes:read")
        path = "/internal/v1/quotes/batch"
        payload = {
            "symbols": [_normalized_symbol(symbol) for symbol in symbols],
            "include_raw": include_raw,
        }
        response = self._request("POST", path, json_payload=payload)
        decoded = self._decode_response(response)
        return normalize_quotes_batch_payload(decoded)

    def search_symbols(self, query: str, *, limit: int = 20) -> dict[str, Any]:
        self._require_scope("symbols:read")
        text = query.strip().upper()
        path = "/internal/v1/symbols/search"
        query_string = _build_query_string({"q": text, "limit": int(limit)})
        response = self._request("GET", path, query=query_string)
        return self._decode_response(response)

    def preview_order(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        self._require_scope("orders:preview")
        path = "/internal/v1/orders/preview"
        response = self._request("POST", path, json_payload=dict(payload))
        return self._decode_response(response)

    def send_order(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        self._require_scope("orders:send")
        path = "/internal/v1/orders"
        response = self._request("POST", path, json_payload=dict(payload))
        return self._decode_response(response)

    def _request(
        self,
        method: str,
        path: str,
        *,
        query: str = "",
        json_payload: Mapping[str, Any] | None = None,
    ) -> httpx.Response:
        body = _json_bytes(json_payload)
        headers = build_hmac_headers(
            key_id=self.config.key_id,
            shared_secret=self.config.shared_secret,
            method=method,
            path=path,
            query=query,
            body=body,
        )
        if json_payload is not None:
            headers["Content-Type"] = "application/json"
        url = path if not query else f"{path}?{query}"
        try:
            return self._client.request(method, url, content=body or None, headers=headers)
        except httpx.HTTPError as exc:
            raise Mt5GatewayError(f"Falha de rede ao acessar mt5-gateway: {exc}") from exc

    @staticmethod
    def _decode_response(response: httpx.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError:
            payload = {"raw_text": response.text}
        if response.is_error:
            message = "Falha ao consultar mt5-gateway."
            if isinstance(payload, dict):
                message = (
                    payload.get("error", {}).get("message")
                    or payload.get("detail")
                    or message
                )
            raise Mt5GatewayError(
                message,
                status_code=response.status_code,
                payload=payload if isinstance(payload, dict) else {"payload": payload},
            )
        if not isinstance(payload, dict):
            raise Mt5GatewayError(
                "Resposta inesperada do mt5-gateway.",
                status_code=response.status_code,
                payload={"payload": payload},
            )
        return payload


class AsyncMt5GatewayClient:
    def __init__(
        self,
        *,
        config: Mt5GatewayConfig | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.config = config or load_gateway_config_from_env()
        self._client = http_client or httpx.AsyncClient(
            base_url=self.config.base_url,
            timeout=self.config.timeout_seconds,
        )
        self._owns_client = http_client is None

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def get_quotes_batch(
        self,
        symbols: list[str],
        *,
        include_raw: bool = False,
    ) -> dict[str, Any]:
        if self.config.scopes and "quotes:read" not in self.config.scopes:
            raise Mt5GatewayError(
                "A chave configurada nao possui o escopo obrigatorio: quotes:read.",
                status_code=403,
                payload={"error": {"message": "scope_forbidden", "scope": "quotes:read"}},
            )
        path = "/internal/v1/quotes/batch"
        payload = {
            "symbols": [_normalized_symbol(symbol) for symbol in symbols],
            "include_raw": include_raw,
        }
        response = await self._request("POST", path, json_payload=payload)
        decoded = Mt5GatewayClient._decode_response(response)
        return normalize_quotes_batch_payload(decoded)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        query: str = "",
        json_payload: Mapping[str, Any] | None = None,
    ) -> httpx.Response:
        body = _json_bytes(json_payload)
        headers = build_hmac_headers(
            key_id=self.config.key_id,
            shared_secret=self.config.shared_secret,
            method=method,
            path=path,
            query=query,
            body=body,
        )
        if json_payload is not None:
            headers["Content-Type"] = "application/json"
        url = path if not query else f"{path}?{query}"
        try:
            return await self._client.request(method, url, content=body or None, headers=headers)
        except httpx.HTTPError as exc:
            raise Mt5GatewayError(f"Falha de rede ao acessar mt5-gateway: {exc}") from exc


__all__ = [
    "AsyncMt5GatewayClient",
    "Mt5GatewayClient",
    "Mt5GatewayConfig",
    "Mt5GatewayError",
    "build_canonical_message",
    "build_hmac_headers",
    "iter_successful_quote_items",
    "load_gateway_config_from_env",
    "normalize_quotes_batch_payload",
    "parse_gateway_scopes",
    "sha256_hex",
]
