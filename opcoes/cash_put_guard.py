from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence

from . import finance
from .tax import build_position_tax_events
from .utils import infer_option_type


class CashPutValidationError(ValueError):
    """Erro de dominio para impedir cadastro incoerente de Cash-Covered Put."""


@dataclass(frozen=True)
class CashPutAuditIssue:
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


def _money(value: Any) -> float:
    try:
        return round(float(value or 0.0), 2)
    except (TypeError, ValueError):
        return 0.0


def _reason_has(value: Any, token: str) -> bool:
    text = _norm_lower(value)
    return token in text


def validate_cash_put_input(
    *,
    ticker: Any,
    underlying: Any,
    trade_date: Any,
    qty: Any,
    entry_price: Any,
    side: Any,
    strategy_tag: Any,
    status: Any = "open",
    exit_date: Any = None,
    exit_price: Any = None,
    exit_reason: Any = None,
) -> None:
    """Bloqueia dados que descaracterizam a venda de PUT coberta por caixa."""

    if _norm_lower(strategy_tag) != "cash_put":
        return

    ticker_norm = _norm_upper(ticker)
    underlying_norm = _norm_upper(underlying)
    if infer_option_type(ticker_norm) != "PUT":
        raise CashPutValidationError(
            "Cash-Covered Put aceita somente ticker de PUT. Revise ticker e estrategia."
        )
    if _norm_lower(side) != "short":
        raise CashPutValidationError(
            "Cash-Covered Put precisa ser cadastrada como posicao vendida."
        )
    if not underlying_norm or underlying_norm == ticker_norm:
        raise CashPutValidationError(
            "Cash-Covered Put precisa de ativo-base identificado, por exemplo PETR4."
        )
    try:
        qty_int = int(qty or 0)
    except (TypeError, ValueError):
        qty_int = 0
    if qty_int <= 0:
        raise CashPutValidationError("Quantidade da PUT vendida precisa ser maior que zero.")
    if _money(entry_price) <= 0:
        raise CashPutValidationError("Preco de entrada da PUT precisa ser maior que zero.")
    if not _valid_iso_date(trade_date):
        raise CashPutValidationError("Data de entrada invalida. Use YYYY-MM-DD.")

    status_norm = _norm_lower(status or "open")
    if status_norm == "closed":
        if not _valid_iso_date(exit_date):
            raise CashPutValidationError("Posicao cash_put fechada precisa de data de saida valida.")
        reason = _norm_lower(exit_reason)
        if not reason:
            raise CashPutValidationError(
                "Posicao cash_put fechada precisa informar o motivo: recompra, expiracao ou exercicio."
            )
        exit_price_value = _money(exit_price)
        if "recompra" in reason and exit_price_value <= 0:
            raise CashPutValidationError("Recompra de cash_put precisa de preco de saida maior que zero.")
        if ("expira" in reason or "exerc" in reason) and exit_price_value != 0.0:
            raise CashPutValidationError("Expiracao ou exercicio de cash_put deve fechar com preco zero.")


def audit_cash_put_positions(
    positions: Sequence[Mapping[str, Any]],
    *,
    ledger_sums: Mapping[int, Mapping[str, float]],
) -> list[CashPutAuditIssue]:
    issues: list[CashPutAuditIssue] = []

    for pos in positions:
        if _norm_lower(pos.get("strategy_tag")) != "cash_put":
            continue

        pid = int(pos.get("id") or 0)
        ticker = _norm_upper(pos.get("ticker"))
        sums = ledger_sums.get(pid, {})

        def add(code: str, message: str) -> None:
            issues.append(
                CashPutAuditIssue(
                    position_id=pid,
                    ticker=ticker or f"#{pid}",
                    code=code,
                    message=message,
                )
            )

        try:
            validate_cash_put_input(
                ticker=pos.get("ticker"),
                underlying=pos.get("underlying"),
                trade_date=pos.get("trade_date"),
                qty=pos.get("qty"),
                entry_price=pos.get("entry_price"),
                side=pos.get("side"),
                strategy_tag=pos.get("strategy_tag"),
                status=pos.get("status") or "open",
                exit_date=pos.get("exit_date"),
                exit_price=pos.get("exit_price"),
                exit_reason=pos.get("exit_reason"),
            )
        except CashPutValidationError as exc:
            add("VALIDACAO", str(exc))

        expected_premium = finance.calculate_option_premium(
            entry_price=float(pos.get("entry_price") or 0.0),
            qty=int(pos.get("qty") or 0),
            fees=float(pos.get("fees") or 0.0),
        )
        actual_premium = sums.get(finance.TransactionType.PREMIUM.value)
        if round(float(actual_premium or 0.0) - expected_premium, 2) != 0:
            add("PREMIO_DIVERGENTE", "Premio no ledger nao bate com preco, quantidade e taxas.")

        expected_realized = round(
            sum(float(event.amount) for event in build_position_tax_events(pos)),
            2,
        )
        actual_realized = sums.get(finance.TransactionType.REALIZED.value)
        if expected_realized and round(float(actual_realized or 0.0) - expected_realized, 2) != 0:
            add("REALIZED_DIVERGENTE", "Resultado realizado esperado nao bate com o ledger.")

        status_norm = _norm_lower(pos.get("status"))
        if status_norm == "closed" and _money(pos.get("exit_price")) > 0:
            if sums.get(finance.TransactionType.BUY.value) is None:
                add("RECOMPRA_SEM_LEDGER", "Fechamento com preco de saida nao tem recompra no ledger.")

        if status_norm == "closed" and _reason_has(pos.get("exit_reason"), "exerc"):
            if sums.get(finance.TransactionType.ASSIGNMENT.value) is None:
                add("EXERCICIO_SEM_ASSIGN", "Exercicio de PUT nao tem lancamento ASSIGN no ledger.")

    return issues
