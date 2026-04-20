from __future__ import annotations

import asyncio
import os
import threading
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from pydantic import BaseModel, Field

from .mt5_gateway import (
    AsyncMt5GatewayClient,
    Mt5GatewayClient,
    Mt5GatewayError,
    iter_successful_quote_items,
)
from .runtime_env import load_dotenv_once


class BatchQuotesRequest(BaseModel):
    symbols: list[str] = Field(min_length=1, max_length=100)
    include_raw: bool = False


class OrderPreviewRequest(BaseModel):
    symbol: str
    side: str
    order_type: str
    volume: float = Field(gt=0)
    price: float | None = Field(default=None, gt=0)
    stop_limit_price: float | None = Field(default=None, gt=0)
    stop_loss: float | None = Field(default=None, gt=0)
    take_profit: float | None = Field(default=None, gt=0)
    deviation: int | None = Field(default=None, ge=0, le=500)
    time_in_force: str = "day"
    filling_type: str = "auto"
    expiration: str | None = None
    comment: str | None = None
    magic: int | None = Field(default=None, ge=0)
    client_order_id: str | None = None


@dataclass(frozen=True)
class EdgeSettings:
    api_tokens: dict[str, str]
    quote_cache_ms: int
    ws_token_secret: str
    ws_token_ttl_seconds: int
    ws_poll_interval_ms: int
    app_host: str
    app_port: int


class QuoteCache:
    def __init__(self, ttl_ms: int) -> None:
        self.ttl_ms = ttl_ms
        self._lock = threading.Lock()
        self._items: dict[str, tuple[float, dict[str, Any]]] = {}

    def get_many(self, symbols: list[str]) -> tuple[list[dict[str, Any]], list[str]]:
        now = time.monotonic()
        hits: list[dict[str, Any]] = []
        misses: list[str] = []
        with self._lock:
            for symbol in symbols:
                entry = self._items.get(symbol)
                if not entry:
                    misses.append(symbol)
                    continue
                expires_at, payload = entry
                if expires_at <= now:
                    self._items.pop(symbol, None)
                    misses.append(symbol)
                    continue
                hits.append(payload)
        return hits, misses

    def set_many(self, items: list[dict[str, Any]]) -> None:
        now = time.monotonic()
        expires_at = now + (self.ttl_ms / 1000.0)
        with self._lock:
            for item in items:
                symbol = str(item.get("requested_symbol") or item.get("symbol") or "").strip().upper()
                if symbol:
                    self._items[symbol] = (expires_at, item)


def load_edge_settings() -> EdgeSettings:
    load_dotenv_once()
    tokens_raw = (os.getenv("OPCOES_EDGE_API_TOKENS") or "").strip()
    tokens: dict[str, str] = {}
    for chunk in tokens_raw.split(","):
        item = chunk.strip()
        if not item or "=" not in item:
            continue
        label, token = item.split("=", 1)
        label = label.strip()
        token = token.strip()
        if label and token:
            tokens[label] = token
    if not tokens:
        raise RuntimeError("Defina OPCOES_EDGE_API_TOKENS para publicar a edge API.")

    ws_secret = (os.getenv("OPCOES_EDGE_WS_TOKEN_SECRET") or os.getenv("OPCOES_SECRET_KEY") or "").strip()
    if not ws_secret:
        raise RuntimeError("Defina OPCOES_EDGE_WS_TOKEN_SECRET ou OPCOES_SECRET_KEY.")

    def _int_env(name: str, default: int, minimum: int) -> int:
        raw = (os.getenv(name) or str(default)).strip()
        try:
            value = int(raw)
        except ValueError:
            value = default
        return max(value, minimum)

    return EdgeSettings(
        api_tokens=tokens,
        quote_cache_ms=_int_env("OPCOES_EDGE_QUOTE_CACHE_MS", 500, 50),
        ws_token_secret=ws_secret,
        ws_token_ttl_seconds=_int_env("OPCOES_EDGE_WS_TOKEN_TTL_SECONDS", 60, 5),
        ws_poll_interval_ms=_int_env("OPCOES_EDGE_WS_POLL_INTERVAL_MS", 1000, 100),
        app_host=(os.getenv("OPCOES_EDGE_HOST") or "0.0.0.0").strip() or "0.0.0.0",
        app_port=_int_env("OPCOES_EDGE_PORT", 8001, 1),
    )


