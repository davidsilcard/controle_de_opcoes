from __future__ import annotations

import math
import unicodedata
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

from .db import db_transaction
from .finance import TransactionType
from .utils import infer_option_type


class ExerciseFeeRepairError(RuntimeError):
    """Raised when a historical exercise does not match the repair invariants."""


@dataclass(frozen=True)
class CoveredCallExerciseFeeRepairPlan:
    call_position_id: int
    stock_position_id: int
    holding_event_id: int
    sell_ledger_id: int
    gross_sale: float
    sale_fees: float
    net_sale: float
    update_holding_event: bool
    update_sell_ledger: bool

    @property
    def changes_required(self) -> bool:
        return self.update_holding_event or self.update_sell_ledger

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["changes_required"] = self.changes_required
        return payload


def _norm(value: Any) -> str:
    return str(value or "").strip()


def _norm_upper(value: Any) -> str:
    return _norm(value).upper()


def _money(value: Any, *, label: str) -> float:
    try:
        amount = float(str(value).strip().replace(",", "."))
    except (TypeError, ValueError) as exc:
        raise ExerciseFeeRepairError(f"{label} invalido.") from exc
    if not math.isfinite(amount):
        raise ExerciseFeeRepairError(f"{label} invalido.")
    return round(amount, 2)


