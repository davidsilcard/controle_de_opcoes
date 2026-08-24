from __future__ import annotations

import math
import unicodedata
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

from .db import db_transaction
from .utils import infer_option_type


class PutAssignmentPmRepairError(RuntimeError):
    """Raised when a historical PUT assignment cannot be repaired safely."""


@dataclass(frozen=True)
class PutAssignmentPmRepairPlan:
    put_position_id: int
    holding_id: int
    holding_event_id: int
    quantity_after: int
    previous_avg_price: float
    corrected_avg_price: float
    update_required: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _upper(value: Any) -> str:
    return _text(value).upper()


def _money(value: Any, *, label: str) -> float:
    try:
        amount = float(value)
    except (TypeError, ValueError) as exc:
        raise PutAssignmentPmRepairError(f"{label} invalido.") from exc
    if not math.isfinite(amount):
        raise PutAssignmentPmRepairError(f"{label} invalido.")
    return round(amount, 6)


def _positive_int(value: Any, *, label: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise PutAssignmentPmRepairError(f"{label} invalida.") from exc
    if parsed <= 0:
        raise PutAssignmentPmRepairError(f"{label} precisa ser maior que zero.")
    return parsed


def _is_exercise(value: Any) -> bool:
    normalized = unicodedata.normalize("NFKD", _text(value))
    return "exerc" in normalized.encode("ascii", "ignore").decode().lower()


def _same_money(left: Any, right: Any) -> bool:
    try:
        return round(float(left or 0.0) - float(right or 0.0), 6) == 0.0
    except (TypeError, ValueError):
        return False


def build_put_assignment_pm_repair_plan(
    *,
    put_position: Mapping[str, Any],
    holding: Mapping[str, Any],
    holding_events: Sequence[Mapping[str, Any]],
) -> PutAssignmentPmRepairPlan:
    """Describe the exact PM correction for one confirmed legacy PUT assignment."""

    put_id = _positive_int(put_position.get("id"), label="ID da PUT")
    underlying = _upper(put_position.get("underlying"))
    if infer_option_type(_upper(put_position.get("ticker"))) != "PUT":
        raise PutAssignmentPmRepairError("A posicao informada nao e uma PUT.")
    if _text(put_position.get("strategy_tag")).lower() != "cash_put":
        raise PutAssignmentPmRepairError("A PUT nao pertence a Cash-Covered Put.")
    if _text(put_position.get("status")).lower() != "closed" or not _is_exercise(
        put_position.get("exit_reason")
    ):
        raise PutAssignmentPmRepairError("A PUT precisa estar fechada por exercicio.")
    if len(holding_events) != 1:
        raise PutAssignmentPmRepairError("Era esperado exatamente um evento PUT_ASSIGNMENT vinculado a PUT.")

    event = holding_events[0]
    if _upper(event.get("ticker")) != underlying or _upper(event.get("event_type")) != "PUT_ASSIGNMENT":
        raise PutAssignmentPmRepairError("O evento de estoque nao corresponde a PUT exercida.")
    if _text(event.get("event_date")) != _text(put_position.get("exit_date")):
        raise PutAssignmentPmRepairError("A data do evento de estoque diverge do exercicio.")
    if bool(event.get("is_simulated") or 0) != bool(put_position.get("is_simulated") or 0):
        raise PutAssignmentPmRepairError("Evento e PUT pertencem a modos diferentes.")

    qty_before = int(event.get("quantity_before") or 0)
    qty_delta = _positive_int(event.get("qty_delta"), label="Quantidade exercida")
    qty_after = _positive_int(event.get("quantity_after"), label="Quantidade final")
    if qty_after != qty_before + qty_delta:
        raise PutAssignmentPmRepairError("As quantidades do evento de estoque sao incoerentes.")
    if qty_delta != _positive_int(put_position.get("qty"), label="Quantidade da PUT"):
        raise PutAssignmentPmRepairError("A quantidade do evento diverge da PUT.")
    if qty_before <= 0:
        raise PutAssignmentPmRepairError("Este reparo so atende estoque preexistente com PM confirmado.")

    before_avg = _money(event.get("avg_price_before"), label="PM anterior")
    strike = _money(event.get("price_reference"), label="Strike")
    fees = _money(event.get("fees"), label="Despesas da compra")
    if before_avg <= 0 or strike <= 0 or fees < 0:
        raise PutAssignmentPmRepairError("PM, strike ou despesas do evento sao invalidos.")
    corrected_avg = round(
        ((before_avg * qty_before) + (strike * qty_delta) + fees) / qty_after,
        6,
    )
    if _upper(holding.get("ticker")) != underlying:
        raise PutAssignmentPmRepairError("O estoque consolidado pertence a outro ativo.")
    if bool(holding.get("is_simulated") or 0) != bool(put_position.get("is_simulated") or 0):
        raise PutAssignmentPmRepairError("Estoque e PUT pertencem a modos diferentes.")
    if _positive_int(holding.get("quantity"), label="Quantidade do estoque") != qty_after:
        raise PutAssignmentPmRepairError("O estoque teve movimentos posteriores; reparo automatico bloqueado.")

    current_avg = _money(holding.get("avg_price"), label="PM atual")
    if not (_same_money(current_avg, before_avg) or _same_money(current_avg, corrected_avg)):
        raise PutAssignmentPmRepairError("O PM atual nao corresponde ao estado legado esperado.")
    event_after = _money(event.get("avg_price_after"), label="PM final do evento")
    if not (_same_money(event_after, before_avg) or _same_money(event_after, corrected_avg)):
        raise PutAssignmentPmRepairError("O PM final registrado no evento nao e reconhecido.")

    return PutAssignmentPmRepairPlan(
        put_position_id=put_id,
        holding_id=_positive_int(holding.get("id"), label="ID do estoque"),
        holding_event_id=_positive_int(event.get("id"), label="ID do evento"),
        quantity_after=qty_after,
        previous_avg_price=current_avg,
        corrected_avg_price=corrected_avg,
        update_required=not _same_money(current_avg, corrected_avg)
        or not _same_money(event_after, corrected_avg),
    )


def repair_put_assignment_average_price(*, put_position_id: int, apply: bool = False) -> dict[str, Any]:
    put_id = _positive_int(put_position_id, label="ID da PUT")
    lock = " FOR UPDATE" if apply else ""
    with db_transaction() as conn:
        put_position = conn.execute(
            f"SELECT * FROM positions WHERE id = %s{lock}", (put_id,)
        ).fetchone()
        if put_position is None:
            raise PutAssignmentPmRepairError("PUT nao encontrada.")
        underlying = _upper(put_position.get("underlying"))
        holding = conn.execute(
            f"SELECT * FROM equity_holdings WHERE ticker = %s AND is_simulated = %s{lock}",
            (underlying, 1 if bool(put_position.get("is_simulated") or 0) else 0),
        ).fetchone()
        if holding is None:
            raise PutAssignmentPmRepairError("Estoque consolidado nao encontrado.")
        events = conn.execute(
            f"SELECT * FROM equity_holding_events WHERE related_position_id = %s AND event_type = 'PUT_ASSIGNMENT'{lock}",
            (put_id,),
        ).fetchall()
        plan = build_put_assignment_pm_repair_plan(
            put_position=put_position,
            holding=holding,
            holding_events=events,
        )
        if apply and plan.update_required:
            notes = (
                f"PM corrigido por reparo auditado da PUT exercida #{put_id}; "
                f"PM anterior: R$ {plan.previous_avg_price:.6f}."
            )
            updated_holding = conn.execute(
                "UPDATE equity_holdings SET avg_price = %s, needs_review = 0, notes = %s, updated_at = NOW() WHERE id = %s",
                (plan.corrected_avg_price, notes, plan.holding_id),
            )
            updated_event = conn.execute(
                "UPDATE equity_holding_events SET avg_price_after = %s, notes = %s WHERE id = %s",
                (plan.corrected_avg_price, notes, plan.holding_event_id),
            )
            if updated_holding.rowcount != 1 or updated_event.rowcount != 1:
                raise PutAssignmentPmRepairError("O reparo nao atualizou todos os registros esperados.")
    report = plan.to_dict()
    report["applied"] = bool(apply and plan.update_required)
    return report


__all__ = [
    "PutAssignmentPmRepairError",
    "PutAssignmentPmRepairPlan",
    "build_put_assignment_pm_repair_plan",
    "repair_put_assignment_average_price",
]
