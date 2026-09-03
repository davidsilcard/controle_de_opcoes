from __future__ import annotations

import datetime as dt
import math
import unicodedata
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

from .db import db_transaction
from .portfolio import _ensure_tables
from .utils import infer_option_type


class CashPutExerciseRepairError(RuntimeError):
    """Raised when one audited PUT exercise cannot be repaired safely."""


@dataclass(frozen=True)
class CashPutExerciseRepairPlan:
    put_position_id: int
    holding_id: int
    holding_event_id: int
    assignment_ledger_id: int
    realized_ledger_id: int
    exercise_date: str
    original_strike: float
    exercise_strike: float
    purchase_fees: float
    assignment_amount: float
    holding_events_rebased: tuple[int, ...]
    update_required: bool

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["holding_events_rebased"] = list(self.holding_events_rebased)
        return result


def _text(value: Any) -> str:
    return str(value or "").strip()


def _upper(value: Any) -> str:
    return _text(value).upper()


def _same_money(left: Any, right: Any) -> bool:
    try:
        return round(float(left or 0.0) - float(right or 0.0), 6) == 0.0
    except (TypeError, ValueError):
        return False


def _money(value: Any, *, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise CashPutExerciseRepairError(f"{label} inválido.") from exc
    if result <= 0 or not math.isfinite(result):
        raise CashPutExerciseRepairError(f"{label} deve ser maior que zero.")
    return round(result, 6)


def _positive_int(value: Any, *, label: str) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise CashPutExerciseRepairError(f"{label} inválida.") from exc
    if result <= 0:
        raise CashPutExerciseRepairError(f"{label} precisa ser maior que zero.")
    return result


def _date(value: Any, *, label: str) -> str:
    try:
        return dt.date.fromisoformat(_text(value)).isoformat()
    except ValueError as exc:
        raise CashPutExerciseRepairError(f"{label} inválida. Use YYYY-MM-DD.") from exc


def _is_exercise(value: Any) -> bool:
    normalized = unicodedata.normalize("NFKD", _text(value)).encode("ascii", "ignore").decode()
    return "exerc" in normalized.lower()


def _rebase_event_before_values(
    *,
    events: Sequence[Mapping[str, Any]],
    assignment_event_id: int,
    exercise_date: str,
    exercise_strike: float,
    purchase_fees: float,
) -> tuple[dict[int, tuple[int, float | None]], tuple[int, ...]]:
    """Rebase only historical *before* references after a corrected acquisition.

    Later MANUAL_SET rows preserve their declared final balance/PM.  We only make
    their `quantity_before` and `avg_price_before` truthful again, never replace a
    broker-confirmed balance with an inferred calculation.
    """

    ordered = sorted(events, key=lambda item: (_text(item.get("event_date")), int(item.get("id") or 0)))
    assignment_index = next(
        (index for index, event in enumerate(ordered) if int(event.get("id") or 0) == assignment_event_id),
        None,
    )
    if assignment_index is None:
        raise CashPutExerciseRepairError("Evento de aquisição não encontrado na cadeia de estoque.")
    if assignment_index != 0:
        raise CashPutExerciseRepairError(
            "Há movimento de estoque anterior à PUT; este reparo exige uma cadeia iniciada pela aquisição auditada."
        )

    current_qty = 0
    current_avg: float | None = None
    updates: dict[int, tuple[int, float | None]] = {}
    rebased: list[int] = []
    for index, event in enumerate(ordered):
        event_id = _positive_int(event.get("id"), label="ID do evento de estoque")
        event_date = _date(event.get("event_date"), label="Data do evento de estoque")
        if index == assignment_index:
            if _upper(event.get("event_type")) != "PUT_ASSIGNMENT":
                raise CashPutExerciseRepairError("O evento vinculado não é uma aquisição por exercício de PUT.")
            if event_date < exercise_date:
                raise CashPutExerciseRepairError("A nova data do exercício ficaria após um evento de estoque já registrado.")
            qty_delta = _positive_int(event.get("qty_delta"), label="Quantidade exercida")
            current_qty += qty_delta
            current_avg = round(((exercise_strike * qty_delta) + purchase_fees) / qty_delta, 6)
            continue

        before_qty = int(event.get("quantity_before") or 0)
        before_avg = event.get("avg_price_before")
        expected_before_avg = current_avg if current_qty > 0 else None
        if before_qty != current_qty or not _same_money(before_avg, expected_before_avg):
            updates[event_id] = (current_qty, expected_before_avg)
            rebased.append(event_id)

        after_qty = int(event.get("quantity_after") or 0)
        qty_delta = int(event.get("qty_delta") or 0)
        if after_qty != current_qty + qty_delta or after_qty < 0:
            raise CashPutExerciseRepairError(
                f"Evento de estoque #{event_id} tem quantidade incoerente; reparo automático bloqueado."
            )
        after_avg_raw = event.get("avg_price_after")
        if after_qty > 0 and after_avg_raw is None:
            raise CashPutExerciseRepairError(
                f"Evento de estoque #{event_id} não tem PM final; reparo automático bloqueado."
            )
        current_qty = after_qty
        current_avg = float(after_avg_raw) if after_qty > 0 else None
    return updates, tuple(rebased)


def build_cash_put_exercise_repair_plan(
    *,
    put_position: Mapping[str, Any],
    holding: Mapping[str, Any],
    holding_events: Sequence[Mapping[str, Any]],
    assignment_transactions: Sequence[Mapping[str, Any]],
    realized_transactions: Sequence[Mapping[str, Any]],
    exercise_date: Any,
    original_strike: Any,
    exercise_strike: Any,
    purchase_fees: Any,
) -> CashPutExerciseRepairPlan:
    put_id = _positive_int(put_position.get("id"), label="ID da PUT")
    qty = _positive_int(put_position.get("qty"), label="Quantidade da PUT")
    resolved_date = _date(exercise_date, label="Data do exercício")
    original = _money(original_strike, label="Strike original")
    exercised = _money(exercise_strike, label="Strike aplicado no exercício")
    fees = _money(purchase_fees, label="Despesas da compra")
    if infer_option_type(_upper(put_position.get("ticker"))) != "PUT":
        raise CashPutExerciseRepairError("A posição informada não é uma PUT.")
    if _text(put_position.get("strategy_tag")).lower() != "cash_put":
        raise CashPutExerciseRepairError("A PUT não pertence a Cash-Covered Put.")
    if _text(put_position.get("status")).lower() != "closed" or not _is_exercise(put_position.get("exit_reason")):
        raise CashPutExerciseRepairError("A PUT precisa estar encerrada por exercício.")
    underlying = _upper(put_position.get("underlying"))
    if _upper(holding.get("ticker")) != underlying:
        raise CashPutExerciseRepairError("O estoque consolidado não pertence ao ativo-base da PUT.")
    if bool(holding.get("is_simulated") or 0) != bool(put_position.get("is_simulated") or 0):
        raise CashPutExerciseRepairError("PUT e estoque pertencem a modos diferentes.")

    linked_events = [
        event for event in holding_events
        if int(event.get("related_position_id") or 0) == put_id
        and _upper(event.get("event_type")) == "PUT_ASSIGNMENT"
    ]
    if len(linked_events) != 1:
        raise CashPutExerciseRepairError("Era esperado exatamente um evento PUT_ASSIGNMENT vinculado à posição.")
    event = linked_events[0]
    event_id = _positive_int(event.get("id"), label="ID do evento de estoque")
    if _upper(event.get("ticker")) != underlying:
        raise CashPutExerciseRepairError("O evento de estoque pertence a outro ativo.")
    if int(event.get("qty_delta") or 0) != qty:
        raise CashPutExerciseRepairError("A quantidade do evento de estoque diverge da PUT.")

    if len(assignment_transactions) != 1 or len(realized_transactions) != 1:
        raise CashPutExerciseRepairError("A PUT precisa ter exatamente um ASSIGN e um REALIZED no ledger.")
    assignment = assignment_transactions[0]
    realized = realized_transactions[0]
    assignment_id = _positive_int(assignment.get("id"), label="ID do ASSIGN")
    realized_id = _positive_int(realized.get("id"), label="ID do REALIZED")
    expected_assignment = -round((exercised * qty) + fees, 2)
    old_gross_assignment = -round(exercised * qty, 2)
    if not (_same_money(assignment.get("amount"), old_gross_assignment) or _same_money(assignment.get("amount"), expected_assignment)):
        raise CashPutExerciseRepairError("O ASSIGN atual não corresponde ao valor bruto ou líquido documentado.")

    before_updates, rebased = _rebase_event_before_values(
        events=holding_events,
        assignment_event_id=event_id,
        exercise_date=resolved_date,
        exercise_strike=exercised,
        purchase_fees=fees,
    )
    final_event = sorted(holding_events, key=lambda item: (_text(item.get("event_date")), int(item.get("id") or 0)))[-1]
    if int(holding.get("quantity") or 0) != int(final_event.get("quantity_after") or 0) or not _same_money(
        holding.get("avg_price"), final_event.get("avg_price_after")
    ):
        raise CashPutExerciseRepairError(
            "O saldo consolidado atual diverge do último evento; reparo automático bloqueado."
        )

    assignment_date = _text(assignment.get("date"))
    realized_date = _text(realized.get("date"))
    position_date = _text(put_position.get("exit_date"))
    event_date = _text(event.get("event_date"))
    expected_event_avg = round(((exercised * qty) + fees) / qty, 6)
    update_required = any(
        (
            position_date != resolved_date,
            event_date != resolved_date,
            assignment_date != resolved_date,
            realized_date != resolved_date,
            not _same_money(event.get("price_reference"), exercised),
            not _same_money(event.get("fees"), fees),
            not _same_money(event.get("avg_price_after"), expected_event_avg),
            not _same_money(assignment.get("amount"), expected_assignment),
            not _same_money(put_position.get("contract_strike"), original),
            not _same_money(put_position.get("contract_exercise_strike"), exercised),
            bool(before_updates),
        )
    )
    return CashPutExerciseRepairPlan(
        put_position_id=put_id,
        holding_id=_positive_int(holding.get("id"), label="ID do estoque"),
        holding_event_id=event_id,
        assignment_ledger_id=assignment_id,
        realized_ledger_id=realized_id,
        exercise_date=resolved_date,
        original_strike=original,
        exercise_strike=exercised,
        purchase_fees=fees,
        assignment_amount=expected_assignment,
        holding_events_rebased=rebased,
        update_required=update_required,
    )


def repair_cash_put_exercise(
    *,
    put_position_id: int,
    exercise_date: Any,
    original_strike: Any,
    exercise_strike: Any,
    purchase_fees: Any,
    source_ref: str,
    apply: bool = False,
) -> dict[str, Any]:
    """Dry-run by default; repair one evidence-backed PUT exercise atomically."""

    put_id = _positive_int(put_position_id, label="ID da PUT")
    source = _text(source_ref)
    if not source:
        raise CashPutExerciseRepairError("Informe a referência documental da correção.")
    lock = " FOR UPDATE" if apply else ""
    with db_transaction() as conn:
        # Applies the additive column migration within this controlled transaction.
        _ensure_tables(conn, commit=False)
        position = conn.execute(f"SELECT * FROM positions WHERE id = %s{lock}", (put_id,)).fetchone()
        if position is None:
            raise CashPutExerciseRepairError("PUT não encontrada.")
        underlying = _upper(position.get("underlying"))
        mode = 1 if bool(position.get("is_simulated") or 0) else 0
        holding = conn.execute(
            f"SELECT * FROM equity_holdings WHERE ticker = %s AND is_simulated = %s{lock}",
            (underlying, mode),
        ).fetchone()
        if holding is None:
            raise CashPutExerciseRepairError("Estoque consolidado não encontrado.")
        events = conn.execute(
            f"SELECT * FROM equity_holding_events WHERE ticker = %s AND is_simulated = %s ORDER BY event_date, id{lock}",
            (underlying, mode),
        ).fetchall()
        assignments = conn.execute(
            f"SELECT * FROM ledger WHERE position_id = %s AND type = 'ASSIGN'{lock}", (put_id,)
        ).fetchall()
        realized = conn.execute(
            f"SELECT * FROM ledger WHERE position_id = %s AND type = 'REALIZED'{lock}", (put_id,)
        ).fetchall()
        plan = build_cash_put_exercise_repair_plan(
            put_position=position,
            holding=holding,
            holding_events=events,
            assignment_transactions=assignments,
            realized_transactions=realized,
            exercise_date=exercise_date,
            original_strike=original_strike,
            exercise_strike=exercise_strike,
            purchase_fees=purchase_fees,
        )
        if apply and plan.update_required:
            note = (
                f"Exercício confirmado em {plan.exercise_date}; strike original R$ {plan.original_strike:.2f}; "
                f"strike aplicado R$ {plan.exercise_strike:.2f}; despesas individuais R$ {plan.purchase_fees:.2f}."
            )
            result = conn.execute(
                """
                UPDATE positions
                SET exit_date = %s,
                    contract_strike = %s,
                    contract_exercise_strike = %s,
                    performance_source_ref = %s,
                    performance_evidence_note = %s,
                    performance_evidence_state = 'pending'
                WHERE id = %s
                """,
                (plan.exercise_date, plan.original_strike, plan.exercise_strike, source, note, put_id),
            )
            if result.rowcount != 1:
                raise CashPutExerciseRepairError("A posição não foi atualizada.")
            result = conn.execute(
                "UPDATE ledger SET date = %s, amount = %s, description = %s WHERE id = %s",
                (
                    plan.exercise_date,
                    plan.assignment_amount,
                    f"Exercício PUT {put_id} @ {plan.exercise_strike:.2f}; despesas da compra: R$ {plan.purchase_fees:.2f}",
                    plan.assignment_ledger_id,
                ),
            )
            if result.rowcount != 1:
                raise CashPutExerciseRepairError("O ASSIGN não foi atualizado.")
            result = conn.execute(
                "UPDATE ledger SET date = %s WHERE id = %s",
                (plan.exercise_date, plan.realized_ledger_id),
            )
            if result.rowcount != 1:
                raise CashPutExerciseRepairError("O REALIZED não foi atualizado.")
            result = conn.execute(
                """
                UPDATE equity_holding_events
                SET event_date = %s, price_reference = %s, fees = %s, avg_price_after = %s, notes = %s
                WHERE id = %s
                """,
                (
                    plan.exercise_date,
                    plan.exercise_strike,
                    plan.purchase_fees,
                    round(-plan.assignment_amount / _positive_int(position.get("qty"), label="Quantidade da PUT"), 6),
                    note,
                    plan.holding_event_id,
                ),
            )
            if result.rowcount != 1:
                raise CashPutExerciseRepairError("O evento de estoque não foi atualizado.")

            refreshed = conn.execute(
                "SELECT * FROM equity_holding_events WHERE ticker = %s AND is_simulated = %s ORDER BY event_date, id FOR UPDATE",
                (underlying, mode),
            ).fetchall()
            before_updates, _ = _rebase_event_before_values(
                events=refreshed,
                assignment_event_id=plan.holding_event_id,
                exercise_date=plan.exercise_date,
                exercise_strike=plan.exercise_strike,
                purchase_fees=plan.purchase_fees,
            )
            for event_id, (before_qty, before_avg) in before_updates.items():
                result = conn.execute(
                    "UPDATE equity_holding_events SET quantity_before = %s, avg_price_before = %s WHERE id = %s",
                    (before_qty, before_avg, event_id),
                )
                if result.rowcount != 1:
                    raise CashPutExerciseRepairError("A cadeia posterior de estoque não foi atualizada.")

    report = plan.to_dict()
    report["applied"] = bool(apply and plan.update_required)
    return report


__all__ = [
    "CashPutExerciseRepairError",
    "CashPutExerciseRepairPlan",
    "build_cash_put_exercise_repair_plan",
    "repair_cash_put_exercise",
]
