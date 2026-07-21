from __future__ import annotations

import datetime as dt
import math
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


def _require_iso_date(value: str, *, label: str) -> str:
    text = str(value or "").strip()
    try:
        parsed = dt.date.fromisoformat(text)
    except ValueError as exc:
        raise FlowError(f"{label} precisa de data valida.") from exc
    return parsed.isoformat()


def _positive_int(value: object) -> int:
    try:
        parsed = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return parsed if parsed > 0 else 0


def _positive_float(value: object) -> float:
    try:
        parsed = float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
    return parsed if parsed > 0 else 0.0


def _nonnegative_currency(value: object, *, label: str) -> float:
    text = str(value or "").strip().replace(",", ".")
    if not text:
        raise FlowError(f"{label} precisa ser informado, mesmo quando for R$ 0,00.")
    try:
        parsed = float(text)
    except (TypeError, ValueError) as exc:
        raise FlowError(f"{label} precisa ser um valor valido.") from exc
    if not math.isfinite(parsed) or parsed < 0:
        raise FlowError(f"{label} nao pode ser negativo.")
    return round(parsed, 2)


def assign_put(
    *,
    position_id: int,
    strike: Optional[float] = None,
    qty: Optional[int] = None,
    date: str,
) -> None:
    confirmed_date = _require_iso_date(date, label="Exercicio da PUT")
    with db_transaction() as conn:
        pos = get_position(position_id, conn=conn)
        if not pos:
            raise FlowError("Posição não encontrada.")
        is_simulated = bool(pos["is_simulated"]) if pos else False

        underlying = (pos.get("underlying") or "").strip().upper()
        if (pos.get("status") or "").strip().lower() != "open":
            raise FlowError("Posição não está aberta.", underlying=underlying)
        if infer_option_type(pos.get("ticker")) != "PUT":
            raise FlowError("Ticker não é PUT.", underlying=underlying)

        resolved_qty = _positive_int(pos.get("open_qty") or pos.get("qty"))
        if qty is not None and _positive_int(qty) != resolved_qty:
            raise FlowError("Quantidade do exercicio diverge da posição.", underlying=underlying)
        resolved_strike = _positive_float(pos.get("strike"))
        submitted_strike = _positive_float(strike)
        if resolved_strike <= 0:
            resolved_strike = submitted_strike
        elif submitted_strike > 0 and round(submitted_strike - resolved_strike, 4) != 0:
            raise FlowError("Strike do exercicio diverge da posição.", underlying=underlying)
        if resolved_qty <= 0 or resolved_strike <= 0:
            raise FlowError("Quantidade ou strike inválido.", underlying=underlying)

        close_position(
            position_id=position_id,
            exit_date=confirmed_date,
            exit_price=0.0,
            exit_reason="Exercício",
            conn=conn,
        )

        cost = float(resolved_strike) * int(resolved_qty)
        add_transaction(
            date=confirmed_date,
            type=TransactionType.ASSIGNMENT,
            amount=-cost,
            description=f"Exercício PUT {position_id} @ {resolved_strike}",
            position_id=position_id,
            is_simulated=is_simulated,
            conn=conn,
        )
        sync_position_closure_effects(position_id=position_id, conn=conn)

        if pos:
            apply_put_assignment_to_holding(
                ticker=underlying,
                qty=int(resolved_qty),
                strike=float(resolved_strike),
                date=confirmed_date,
                is_simulated=is_simulated,
                related_position_id=position_id,
                conn=conn,
            )


def callaway(
    *,
    position_id: int,
    date: str,
    sale_fees: object = "0",
) -> str:
    confirmed_date = _require_iso_date(date, label="Exercicio da CALL")
    resolved_sale_fees = _nonnegative_currency(
        sale_fees,
        label="Despesas da venda no exercicio",
    )
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
                date=confirmed_date,
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
            trade_date=confirmed_date,
            qty=int(qty),
            entry_price=float(consumed_avg_price or 0.0),
            fees=resolved_sale_fees,
            trade_type="stock",
            side="long",
            notes=(
                "Baixa automática do estoque consolidado no exercício da call "
                f"{call_pos.get('ticker')}; despesas da venda: R$ {resolved_sale_fees:.2f}"
            ),
            is_simulated=is_simulated,
            strategy_tag="covered_call",
            conn=conn,
        )
        close_position(
            position_id=stock_history_id,
            exit_date=confirmed_date,
            exit_price=strike_val,
            exit_reason="Exercício",
            conn=conn,
        )
        sync_position_closure_effects(position_id=stock_history_id, conn=conn)

        close_position(
            position_id=position_id,
            exit_date=confirmed_date,
            exit_price=0.0,
            exit_reason="Exercício",
            conn=conn,
        )

        proceeds = strike_val * qty
        add_transaction(
            date=confirmed_date,
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
