from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import time
from collections import Counter
from dataclasses import dataclass
from typing import Any, Iterable

import httpx

from .runtime_env import load_dotenv_once


@dataclass(frozen=True)
class StressResult:
    latency_ms: float
    status_code: int
    ok: bool
    error: str | None = None


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


def resolve_bearer_token(explicit_token: str | None = None) -> str | None:
    load_dotenv_once()
    token = (explicit_token or os.getenv("OPCOES_MARKET_DATA_TOKEN") or "").strip()
    if token:
        return token
    token_map = _parse_token_map(os.getenv("OPCOES_EDGE_API_TOKENS"))
    return token_map.get("app") or next(iter(token_map.values()), None)


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return float(values[0])
    ordered = sorted(float(v) for v in values)
    rank = (len(ordered) - 1) * pct
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    weight = rank - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def build_summary(results: list[StressResult], *, elapsed_seconds: float) -> dict[str, Any]:
    latencies = [result.latency_ms for result in results]
    ok_count = sum(1 for result in results if result.ok)
    error_count = len(results) - ok_count
    statuses = Counter(result.status_code for result in results)
    errors = Counter(result.error for result in results if result.error)
    requests_per_second = (len(results) / elapsed_seconds) if elapsed_seconds > 0 else 0.0
    return {
        "requests_total": len(results),
        "ok_count": ok_count,
        "error_count": error_count,
        "success_rate_pct": (ok_count / len(results) * 100.0) if results else 0.0,
        "elapsed_seconds": elapsed_seconds,
        "requests_per_second": requests_per_second,
        "latency_ms": {
            "min": min(latencies) if latencies else 0.0,
            "avg": statistics.fmean(latencies) if latencies else 0.0,
            "p50": percentile(latencies, 0.50),
            "p95": percentile(latencies, 0.95),
            "p99": percentile(latencies, 0.99),
            "max": max(latencies) if latencies else 0.0,
        },
        "status_codes": dict(sorted(statuses.items())),
        "top_errors": [
            {"error": error or "unknown", "count": count}
            for error, count in errors.most_common(5)
        ],
    }


def _normalize_symbols(raw: str) -> list[str]:
    values = [item.strip().upper() for item in raw.split(",")]
    return [item for item in values if item]


def build_request_spec(args: argparse.Namespace) -> tuple[str, str, dict[str, Any] | None]:
    mode = args.mode
    if mode == "health":
        return "GET", "/health", None
    if mode == "ready":
        return "GET", "/ready", None
    if mode == "metrics":
        return "GET", "/v1/metrics", None
    if mode == "quote":
        return "GET", f"/v1/quotes/{args.symbol.strip().upper()}", None
    if mode == "batch":
        return "POST", "/v1/quotes/batch", {
            "symbols": _normalize_symbols(args.symbols),
            "include_raw": False,
        }
    if mode == "search":
        query = args.query.strip().upper()
        return "GET", f"/v1/symbols/search?q={query}&limit={int(args.limit)}", None
    raise ValueError(f"Modo de stress desconhecido: {mode}")


async def _single_request(
    client: httpx.AsyncClient,
    *,
    method: str,
    path: str,
    json_payload: dict[str, Any] | None,
) -> StressResult:
    started = time.perf_counter()
    try:
        response = await client.request(method, path, json=json_payload)
        latency_ms = (time.perf_counter() - started) * 1000.0
        ok = 200 <= response.status_code < 400
        error = None if ok else (response.text[:200] or f"http_{response.status_code}")
        return StressResult(
            latency_ms=latency_ms,
            status_code=response.status_code,
            ok=ok,
            error=error,
        )
    except Exception as exc:
        latency_ms = (time.perf_counter() - started) * 1000.0
        return StressResult(
            latency_ms=latency_ms,
            status_code=0,
            ok=False,
            error=type(exc).__name__,
        )


