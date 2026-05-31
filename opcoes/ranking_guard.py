from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from . import finance
from .utils import infer_option_type


class RankingValidationError(ValueError):
    """Erro de dominio para impedir cadastro incoerente de opcao comprada."""


@dataclass(frozen=True)
class RankingAuditIssue:
    position_id: int
    ticker: str
    code: str
    message: str


def _norm(value: Any) -> str:
    return str(value or "").strip()


def _norm_upper(value: Any) -> str:
    return _norm(value).upper()


def _norm_lower(value: Any) -> str:
    return _norm(value).lower()


def _valid_iso_date(value: Any) -> bool:
    text = _norm(value)
    if not text:
        return False
    try:
        return dt.date.fromisoformat(text).isoformat() == text
    except ValueError:
        return False


def validate_ranking_option_input(
    *,
    ticker: Any,
    underlying: Any,
    trade_date: Any,
    qty: Any,
    entry_price: Any,
    side: Any,
    strategy_tag: Any,
) -> None:
    if _norm_lower(strategy_tag) != "ranking":
        return
    ticker_norm = _norm_upper(ticker)
    if infer_option_type(ticker_norm) not in {"CALL", "PUT"}:
        raise RankingValidationError("Aposta / Ranking aceita somente ticker de opcao.")
    if _norm_lower(side) != "long":
        raise RankingValidationError("Aposta / Ranking precisa ser cadastrada como opcao comprada.")
    if not _norm_upper(underlying) or _norm_upper(underlying) == ticker_norm:
        raise RankingValidationError("Aposta / Ranking precisa de ativo-base identificado.")
    try:
        qty_int = int(qty or 0)
    except (TypeError, ValueError):
        qty_int = 0
    try:
        price = float(entry_price or 0.0)
    except (TypeError, ValueError):
        price = 0.0
    if qty_int <= 0:
        raise RankingValidationError("Quantidade da opcao comprada precisa ser maior que zero.")
    if price <= 0:
        raise RankingValidationError("Preco de entrada da opcao comprada precisa ser maior que zero.")
    if not _valid_iso_date(trade_date):
        raise RankingValidationError("Data de entrada invalida. Use YYYY-MM-DD.")


def audit_ranking_positions(
    positions: Sequence[Mapping[str, Any]],
    *,
    ledger_sums: Mapping[int, Mapping[str, float]],
) -> list[RankingAuditIssue]:
    issues: list[RankingAuditIssue] = []
    for pos in positions:
        if _norm_lower(pos.get("strategy_tag")) != "ranking":
            continue
        pid = int(pos.get("id") or 0)
        ticker = _norm_upper(pos.get("ticker")) or f"#{pid}"

        def add(code: str, message: str) -> None:
            issues.append(RankingAuditIssue(pid, ticker, code, message))

        try:
            validate_ranking_option_input(
                ticker=pos.get("ticker"),
                underlying=pos.get("underlying"),
                trade_date=pos.get("trade_date"),
                qty=pos.get("qty"),
                entry_price=pos.get("entry_price"),
                side=pos.get("side"),
                strategy_tag=pos.get("strategy_tag"),
            )
        except RankingValidationError as exc:
            add("VALIDACAO", str(exc))

        if infer_option_type(ticker) in {"CALL", "PUT"} and _norm_lower(pos.get("side")) == "long":
            sums = ledger_sums.get(pid, {})
            expected_buy = round(
                finance.calculate_option_purchase(
                    entry_price=float(pos.get("entry_price") or 0.0),
                    qty=int(pos.get("qty") or 0),
                    fees=finance.long_option_entry_buy_fees(pos),
                ),
                2,
            )
            actual_buy = sums.get(finance.TransactionType.BUY.value)
            if round(float(actual_buy or 0.0) - expected_buy, 2) != 0:
                add("COMPRA_SEM_LEDGER", "Compra da opcao nao bate com o ledger BUY.")
    return issues


__all__ = [
    "RankingAuditIssue",
    "RankingValidationError",
    "audit_ranking_positions",
    "validate_ranking_option_input",
]