def create_app(
    *,
    settings: EdgeSettings | None = None,
    gateway_client: Mt5GatewayClient | None = None,
    async_gateway_client: AsyncMt5GatewayClient | None = None,
) -> FastAPI:
    load_dotenv_once()
    settings = settings or load_edge_settings()
    gateway_client = gateway_client or Mt5GatewayClient()
    async_gateway_client = async_gateway_client or AsyncMt5GatewayClient()
    cache = QuoteCache(ttl_ms=settings.quote_cache_ms)
    serializer = URLSafeTimedSerializer(settings.ws_token_secret, salt="opcoes-edge-ws")

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        try:
            yield
        finally:
            gateway_client.close()
            await async_gateway_client.aclose()

    app = FastAPI(title="opcoes-edge", version="0.1.0", lifespan=lifespan)
    app.state.edge_settings = settings
    app.state.gateway_client = gateway_client
    app.state.async_gateway_client = async_gateway_client
    app.state.quote_cache = cache
    app.state.ws_serializer = serializer

    def get_gateway_client() -> Mt5GatewayClient:
        return app.state.gateway_client

    def get_async_gateway_client() -> AsyncMt5GatewayClient:
        return app.state.async_gateway_client

    def get_cache() -> QuoteCache:
        return app.state.quote_cache

    def verify_token(authorization: str | None = Header(default=None)) -> str:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Bearer token ausente ou invalido.")
        token = authorization[7:].strip()
        for label, expected_token in settings.api_tokens.items():
            if token == expected_token:
                return label
        raise HTTPException(status_code=401, detail="Bearer token invalido.")

    def sign_ws_token(subject: str) -> str:
        return serializer.dumps({"sub": subject, "kind": "quotes"})

    def verify_ws_token(token: str) -> dict[str, Any]:
        try:
            payload = serializer.loads(token, max_age=settings.ws_token_ttl_seconds)
        except SignatureExpired as exc:
            raise HTTPException(status_code=401, detail="WebSocket token expirado.") from exc
        except BadSignature as exc:
            raise HTTPException(status_code=401, detail="WebSocket token invalido.") from exc
        if not isinstance(payload, dict) or payload.get("kind") != "quotes":
            raise HTTPException(status_code=401, detail="WebSocket token invalido.")
        return payload

    def load_quotes(
        *,
        client: Mt5GatewayClient,
        cache_obj: QuoteCache,
        symbols: list[str],
        include_raw: bool,
    ) -> list[dict[str, Any]]:
        normalized = [symbol.strip().upper() for symbol in symbols if symbol and symbol.strip()]
        if not normalized:
            return []
        if include_raw:
            batch = client.get_quotes_batch(normalized, include_raw=True)
            return list(batch.get("items", []))
        cached_items, missing = cache_obj.get_many(normalized)
        items_by_symbol = {
            str(item.get("requested_symbol") or item.get("symbol") or "").upper(): item
            for item in cached_items
        }
        if missing:
            batch = client.get_quotes_batch(missing, include_raw=include_raw)
            fresh_items = list(iter_successful_quote_items(batch))
            cache_obj.set_many(fresh_items)
            for item in fresh_items:
                key = str(item.get("requested_symbol") or item.get("symbol") or "").upper()
                items_by_symbol[key] = item
        return [items_by_symbol[symbol] for symbol in normalized if symbol in items_by_symbol]

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "service": "opcoes-edge",
            "quote_cache_ms": settings.quote_cache_ms,
            "ws_poll_interval_ms": settings.ws_poll_interval_ms,
        }

    @app.get("/v1/quotes/{symbol}")
    def get_quote(
        symbol: str,
        include_raw: bool = Query(False),
        _subject: str = Depends(verify_token),
        client: Mt5GatewayClient = Depends(get_gateway_client),
        cache_obj: QuoteCache = Depends(get_cache),
    ) -> JSONResponse:
        normalized_symbol = str(symbol or "").strip().upper()
        try:
            if include_raw:
                payload = client.get_quote(normalized_symbol, include_raw=True)
                return JSONResponse(payload)
            cached_items, _missing = cache_obj.get_many([normalized_symbol])
            if cached_items:
                return JSONResponse(cached_items[0])
            payload = client.get_quote(normalized_symbol, include_raw=False)
        except Mt5GatewayError as exc:
            raise HTTPException(status_code=exc.status_code or 502, detail=exc.payload or str(exc)) from exc
        if not isinstance(payload, dict):
            raise HTTPException(status_code=404, detail="Quote nao encontrado.")
        if payload.get("ok") is False:
            error_payload = payload.get("error")
            detail = error_payload if isinstance(error_payload, dict) else {"message": "Quote nao encontrado."}
            raise HTTPException(status_code=404, detail=detail)
        cache_obj.set_many([payload])
        return JSONResponse(payload)

    @app.post("/v1/quotes/batch")
    def get_quotes_batch(
        payload: BatchQuotesRequest,
        _subject: str = Depends(verify_token),
        client: Mt5GatewayClient = Depends(get_gateway_client),
        cache_obj: QuoteCache = Depends(get_cache),
    ) -> JSONResponse:
        try:
            result = client.get_quotes_batch(payload.symbols, include_raw=payload.include_raw)
        except Mt5GatewayError as exc:
            raise HTTPException(status_code=exc.status_code or 502, detail=exc.payload or str(exc)) from exc
        if not payload.include_raw:
            cache_obj.set_many(list(iter_successful_quote_items(result)))
        return JSONResponse(result)

    @app.get("/v1/symbols/search")
    def search_symbols(
        q: str = Query(..., min_length=1),
        limit: int = Query(20, ge=1, le=100),
        _subject: str = Depends(verify_token),
        client: Mt5GatewayClient = Depends(get_gateway_client),
    ) -> JSONResponse:
        try:
            payload = client.search_symbols(q, limit=limit)
        except Mt5GatewayError as exc:
            raise HTTPException(status_code=exc.status_code or 502, detail=exc.payload or str(exc)) from exc
        return JSONResponse(payload)

    @app.get("/v1/metrics")
    def metrics(
        _subject: str = Depends(verify_token),
        client: Mt5GatewayClient = Depends(get_gateway_client),
    ) -> JSONResponse:
        try:
            payload = client.metrics()
        except Mt5GatewayError as exc:
            raise HTTPException(status_code=exc.status_code or 502, detail=exc.payload or str(exc)) from exc
        return JSONResponse(payload)

    @app.post("/v1/orders/preview")
    def order_preview(
        payload: OrderPreviewRequest,
        _subject: str = Depends(verify_token),
        client: Mt5GatewayClient = Depends(get_gateway_client),
    ) -> JSONResponse:
        try:
            result = client.preview_order(payload.model_dump(exclude_none=True))
        except Mt5GatewayError as exc:
            raise HTTPException(status_code=exc.status_code or 502, detail=exc.payload or str(exc)) from exc
        return JSONResponse(result)

    @app.post("/v1/orders")
    def send_order(
        payload: OrderPreviewRequest,
        _subject: str = Depends(verify_token),
        client: Mt5GatewayClient = Depends(get_gateway_client),
    ) -> JSONResponse:
        try:
            result = client.send_order(payload.model_dump(exclude_none=True))
        except Mt5GatewayError as exc:
            raise HTTPException(status_code=exc.status_code or 502, detail=exc.payload or str(exc)) from exc
        return JSONResponse(result)

    @app.post("/v1/ws/token")
    def create_ws_token(subject: str = Depends(verify_token)) -> dict[str, Any]:
        return {
            "token": sign_ws_token(subject),
            "expires_in": settings.ws_token_ttl_seconds,
        }

    @app.websocket("/v1/ws/quotes")
    async def quotes_socket(websocket: WebSocket, token: str = Query(...)) -> None:
        try:
            payload = verify_ws_token(token)
        except HTTPException:
            await websocket.close(code=1008)
            return
        await websocket.accept()
        subscribed: set[str] = set()
        poll_seconds = settings.ws_poll_interval_ms / 1000.0
        try:
            while True:
                try:
                    message = await asyncio.wait_for(websocket.receive_json(), timeout=poll_seconds)
                    action = str(message.get("action") or "").strip().lower()
                    symbols = {
                        str(symbol).strip().upper()
                        for symbol in (message.get("symbols") or [])
                        if str(symbol).strip()
                    }
                    if action == "subscribe":
                        subscribed.update(symbols)
                        await websocket.send_json(
                            {
                                "type": "subscribed",
                                "client": payload.get("sub"),
                                "symbols": sorted(subscribed),
                            }
                        )
                    elif action == "unsubscribe":
                        subscribed.difference_update(symbols)
                        await websocket.send_json(
                            {
                                "type": "subscribed",
                                "client": payload.get("sub"),
                                "symbols": sorted(subscribed),
                            }
                        )
                    elif action == "ping":
                        await websocket.send_json({"type": "pong"})
                    else:
                        await websocket.send_json({"type": "error", "message": "acao desconhecida"})
                except asyncio.TimeoutError:
                    if not subscribed:
                        continue
                    cached_items, missing = cache.get_many(sorted(subscribed))
                    items_by_symbol = {
                        str(item.get("requested_symbol") or item.get("symbol") or "").upper(): item
                        for item in cached_items
                    }
                    if missing:
                        try:
                            batch = await get_async_gateway_client().get_quotes_batch(missing, include_raw=False)
                            fresh_items = list(iter_successful_quote_items(batch))
                            cache.set_many(fresh_items)
                            for item in fresh_items:
                                key = str(item.get("requested_symbol") or item.get("symbol") or "").upper()
                                items_by_symbol[key] = item
                        except Mt5GatewayError as exc:
                            await websocket.send_json(
                                {
                                    "type": "error",
                                    "message": str(exc),
                                    "details": exc.payload,
                                }
                            )
                            continue
                    items = [items_by_symbol[symbol] for symbol in sorted(subscribed) if symbol in items_by_symbol]
                    await websocket.send_json({"type": "snapshot", "count": len(items), "items": items})
        except WebSocketDisconnect:
            return

    return app


def main() -> int:
    settings = load_edge_settings()
    uvicorn.run(
        "opcoes.edge:create_app",
        factory=True,
        host=settings.app_host,
        port=settings.app_port,
        log_level="info",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