async def run_stress(args: argparse.Namespace) -> dict[str, Any]:
    token = resolve_bearer_token(args.token)
    method, path, json_payload = build_request_spec(args)
    headers: dict[str, str] = {}
    if path.startswith("/v1/"):
        if not token:
            raise RuntimeError(
                "Nenhum bearer token encontrado. Defina OPCOES_MARKET_DATA_TOKEN ou OPCOES_EDGE_API_TOKENS."
            )
        headers["Authorization"] = f"Bearer {token}"

    timeout = httpx.Timeout(args.timeout_seconds)
    limits = httpx.Limits(max_connections=args.concurrency, max_keepalive_connections=args.concurrency)
    async with httpx.AsyncClient(
        base_url=args.base_url.rstrip("/"),
        headers=headers,
        timeout=timeout,
        limits=limits,
    ) as client:
        for _ in range(max(args.warmup_requests, 0)):
            await _single_request(client, method=method, path=path, json_payload=json_payload)

        semaphore = asyncio.Semaphore(max(args.concurrency, 1))

        async def _run_one() -> StressResult:
            async with semaphore:
                return await _single_request(
                    client,
                    method=method,
                    path=path,
                    json_payload=json_payload,
                )

        started = time.perf_counter()
        results = await asyncio.gather(*[_run_one() for _ in range(max(args.requests, 1))])
        elapsed = time.perf_counter() - started

    summary = build_summary(results, elapsed_seconds=elapsed)
    summary["target"] = {
        "base_url": args.base_url.rstrip("/"),
        "method": method,
        "path": path,
        "concurrency": args.concurrency,
        "requests": args.requests,
        "warmup_requests": args.warmup_requests,
    }
    return summary


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Teste de estresse simples para a API web/edge da aplicação.",
    )
    parser.add_argument(
        "--base-url",
        default=os.getenv("OPCOES_EDGE_BASE_URL", "http://127.0.0.1:8011"),
        help="URL base da API a ser testada.",
    )
    parser.add_argument(
        "--mode",
        choices=["health", "ready", "metrics", "quote", "batch", "search"],
        default="quote",
        help="Perfil do endpoint que será testado.",
    )
    parser.add_argument("--symbol", default="PETR4", help="Símbolo usado em --mode quote.")
    parser.add_argument(
        "--symbols",
        default="PETR4,VALE3,ITUB4,BBAS3",
        help="Lista de símbolos separada por vírgula usada em --mode batch.",
    )
    parser.add_argument("--query", default="PETR", help="Texto usado em --mode search.")
    parser.add_argument("--limit", type=int, default=10, help="Limite usado em --mode search.")
    parser.add_argument("--requests", type=int, default=200, help="Total de requisições medidas.")
    parser.add_argument("--warmup-requests", type=int, default=20, help="Requisições de aquecimento.")
    parser.add_argument("--concurrency", type=int, default=20, help="Quantidade de requisições concorrentes.")
    parser.add_argument("--timeout-seconds", type=float, default=10.0, help="Timeout por requisição.")
    parser.add_argument("--token", default="", help="Bearer token opcional. Se omitido, tenta env.")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emite o resumo final apenas como JSON.",
    )
    return parser


def _format_summary(summary: Mapping[str, Any]) -> str:
    latency = summary["latency_ms"]
    lines = [
        "Stress API summary",
        f"target: {summary['target']['method']} {summary['target']['base_url']}{summary['target']['path']}",
        f"requests: {summary['requests_total']} | concurrency: {summary['target']['concurrency']} | warmup: {summary['target']['warmup_requests']}",
        f"success: {summary['ok_count']} | errors: {summary['error_count']} | success_rate: {summary['success_rate_pct']:.2f}%",
        f"elapsed: {summary['elapsed_seconds']:.2f}s | throughput: {summary['requests_per_second']:.2f} req/s",
        (
            "latency_ms: "
            f"min={latency['min']:.2f} avg={latency['avg']:.2f} p50={latency['p50']:.2f} "
            f"p95={latency['p95']:.2f} p99={latency['p99']:.2f} max={latency['max']:.2f}"
        ),
        f"status_codes: {summary['status_codes']}",
    ]
    top_errors = summary.get("top_errors") or []
    if top_errors:
        lines.append(f"top_errors: {top_errors}")
    return "\n".join(lines)


def main(argv: Iterable[str] | None = None) -> int:
    load_dotenv_once()
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    summary = asyncio.run(run_stress(args))
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(_format_summary(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
