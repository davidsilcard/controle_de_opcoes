from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from . import finance
from .cash_put_guard import audit_cash_put_positions
from .covered_call_guard import audit_covered_call_positions
from .ranking_guard import audit_ranking_positions
from .utils import infer_option_type


@dataclass(frozen=True)
class PositionsAuditIssue:
    severity: str
    scope: str
    position_id: int
    ticker: str
    code: str
    message: str
    action: str


def _norm(value: Any) -> str:
    return str(value or "").strip()


def _norm_upper(value: Any) -> str:
    return _norm(value).upper()


def _norm_lower(value: Any) -> str:
    return _norm(value).lower()


def _money_or_none(value: Any) -> float | None:
    if value is None or _norm(value) == "":
        return None
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


def _valid_iso_date(value: Any) -> bool:
    text = _norm(value)
    if not text:
        return False
    try:
        return dt.date.fromisoformat(text).isoformat() == text
    except ValueError:
        return False


def _int_value(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _is_stock_position(pos: Mapping[str, Any]) -> bool:
    ticker = _norm_upper(pos.get("ticker"))
    return bool(ticker) and infer_option_type(ticker) not in {"CALL", "PUT"}


def _has_exercised_call_sell_for_stock(
    pos: Mapping[str, Any],
    *,
    positions: Sequence[Mapping[str, Any]],
    ledger_sums: Mapping[int, Mapping[str, float]],
) -> bool:
    underlying = _norm_upper(pos.get("underlying") or pos.get("ticker"))
    exit_date = _norm(pos.get("exit_date"))
    mode = bool(pos.get("is_simulated") or 0)
    if not underlying or not exit_date:
        return False

    for candidate in positions:
        if bool(candidate.get("is_simulated") or 0) != mode:
            continue
        if _norm_lower(candidate.get("strategy_tag")) != "covered_call":
            continue
        if infer_option_type(_norm_upper(candidate.get("ticker"))) != "CALL":
            continue
        if _norm_lower(candidate.get("side")) != "short":
            continue
        if _norm_upper(candidate.get("underlying")) != underlying:
            continue
        if _norm_lower(candidate.get("status")) != "closed":
            continue
        if _norm(candidate.get("exit_date")) != exit_date:
            continue
        if "exerc" not in _norm_lower(candidate.get("exit_reason")):
            continue
        sums = ledger_sums.get(_int_value(candidate.get("id")), {})
        if sums.get(finance.TransactionType.SELL.value) is not None:
            return True
    return False


def _is_documented_technical_consolidation(
    pos: Mapping[str, Any],
    *,
    positions: Sequence[Mapping[str, Any]],
    ledger_sums: Mapping[int, Mapping[str, float]],
) -> bool:
    if _norm_lower(pos.get("strategy_tag")) != "covered_call":
        return False
    if _norm_lower(pos.get("trade_type")) != "stock":
        return False
    if _norm_lower(pos.get("side")) != "long":
        return False
    if _norm_lower(pos.get("status")) != "closed":
        return False
    if not _is_stock_position(pos):
        return False

    reason_notes = (
        f"{_norm_lower(pos.get('exit_reason'))} {_norm_lower(pos.get('notes'))}"
    )
    if "consolid" not in reason_notes and "baixa economica" not in reason_notes:
        return False
    return _has_exercised_call_sell_for_stock(
        pos,
        positions=positions,
        ledger_sums=ledger_sums,
    )


def audit_positions_page(
    positions: Sequence[Mapping[str, Any]],
    *,
    ledger_sums: Mapping[int, Mapping[str, float]],
    holding_snapshots: Sequence[Mapping[str, Any]] | None = None,
    holding_events: Sequence[Mapping[str, Any]] | None = None,
) -> list[PositionsAuditIssue]:
    issues: list[PositionsAuditIssue] = []

    def add(
        pos: Mapping[str, Any],
        code: str,
        message: str,
        *,
        severity: str = "BLOQUEIO",
        scope: str = "positions",
        action: str = "Corrija a posicao ou confira a nota de corretagem antes de continuar.",
    ) -> None:
        pid = _int_value(pos.get("id"))
        ticker = _norm_upper(pos.get("ticker")) or f"#{pid}"
        issues.append(
            PositionsAuditIssue(
                severity=severity,
                scope=scope,
                position_id=pid,
                ticker=ticker,
                code=code,
                message=message,
                action=action,
            )
        )

    for pos in positions:
        pid = _int_value(pos.get("id"))
        if pid <= 0:
            continue
        status = _norm_lower(pos.get("status"))

        if not _valid_iso_date(pos.get("trade_date")):
            add(
                pos,
                "DATA_ENTRADA_INVALIDA",
                "Data de entrada invalida. Use YYYY-MM-DD.",
            )

        if status not in {"open", "closed"}:
            add(pos, "STATUS_INVALIDO", "Status precisa ser open ou closed.")
            continue

        if status == "open":
            if (
                _norm(pos.get("exit_date"))
                or _money_or_none(pos.get("exit_price")) is not None
            ):
                add(
                    pos,
                    "ABERTA_COM_SAIDA",
                    "Posicao aberta nao pode ter data ou preco de saida preenchidos.",
                )
            continue

        if not _valid_iso_date(pos.get("exit_date")):
            add(
                pos,
                "FECHADA_SEM_DATA",
                "Posicao fechada precisa de data de saida valida.",
            )
        if not _norm(pos.get("exit_reason")):
            add(
                pos,
                "FECHADA_SEM_MOTIVO",
                "Posicao fechada precisa informar o motivo da baixa.",
            )
        if _money_or_none(pos.get("exit_price")) is None:
            if not _is_documented_technical_consolidation(
                pos,
                positions=positions,
                ledger_sums=ledger_sums,
            ):
                add(
                    pos,
                    "FECHADA_SEM_PRECO",
                    "Posicao fechada sem preco de saida.",
                    severity="PRECISA_NOTA",
                    action=(
                        "Informe o preco da nota ou marque a baixa como consolidacao tecnica "
                        "somente quando outra posicao ja tiver registrado a venda real."
                    ),
                )

    for item in audit_cash_put_positions(positions, ledger_sums=ledger_sums):
        issues.append(
            PositionsAuditIssue(
                severity="BLOQUEIO",
                scope="cash_put",
                position_id=item.position_id,
                ticker=item.ticker,
                code=item.code,
                message=item.message,
                action="Revise a posicao na estrategia Cash-Covered Put.",
            )
        )
    for item in audit_covered_call_positions(
        positions,
        ledger_sums=ledger_sums,
        holding_snapshots=holding_snapshots,
        holding_events=holding_events,
    ):
        issues.append(
            PositionsAuditIssue(
                severity="BLOQUEIO",
                scope="covered_call",
                position_id=item.position_id,
                ticker=item.ticker,
                code=item.code,
                message=item.message,
                action="Revise a posicao na estrategia Covered Call.",
            )
        )
    for item in audit_ranking_positions(positions, ledger_sums=ledger_sums):
        issues.append(
            PositionsAuditIssue(
                severity="BLOQUEIO",
                scope="ranking",
                position_id=item.position_id,
                ticker=item.ticker,
                code=item.code,
                message=item.message,
                action="Revise a posicao na estrategia Aposta / Ranking.",
            )
        )

    return issues


__all__ = [
    "PositionsAuditIssue",
    "audit_positions_page",
]
