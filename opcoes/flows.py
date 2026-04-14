from __future__ import annotations

from typing import Optional

from .db import db_transaction
from .finance import TransactionType, add_transaction, sync_position_closure_effects
from .holdings import (
    HoldingValidationError,
    apply_call_exercise_to_holding,
    apply_put_assignment_to_holding,
)
from .portfolio import add_position, close_position, get_position
from .utils import infer_option_type


class FlowError(RuntimeError):
    def __init__(self, message: str, *, underlying: Optional[str] = None) -> None:
        super().__init__(message)
        self.underlying = underlying


def assign_put(
    *,
    position_id: int,
    strike: float,
    qty: int,
    date: str,
) -> None:
    with db_transaction() as conn:
        pos = get_position(position_id, conn=conn)
        is_simulated = bool(pos["is_simulated"]) if pos else False

        close_position(
            position_id=position_id,
            exit_date=date,
            exit_price=0.0,
            exit_reason="Exercício",
            conn=conn,
        )

        cost = float(strike) * int(qty)
        add_transaction(
            date=date,
            type=TransactionType.ASSIGNMENT,
            amount=-cost,
            description=f"Exercício PUT {position_id} @ {strike}",
            position_id=position_id,
            is_simulated=is_simulated,
            conn=conn,
        )
        sync_position_closure_effects(position_id=position_id, conn=conn)

        if pos:
            apply_put_assignment_to_holding(
                ticker=pos["underlying"],
                qty=int(qty),
                strike=float(strike),
                date=date,
                is_simulated=is_simulated,
                related_position_id=position_id,
                conn=conn,
            )


def callaway(
    *,
    position_id: int,
    date: str,
) -> str:
    with db_transaction() as conn:
        call_pos = get_position(position_id, conn=conn)
        if not call_pos:
            raise FlowError("Posição não encontrada.")

        underlying = (call_pos.get("underlying") or "").strip().upper()
        is_simulated = bool(call_pos.get("is_simulated") or 0)

        if (call_pos.get("status") or "").strip().lower() != "open":
            raise FlowError("Posição não está aberta.", underlying=underlying)

        if infer_option_type(call_pos.get("ticker")) != "CALL":
            raise FlowError("Ticker não é CALL.", underlying=underlying)

        try:
            qty = int(call_pos.get("open_qty") or call_pos.get("qty") or 0)
        except (TypeError, ValueError):
            qty = 0

        strike = call_pos.get("strike")
        if qty <= 0 or strike is None:
            raise FlowError("Quantidade ou strike inválido.", underlying=underlying)

        try:
            strike_val = float(strike)
        except (TypeError, ValueError):
            raise FlowError("Strike inválido.", underlying=underlying)
        try:
            holding_result = apply_call_exercise_to_holding(
                ticker=underlying,
                qty=qty,
                strike=strike_val,
                date=date,
                is_simulated=is_simulated,
                related_position_id=position_id,
                conn=conn,
            )
        except HoldingValidationError as exc:
            raise FlowError(str(exc), underlying=underlying) from exc

        consumed_avg_price = holding_result.get("consumed_avg_price")
        if consumed_avg_price is None:
            raise FlowError(
                "Preco medio do estoque consolidado indisponivel para registrar o exercicio.",
                underlying=underlying,
            )
        stock_history_id = add_position(
            ticker=underlying,
            underlying=underlying,
            trade_date=date,
            qty=int(qty),
            entry_price=float(consumed_avg_price or 0.0),
            fees=0.0,
            trade_type="stock",
            side="long",
            notes=f"Baixa automática do estoque consolidado no exercício da call {call_pos.get('ticker')}",
            is_simulated=is_simulated,
            strategy_tag="covered_call",
            conn=conn,
        )
        close_position(
            position_id=stock_history_id,
            exit_date=date,
            exit_price=strike_val,
            exit_reason="Exercício",
            conn=conn,
        )
        sync_position_closure_effects(position_id=stock_history_id, conn=conn)

        close_position(
            position_id=position_id,
            exit_date=date,
            exit_price=0.0,
            exit_reason="Exercício",
            conn=conn,
        )

        proceeds = strike_val * qty
        add_transaction(
            date=date,
            type=TransactionType.SELL,
            amount=proceeds,
            description=f"Venda (CALL exercida) {call_pos.get('ticker')} @ {strike_val:.2f}",
            position_id=position_id,
            is_simulated=is_simulated,
            conn=conn,
        )
        sync_position_closure_effects(position_id=position_id, conn=conn)

    return underlying


__all__ = ["FlowError", "assign_put", "callaway"]
