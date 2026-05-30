from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from . import finance
from .tax import build_position_tax_events
from .utils import infer_option_type


class CoveredCallValidationError(ValueError):
    """Erro de dominio para impedir cadastro incoerente de Covered Call."""


@dataclass(frozen=True)
class CoveredCallAuditIssue:
    position_id: int
    ticker: str
    code: str
    message: str


def _raw(value: Any) -> str:
    return str(value or "")


def _norm(value: Any) -> str:
    return _raw(value).strip()


def _norm_upper(value: Any) -> str:
    return _norm(value).upper()


def _norm_lower(value: Any) -> str:
    return _norm(value).lower()


def _money(value: Any) -> float:
    try:
        return round(float(value or 0.0), 2)
    except (TypeError, ValueError):
        return 0.0


def _int_value(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _valid_iso_date(value: Any) -> bool:
    raw = _raw(value)
    text = raw.strip()
    if not text or raw != text:
        return False
    try:
        return dt.date.fromisoformat(text).isoformat() == text
    except ValueError:
        return False


def _option_prefix(ticker: Any) -> str:
    text = _norm_upper(ticker)
    if len(text) < 5:
        return ""
    letters = "".join(ch for ch in text if ch.isalpha())
    return letters[:4] if len(letters) >= 4 else ""


def _underlying_prefix(underlying: Any) -> str:
    text = _norm_upper(underlying)
    letters = "".join(ch for ch in text if ch.isalpha())
    return letters[:4] if len(letters) >= 4 else ""


def _is_covered_call_option(*, ticker: Any, side: Any, strategy_tag: Any) -> bool:
    if _norm_lower(strategy_tag) != "covered_call":
        return False
    if infer_option_type(_norm_upper(ticker)) in {"CALL", "PUT"}:
        return True
    return _norm_lower(side) == "short"


def validate_covered_call_input(
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
    """Bloqueia dados que descaracterizam a venda coberta de CALL."""

    if not _is_covered_call_option(ticker=ticker, side=side, strategy_tag=strategy_tag):
        return

    ticker_norm = _norm_upper(ticker)
    underlying_norm = _norm_upper(underlying)
    if infer_option_type(ticker_norm) != "CALL":
        raise CoveredCallValidationError(
            "Covered Call aceita somente ticker de CALL. Revise ticker e estrategia."
        )
    if _norm_lower(side) != "short":
        raise CoveredCallValidationError(
            "Covered Call de opcao precisa ser cadastrada como posicao vendida."
        )
    if not underlying_norm or underlying_norm == ticker_norm:
        raise CoveredCallValidationError(
            "Covered Call precisa de ativo-base identificado, por exemplo WIZC3."
        )
    ticker_prefix = _option_prefix(ticker_norm)
    underlying_prefix = _underlying_prefix(underlying_norm)
    if ticker_prefix and underlying_prefix and ticker_prefix != underlying_prefix:
        raise CoveredCallValidationError(
            (
                f"Ativo-base incoerente: {ticker_norm} parece pertencer a {ticker_prefix}, "
                f"mas foi informado {underlying_norm}. Revise antes de salvar."
            )
        )
    if _int_value(qty) <= 0:
        raise CoveredCallValidationError("Quantidade da CALL vendida precisa ser maior que zero.")
    if _money(entry_price) <= 0:
        raise CoveredCallValidationError("Preco de entrada da CALL precisa ser maior que zero.")
    if not _valid_iso_date(trade_date):
        raise CoveredCallValidationError("Data de entrada invalida. Use YYYY-MM-DD.")

    status_norm = _norm_lower(status or "open")
    if status_norm == "closed":
        if not _valid_iso_date(exit_date):
            raise CoveredCallValidationError("CALL coberta fechada precisa de data de saida valida.")
        reason = _norm_lower(exit_reason)
        if not reason:
            raise CoveredCallValidationError(
                "CALL coberta fechada precisa informar o motivo: recompra, expiracao ou exercicio."
            )
        exit_price_value = _money(exit_price)
        if "recompra" in reason and exit_price_value <= 0:
            raise CoveredCallValidationError("Recompra de covered_call precisa de preco de saida maior que zero.")
        if ("expira" in reason or "exerc" in reason) and exit_price_value != 0.0:
            raise CoveredCallValidationError("Expiracao ou exercicio de CALL deve fechar com preco zero.")


def _duplicate_key(pos: Mapping[str, Any]) -> tuple[Any, ...] | None:
    if _norm_lower(pos.get("strategy_tag")) != "covered_call":
        return None
    ticker = _norm_upper(pos.get("ticker"))
    if infer_option_type(ticker) != "CALL":
        return None
    if _norm_lower(pos.get("side")) != "short":
        return None
    trade_date = _norm(pos.get("trade_date"))
    if not trade_date:
        return None
    return (
        ticker,
        _norm_upper(pos.get("underlying")),
        trade_date,
        _int_value(pos.get("qty")),
        _money(pos.get("entry_price")),
        bool(pos.get("is_simulated") or 0),
    )


def find_duplicate_covered_call(
    positions: Sequence[Mapping[str, Any]],
    *,
    candidate: Mapping[str, Any],
    current_position_id: int | None = None,
) -> Mapping[str, Any] | None:
    candidate_key = _duplicate_key(candidate)
    if candidate_key is None:
        return None
    for pos in positions:
        try:
            pid = int(pos.get("id") or 0)
        except (TypeError, ValueError):
            pid = 0
        if current_position_id is not None and pid == int(current_position_id):
            continue
        if _duplicate_key(pos) == candidate_key:
            return pos
    return None


def audit_covered_call_positions(
    positions: Sequence[Mapping[str, Any]],
    *,
    ledger_sums: Mapping[int, Mapping[str, float]],
    holding_snapshots: Sequence[Mapping[str, Any]] | None = None,
    holding_events: Sequence[Mapping[str, Any]] | None = None,
) -> list[CoveredCallAuditIssue]:
    issues: list[CoveredCallAuditIssue] = []
    events_by_position: dict[int, list[Mapping[str, Any]]] = {}
    for event in holding_events or []:
        rid = event.get("related_position_id")
        if rid is None:
            continue
        events_by_position.setdefault(_int_value(rid), []).append(event)

    holding_by_key = {
        (_norm_upper(item.get("ticker")), bool(item.get("is_simulated") or 0)): item
        for item in (holding_snapshots or [])
        if _norm_upper(item.get("ticker"))
    }
    duplicate_buckets: dict[tuple[Any, ...], list[Mapping[str, Any]]] = {}
    for pos in positions:
        key = _duplicate_key(pos)
        if key is not None:
            duplicate_buckets.setdefault(key, []).append(pos)

    def add(pos: Mapping[str, Any], code: str, message: str) -> None:
        pid = _int_value(pos.get("id"))
        ticker = _norm_upper(pos.get("ticker")) or f"#{pid}"
        issues.append(
            CoveredCallAuditIssue(
                position_id=pid,
                ticker=ticker,
                code=code,
                message=message,
            )
        )

    for pos in positions:
        if _norm_lower(pos.get("strategy_tag")) != "covered_call":
            continue

        pid = _int_value(pos.get("id"))
        ticker = _norm_upper(pos.get("ticker"))
        side = _norm_lower(pos.get("side"))
        status = _norm_lower(pos.get("status"))
        opt_type = infer_option_type(ticker)
        sums = ledger_sums.get(pid, {})

        key = _duplicate_key(pos)
        if key is not None and len(duplicate_buckets.get(key, [])) > 1:
            add(pos, "DUPLICIDADE_PROVAVEL", "Existe outra covered_call com mesmo ticker, data, quantidade, preco e modo.")

        if opt_type == "CALL" or side == "short":
            try:
                validate_covered_call_input(
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
            except CoveredCallValidationError as exc:
                add(pos, "VALIDACAO", str(exc))

        if opt_type == "CALL" and side == "short":
            expected_premium = finance.calculate_option_premium(
                entry_price=float(pos.get("entry_price") or 0.0),
                qty=_int_value(pos.get("qty")),
                fees=float(pos.get("fees") or 0.0),
            )
            actual_premium = sums.get(finance.TransactionType.PREMIUM.value)
            if round(float(actual_premium or 0.0) - expected_premium, 2) != 0:
                add(pos, "PREMIO_DIVERGENTE", "Premio no ledger nao bate com preco, quantidade e taxas.")

            expected_realized = round(
                sum(float(event.amount) for event in build_position_tax_events(pos)),
                2,
            )
            actual_realized = sums.get(finance.TransactionType.REALIZED.value)
            if expected_realized and round(float(actual_realized or 0.0) - expected_realized, 2) != 0:
                add(pos, "REALIZED_DIVERGENTE", "Resultado realizado esperado nao bate com o ledger.")

            reason = _norm_lower(pos.get("exit_reason"))
            if status == "closed" and "recompra" in reason:
                if sums.get(finance.TransactionType.BUY.value) is None:
                    add(pos, "RECOMPRA_SEM_LEDGER", "Fechamento por recompra nao tem BUY no ledger.")
            if status == "closed" and "exerc" in reason:
                if sums.get(finance.TransactionType.SELL.value) is None:
                    add(pos, "EXERCICIO_SEM_SELL", "Exercicio de CALL nao tem venda SELL no ledger.")
                related_events = events_by_position.get(pid, [])
                if not any(_norm_upper(event.get("event_type")) == "CALL_EXERCISE" for event in related_events):
                    add(pos, "EXERCICIO_SEM_ESTOQUE", "Exercicio de CALL nao baixou o estoque consolidado.")

        if opt_type not in {"CALL", "PUT"} and status == "open":
            underlying = _norm_upper(pos.get("underlying") or pos.get("ticker"))
            snapshot = holding_by_key.get((underlying, bool(pos.get("is_simulated") or 0)))
            if snapshot is not None and _int_value(snapshot.get("shares_total")) <= 0:
                add(pos, "LOTE_ABERTO_SEM_ESTOQUE", "Lote legado aberto, mas o estoque consolidado do ativo esta zerado.")

    for snapshot in holding_snapshots or []:
        if _int_value(snapshot.get("coverage_gap")) > 0:
            pseudo_pos = {
                "id": 0,
                "ticker": snapshot.get("ticker"),
            }
            add(
                pseudo_pos,
                "COBERTURA_INSUFICIENTE",
                "Reserva de calls maior que o estoque consolidado disponivel.",
            )

    return issues


__all__ = [
    "CoveredCallAuditIssue",
    "CoveredCallValidationError",
    "audit_covered_call_positions",
    "find_duplicate_covered_call",
    "validate_covered_call_input",
]
