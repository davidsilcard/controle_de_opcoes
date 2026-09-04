from __future__ import annotations

import datetime as dt
import math
from dataclasses import asdict, dataclass
from typing import Any, Mapping

from .db import db_transaction
from .portfolio import _ensure_tables
from .utils import infer_option_type


class ContractAdjustmentRepairError(RuntimeError):
    """Raised when documented contract metadata cannot be recorded safely."""


@dataclass(frozen=True)
class ContractAdjustmentRepairPlan:
    position_id: int
    ticker: str
    original_strike: float
    adjusted_strike: float
    adjustment_date: str
    update_required: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _money(value: Any, *, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ContractAdjustmentRepairError(f"{label} inválido.") from exc
    if result <= 0 or not math.isfinite(result):
        raise ContractAdjustmentRepairError(f"{label} deve ser maior que zero.")
    return round(result, 6)


def _date(value: Any) -> str:
    try:
        return dt.date.fromisoformat(str(value or "").strip()).isoformat()
    except ValueError as exc:
        raise ContractAdjustmentRepairError("Data do ajuste inválida. Use YYYY-MM-DD.") from exc


def _same_money(left: Any, right: Any) -> bool:
    try:
        return round(float(left or 0.0) - float(right or 0.0), 6) == 0.0
    except (TypeError, ValueError):
        return False


def build_contract_adjustment_repair_plan(
    *,
    position: Mapping[str, Any],
    original_strike: Any,
    adjusted_strike: Any,
    adjustment_date: Any,
) -> ContractAdjustmentRepairPlan:
    try:
        position_id = int(position.get("id") or 0)
    except (TypeError, ValueError) as exc:
        raise ContractAdjustmentRepairError("ID da posição inválido.") from exc
    if position_id <= 0:
        raise ContractAdjustmentRepairError("ID da posição inválido.")
    ticker = str(position.get("ticker") or "").strip().upper()
    if infer_option_type(ticker) not in {"CALL", "PUT"}:
        raise ContractAdjustmentRepairError("A posição informada não é uma opção.")
    if str(position.get("side") or "").strip().lower() != "short":
        raise ContractAdjustmentRepairError("O ajuste documental só atende opções vendidas.")
    if str(position.get("strategy_tag") or "").strip().lower() not in {"covered_call", "cash_put"}:
        raise ContractAdjustmentRepairError("A posição não pertence a uma estratégia de opção vendida.")
    original = _money(original_strike, label="Strike original")
    adjusted = _money(adjusted_strike, label="Strike ajustado")
    date = _date(adjustment_date)
    return ContractAdjustmentRepairPlan(
        position_id=position_id,
        ticker=ticker,
        original_strike=original,
        adjusted_strike=adjusted,
        adjustment_date=date,
        update_required=any(
            (
                not _same_money(position.get("contract_strike"), original),
                not _same_money(position.get("contract_adjusted_strike"), adjusted),
                str(position.get("contract_adjustment_date") or "").strip() != date,
            )
        ),
    )


def repair_contract_adjustment(
    *,
    position_id: int,
    original_strike: Any,
    adjusted_strike: Any,
    adjustment_date: Any,
    source_ref: str,
    apply: bool = False,
) -> dict[str, Any]:
    source = str(source_ref or "").strip()
    if not source:
        raise ContractAdjustmentRepairError("Informe a referência documental do ajuste.")
    try:
        resolved_id = int(position_id)
    except (TypeError, ValueError) as exc:
        raise ContractAdjustmentRepairError("ID da posição inválido.") from exc
    if resolved_id <= 0:
        raise ContractAdjustmentRepairError("ID da posição inválido.")
    lock = " FOR UPDATE" if apply else ""
    with db_transaction() as conn:
        _ensure_tables(conn, commit=False)
        position = conn.execute(f"SELECT * FROM positions WHERE id = %s{lock}", (resolved_id,)).fetchone()
        if position is None:
            raise ContractAdjustmentRepairError("Posição não encontrada.")
        plan = build_contract_adjustment_repair_plan(
            position=position,
            original_strike=original_strike,
            adjusted_strike=adjusted_strike,
            adjustment_date=adjustment_date,
        )
        if apply and plan.update_required:
            note = (
                f"Strike original R$ {plan.original_strike:.2f}; strike ajustado R$ {plan.adjusted_strike:.2f} "
                f"em {plan.adjustment_date}."
            )
            result = conn.execute(
                """
                UPDATE positions
                SET contract_strike = %s,
                    contract_adjusted_strike = %s,
                    contract_adjustment_date = %s,
                    performance_source_ref = %s,
                    performance_evidence_note = %s,
                    performance_evidence_state = 'pending'
                WHERE id = %s
                """,
                (
                    plan.original_strike,
                    plan.adjusted_strike,
                    plan.adjustment_date,
                    source,
                    note,
                    plan.position_id,
                ),
            )
            if result.rowcount != 1:
                raise ContractAdjustmentRepairError("A posição não foi atualizada.")
    result = plan.to_dict()
    result["applied"] = bool(apply and plan.update_required)
    return result


__all__ = [
    "ContractAdjustmentRepairError",
    "ContractAdjustmentRepairPlan",
    "build_contract_adjustment_repair_plan",
    "repair_contract_adjustment",
]