def _int(value: Any, *, label: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ExerciseFeeRepairError(f"{label} invalido.") from exc
    if parsed <= 0:
        raise ExerciseFeeRepairError(f"{label} precisa ser maior que zero.")
    return parsed


def _is_exercise_reason(value: Any) -> bool:
    normalized = unicodedata.normalize("NFKD", _norm(value)).encode("ascii", "ignore").decode()
    return "exerc" in normalized.lower()


def _same_money(left: Any, right: Any) -> bool:
    try:
        return round(float(left or 0.0) - float(right or 0.0), 2) == 0.0
    except (TypeError, ValueError):
        return False


def build_covered_call_exercise_fee_repair_plan(
    *,
    call_position: Mapping[str, Any],
    stock_position: Mapping[str, Any],
    holding_events: Sequence[Mapping[str, Any]],
    sell_transactions: Sequence[Mapping[str, Any]],
    sale_fees: Any,
) -> CoveredCallExerciseFeeRepairPlan:
    """Validate one historical CALL exercise and describe its minimal repair."""

    call_id = _int(call_position.get("id"), label="ID da CALL")
    stock_id = _int(stock_position.get("id"), label="ID do historico de acao")
    resolved_fees = _money(sale_fees, label="Despesas da venda")
    if resolved_fees <= 0:
        raise ExerciseFeeRepairError("Despesas da venda precisam ser maiores que R$ 0,00.")

    call_ticker = _norm_upper(call_position.get("ticker"))
    underlying = _norm_upper(call_position.get("underlying"))
    if infer_option_type(call_ticker) != "CALL":
        raise ExerciseFeeRepairError("A posicao informada nao e uma CALL.")
    if _norm(call_position.get("strategy_tag")).lower() != "covered_call":
        raise ExerciseFeeRepairError("A CALL nao pertence a estrategia Covered Call.")
    if _norm(call_position.get("status")).lower() != "closed" or not _is_exercise_reason(
        call_position.get("exit_reason")
    ):
        raise ExerciseFeeRepairError("A CALL precisa estar fechada por exercicio.")
    exercise_date = _norm(call_position.get("exit_date"))
    if not exercise_date:
        raise ExerciseFeeRepairError("A CALL nao possui data de exercicio.")

    qty = _int(call_position.get("qty"), label="Quantidade da CALL")
    if _norm_upper(stock_position.get("ticker")) != underlying:
        raise ExerciseFeeRepairError("O historico de acao nao pertence ao ativo-base da CALL.")
    if _norm(stock_position.get("strategy_tag")).lower() != "covered_call":
        raise ExerciseFeeRepairError("O historico de acao nao pertence a Covered Call.")
    if _norm(stock_position.get("status")).lower() != "closed" or not _is_exercise_reason(
        stock_position.get("exit_reason")
    ):
        raise ExerciseFeeRepairError("O historico de acao precisa estar fechado por exercicio.")
    if _norm(stock_position.get("exit_date")) != exercise_date:
        raise ExerciseFeeRepairError("As datas de exercicio da CALL e da acao divergem.")
    if _int(stock_position.get("qty"), label="Quantidade do historico de acao") != qty:
        raise ExerciseFeeRepairError("As quantidades da CALL e da acao divergem.")
    if bool(call_position.get("is_simulated") or 0) != bool(stock_position.get("is_simulated") or 0):
        raise ExerciseFeeRepairError("CALL e historico de acao pertencem a modos diferentes.")

    strike = _money(stock_position.get("exit_price"), label="Preco de exercicio da acao")
    if strike <= 0:
        raise ExerciseFeeRepairError("O historico de acao nao possui preco de exercicio valido.")
    gross_sale = round(strike * qty, 2)
    if resolved_fees > gross_sale:
        raise ExerciseFeeRepairError("Despesas da venda nao podem ultrapassar o valor bruto.")
    if not _same_money(stock_position.get("fees"), resolved_fees):
        raise ExerciseFeeRepairError(
            "As despesas informadas nao conferem com o historico fiscal da acao."
        )

    if len(holding_events) != 1:
        raise ExerciseFeeRepairError("Era esperado exatamente um evento CALL_EXERCISE vinculado a CALL.")
    event = holding_events[0]
    if _norm_upper(event.get("ticker")) != underlying:
        raise ExerciseFeeRepairError("O evento de estoque pertence a outro ativo.")
    if _norm_upper(event.get("event_type")) != "CALL_EXERCISE":
        raise ExerciseFeeRepairError("O evento de estoque nao e um CALL_EXERCISE.")
    if _norm(event.get("event_date")) != exercise_date:
        raise ExerciseFeeRepairError("A data do evento de estoque diverge do exercicio.")
    if int(event.get("qty_delta") or 0) != -qty:
        raise ExerciseFeeRepairError("A quantidade do evento de estoque diverge da CALL.")
    if not _same_money(event.get("price_reference"), strike):
        raise ExerciseFeeRepairError("O preco do evento de estoque diverge do exercicio.")
    if bool(event.get("is_simulated") or 0) != bool(call_position.get("is_simulated") or 0):
        raise ExerciseFeeRepairError("O evento de estoque pertence a outro modo.")
    event_fees = _money(event.get("fees", 0.0), label="Despesas do evento de estoque")
    if not (_same_money(event_fees, 0.0) or _same_money(event_fees, resolved_fees)):
        raise ExerciseFeeRepairError("O evento de estoque ja possui despesas diferentes da nota.")

    if len(sell_transactions) != 1:
        raise ExerciseFeeRepairError("Era esperado exatamente um SELL no ledger da CALL.")
    sell = sell_transactions[0]
    if _norm(sell.get("date")) != exercise_date:
        raise ExerciseFeeRepairError("A data do SELL no ledger diverge do exercicio.")
    if _norm_upper(sell.get("type")) != TransactionType.SELL.value:
        raise ExerciseFeeRepairError("O lancamento financeiro nao e um SELL.")
    if bool(sell.get("is_simulated") or 0) != bool(call_position.get("is_simulated") or 0):
        raise ExerciseFeeRepairError("O SELL no ledger pertence a outro modo.")

    net_sale = round(gross_sale - resolved_fees, 2)
    current_sale = _money(sell.get("amount"), label="Valor do SELL no ledger")
    if not (_same_money(current_sale, gross_sale) or _same_money(current_sale, net_sale)):
        raise ExerciseFeeRepairError("O SELL atual nao corresponde ao bruto ou ao liquido esperado.")

    return CoveredCallExerciseFeeRepairPlan(
        call_position_id=call_id,
        stock_position_id=stock_id,
        holding_event_id=_int(event.get("id"), label="ID do evento de estoque"),
        sell_ledger_id=_int(sell.get("id"), label="ID do SELL no ledger"),
        gross_sale=gross_sale,
        sale_fees=resolved_fees,
        net_sale=net_sale,
        update_holding_event=not _same_money(event_fees, resolved_fees),
        update_sell_ledger=not _same_money(current_sale, net_sale),
    )


def repair_covered_call_exercise_sale_fee(
    *,
    call_position_id: int,
    stock_position_id: int,
    sale_fees: Any,
    apply: bool = False,
) -> dict[str, Any]:
    """Dry-run by default; when applied, update only the matching event and SELL."""

    call_id = _int(call_position_id, label="ID da CALL")
    stock_id = _int(stock_position_id, label="ID do historico de acao")
    lock = " FOR UPDATE" if apply else ""

    with db_transaction() as conn:
        call_position = conn.execute(
            f"SELECT * FROM positions WHERE id = %s{lock}", (call_id,)
        ).fetchone()
        stock_position = conn.execute(
            f"SELECT * FROM positions WHERE id = %s{lock}", (stock_id,)
        ).fetchone()
        if call_position is None:
            raise ExerciseFeeRepairError("CALL nao encontrada.")
        if stock_position is None:
            raise ExerciseFeeRepairError("Historico de acao nao encontrado.")

        holding_events = conn.execute(
            f"""
            SELECT *
            FROM equity_holding_events
            WHERE related_position_id = %s
              AND event_type = 'CALL_EXERCISE'{lock}
            """,
            (call_id,),
        ).fetchall()
        sell_transactions = conn.execute(
            f"""
            SELECT *
            FROM ledger
            WHERE position_id = %s
              AND type = %s{lock}
            """,
            (call_id, TransactionType.SELL.value),
        ).fetchall()
        plan = build_covered_call_exercise_fee_repair_plan(
            call_position=call_position,
            stock_position=stock_position,
            holding_events=holding_events,
            sell_transactions=sell_transactions,
            sale_fees=sale_fees,
        )

        if apply and plan.update_holding_event:
            notes = (
                f"Baixa automatica por exercicio da call {call_id}; "
                f"despesas da venda: R$ {plan.sale_fees:.2f}"
            )
            result = conn.execute(
                "UPDATE equity_holding_events SET fees = %s, notes = %s WHERE id = %s",
                (plan.sale_fees, notes, plan.holding_event_id),
            )
            if result.rowcount != 1:
                raise ExerciseFeeRepairError("Evento de estoque nao foi atualizado.")

        if apply and plan.update_sell_ledger:
            description = (
                f"Venda (CALL exercida) {_norm_upper(call_position.get('ticker'))} "
                f"@ {plan.gross_sale / _int(call_position.get('qty'), label='Quantidade da CALL'):.2f}; "
                f"despesas da venda: R$ {plan.sale_fees:.2f}"
            )
            result = conn.execute(
                "UPDATE ledger SET amount = %s, description = %s WHERE id = %s",
                (plan.net_sale, description, plan.sell_ledger_id),
            )
            if result.rowcount != 1:
                raise ExerciseFeeRepairError("SELL no ledger nao foi atualizado.")

    report = plan.to_dict()
    report["applied"] = bool(apply and plan.changes_required)
    return report


__all__ = [
    "CoveredCallExerciseFeeRepairPlan",
    "ExerciseFeeRepairError",
    "build_covered_call_exercise_fee_repair_plan",
    "repair_covered_call_exercise_sale_fee",
]
