from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import uuid
from dataclasses import dataclass
from typing import Any, Mapping

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


def load_gateway_config_from_env() -> Mt5GatewayConfig:
    load_dotenv_once()
    base_url = (os.getenv("MT5_GATEWAY_BASE_URL") or "").strip().rstrip("/")
    key_id = (os.getenv("MT5_GATEWAY_KEY_ID") or "").strip()
    shared_secret = (os.getenv("MT5_GATEWAY_SHARED_SECRET") or "").strip()
    timeout_raw = (os.getenv("MT5_GATEWAY_TIMEOUT_SECONDS") or "10").strip()
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
) -> dict[str, str]:
    timestamp = str(int(time.time()))
    nonce = uuid.uuid4().hex
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

    def get_quote(self, symbol: str, *, include_raw: bool = False) -> dict[str, Any]:
        path = f"/internal/v1/quotes/{symbol.strip().upper()}"
        query = f"include_raw={'true' if include_raw else 'false'}"
        response = self._request("GET", path, query=query)
        return self._decode_response(response)

    def get_quotes_batch(
        self,
        symbols: list[str],
        *,
        include_raw: bool = False,
    ) -> dict[str, Any]:
        path = "/internal/v1/quotes/batch"
        payload = {
            "symbols": [symbol.strip().upper() for symbol in symbols],
            "include_raw": include_raw,
        }
        response = self._request("POST", path, json_payload=payload)
        return self._decode_response(response)

    def search_symbols(self, query: str, *, limit: int = 20) -> dict[str, Any]:
        text = query.strip().upper()
        path = "/internal/v1/symbols/search"
        query_string = f"q={text}&limit={int(limit)}"
        response = self._request("GET", path, query=query_string)
        return self._decode_response(response)

    def preview_order(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        path = "/internal/v1/orders/preview"
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
        path = "/internal/v1/quotes/batch"
        payload = {
            "symbols": [symbol.strip().upper() for symbol in symbols],
            "include_raw": include_raw,
        }
        response = await self._request("POST", path, json_payload=payload)
        return Mt5GatewayClient._decode_response(response)

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
    "load_gateway_config_from_env",
    "sha256_hex",
]
