from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from . import finance
from .tax import build_position_tax_events
from .utils import infer_option_type


@dataclass(frozen=True)
class AuditIssue:
    position_id: int
    ticker: str
    code: str
    message: str


def _norm(value: Any) -> str:
    return str(value or "").strip()


def _norm_lower(value: Any) -> str:
    return _norm(value).lower()


def _norm_upper(value: Any) -> str:
    return _norm(value).upper()


def _int_value(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _float_or_none(value: Any) -> float | None:
    if value is None or _norm(value) == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _money_diff(actual: float | None, expected: float | None) -> float | None:
    if actual is None and expected is None:
        return None
    return round(float(actual or 0.0) - float(expected or 0.0), 2)


def _has_diff(value: float | None) -> bool:
    return value is not None and round(float(value), 2) != 0.0


def _events_by_related_position(
    holding_events: Sequence[Mapping[str, Any]] | None,
) -> dict[int, list[Mapping[str, Any]]]:
    indexed: dict[int, list[Mapping[str, Any]]] = {}
    for event in holding_events or []:
        rid = _int_value(event.get("related_position_id"))
        if rid <= 0:
            continue
        indexed.setdefault(rid, []).append(event)
    return indexed


def _exercise_cash_from_event(
    event: Mapping[str, Any],
    *,
    sign: int,
) -> float | None:
    qty = abs(_int_value(event.get("qty_delta")))
    price = _float_or_none(event.get("price_reference"))
    if price is None:
        price = _float_or_none(event.get("avg_price_after"))
    if qty <= 0 or price is None:
        return None
    return round(sign * qty * float(price), 2)


def _stock_assignment_from_legacy_position(
    *,
    positions: Sequence[Mapping[str, Any]],
    option_position_id: int,
    underlying: str,
) -> tuple[str, int, float, float] | None:
    for candidate in positions:
        if _int_value(candidate.get("parent_position_id")) != int(option_position_id):
            continue
        ticker = _norm_upper(candidate.get("ticker"))
        if ticker != _norm_upper(underlying):
            continue
        if infer_option_type(ticker) in {"CALL", "PUT"}:
            continue
        if _norm_lower(candidate.get("side")) != "long":
            continue
        qty = _int_value(candidate.get("qty"))
        price = _float_or_none(candidate.get("entry_price"))
        if qty <= 0 or price is None:
            continue
        return ticker, qty, price, -round(qty * price, 2)
    return None


def build_audit_reconciliation(
    positions: Sequence[Mapping[str, Any]],
    *,
    ledger_sums: Mapping[int, Mapping[str, float]],
    include_closed: bool,
    holding_events: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    events_by_position = _events_by_related_position(holding_events)
    position_ids = {_int_value(pos.get("id")) for pos in positions}
    rows: list[dict[str, Any]] = []
    issues: list[AuditIssue] = []

    totals = {
        "expected_premium": 0.0,
        "expected_darf": 0.0,
        "expected_buyback": 0.0,
        "expected_option_buy": 0.0,
        "expected_assignment": 0.0,
        "expected_sell": 0.0,
        "expected_net": 0.0,
        "expected_cash_net": 0.0,
        "expected_total_cash": 0.0,
        "expected_realized": 0.0,
        "actual_premium": 0.0,
        "actual_darf": 0.0,
        "actual_buyback": 0.0,
        "actual_option_buy": 0.0,
        "actual_assignment": 0.0,
        "actual_sell": 0.0,
        "actual_net": 0.0,
        "actual_cash_net": 0.0,
        "actual_total_cash": 0.0,
        "actual_realized": 0.0,
    }

    def add_issue(pos_id: int, ticker: str, code: str, message: str) -> None:
        issues.append(AuditIssue(pos_id, ticker or f"#{pos_id}", code, message))

    for pos in positions:
        if not include_closed and _norm_lower(pos.get("status")) == "closed":
            continue

        pid = _int_value(pos.get("id"))
        ticker = _norm_upper(pos.get("ticker"))
        underlying = _norm_upper(pos.get("underlying"))
        opt_type = infer_option_type(ticker)
        is_option = opt_type in {"CALL", "PUT"}
        side = _norm_lower(pos.get("side"))
        trade_type = _norm_lower(pos.get("trade_type") or "swing")
        status_norm = _norm_lower(pos.get("status"))
        entry_price = float(pos.get("entry_price") or 0.0)
        qty = _int_value(pos.get("qty"))
        fees = float(pos.get("fees") or 0.0)
        partial_qty = _int_value(pos.get("partial_qty"))
        close_qty = max(qty - partial_qty, 0)
        exit_price = _float_or_none(pos.get("exit_price"))
        exit_reason = _norm_lower(pos.get("exit_reason"))
        sums = ledger_sums.get(pid, {})

        expected_premium = None
        expected_darf = None
        expected_buyback = None
        expected_option_buy = None
        expected_assignment = None
        expected_sell = None
        expected_realized = None
        assignment_stock_ticker = None
        assignment_stock_qty = 0
        assignment_stock_price = None
        sell_stock_ticker = None
        sell_stock_qty = 0
        sell_stock_price = None

        realized_events = build_position_tax_events(pos)
        if realized_events:
            expected_realized = round(
                sum(float(event.amount) for event in realized_events), 2
            )

        if is_option and side == "short":
            expected_premium = finance.calculate_option_premium(
                entry_price=entry_price,
                qty=qty,
                fees=fees,
            )
            expected_darf = finance.calculate_darf_provision(
                premium_amount=expected_premium,
                trade_type=trade_type,
            )
            if (
                status_norm == "closed"
                and close_qty > 0
                and exit_price is not None
                and exit_price > 0
            ):
                expected_buyback = -round(float(exit_price) * int(close_qty), 2)

            for event in events_by_position.get(pid, []):
                event_type = _norm_upper(event.get("event_type"))
                if opt_type == "PUT" and event_type == "PUT_ASSIGNMENT":
                    value = _exercise_cash_from_event(event, sign=-1)
                    if value is not None:
                        expected_assignment = value
                        assignment_stock_qty = abs(_int_value(event.get("qty_delta")))
                        assignment_stock_ticker = event.get("ticker") or underlying
                        assignment_stock_price = _float_or_none(
                            event.get("price_reference")
                        )
                if opt_type == "CALL" and event_type == "CALL_EXERCISE":
                    value = _exercise_cash_from_event(event, sign=1)
                    if value is not None:
                        expected_sell = value
                        sell_stock_qty = abs(_int_value(event.get("qty_delta")))
                        sell_stock_ticker = event.get("ticker") or underlying
                        sell_stock_price = _float_or_none(event.get("price_reference"))

            if opt_type == "PUT" and status_norm == "closed" and "exerc" in exit_reason:
                if expected_assignment is None:
                    legacy_assignment = _stock_assignment_from_legacy_position(
                        positions=positions,
                        option_position_id=pid,
                        underlying=underlying,
                    )
                    if legacy_assignment is not None:
                        (
                            assignment_stock_ticker,
                            assignment_stock_qty,
                            assignment_stock_price,
                            expected_assignment,
                        ) = legacy_assignment
                if expected_assignment is None:
                    add_issue(
                        pid,
                        ticker,
                        "PUT_EXERCIDA_SEM_EVENTO",
                        "PUT exercida sem evento de estoque PUT_ASSIGNMENT.",
                    )
            if (
                opt_type == "CALL"
                and status_norm == "closed"
                and "exerc" in exit_reason
            ):
                if expected_sell is None:
                    add_issue(
                        pid,
                        ticker,
                        "CALL_EXERCIDA_SEM_EVENTO",
                        "CALL exercida sem evento de estoque CALL_EXERCISE.",
                    )

        if is_option and side == "long":
            expected_option_buy = round(
                finance.calculate_option_purchase(
                    entry_price=entry_price,
                    qty=qty,
                    fees=finance.long_option_entry_buy_fees(pos),
                ),
                2,
            )

        actual_premium = sums.get(finance.TransactionType.PREMIUM.value)
        actual_darf = sums.get(finance.TransactionType.DARF.value)
        actual_buy_value = sums.get(finance.TransactionType.BUY.value)
        actual_buyback = actual_buy_value if is_option and side == "short" else None
        actual_option_buy = actual_buy_value if is_option and side == "long" else None
        actual_assignment = sums.get(finance.TransactionType.ASSIGNMENT.value)
        actual_sell = sums.get(finance.TransactionType.SELL.value)
        actual_realized = sums.get(finance.TransactionType.REALIZED.value)

        expected_net = None
        actual_net = None
        expected_cash_net = None
        actual_cash_net = None
        expected_total_cash = None
        actual_total_cash = None

        if expected_premium is not None or expected_darf is not None:
            expected_net = float(expected_premium or 0.0) + float(expected_darf or 0.0)
        if actual_premium is not None or actual_darf is not None:
            actual_net = float(actual_premium or 0.0) + float(actual_darf or 0.0)

        if (
            expected_net is not None
            or expected_buyback is not None
            or expected_option_buy is not None
        ):
            expected_cash_net = (
                float(expected_net or 0.0)
                + float(expected_buyback or 0.0)
                + float(expected_option_buy or 0.0)
            )
        if (
            actual_net is not None
            or actual_buyback is not None
            or actual_option_buy is not None
        ):
            actual_cash_net = (
                float(actual_net or 0.0)
                + float(actual_buyback or 0.0)
                + float(actual_option_buy or 0.0)
            )

        if (
            expected_cash_net is not None
            or expected_assignment is not None
            or expected_sell is not None
        ):
            expected_total_cash = (
                float(expected_cash_net or 0.0)
                + float(expected_assignment or 0.0)
                + float(expected_sell or 0.0)
            )
        if (
            actual_cash_net is not None
            or actual_assignment is not None
            or actual_sell is not None
        ):
            actual_total_cash = (
                float(actual_cash_net or 0.0)
                + float(actual_assignment or 0.0)
                + float(actual_sell or 0.0)
            )

        row = {
            "id": pid,
            "ticker": ticker,
            "underlying": underlying,
            "side": side,
            "status": pos.get("status"),
            "qty": qty,
            "entry_price": entry_price,
            "fees": fees,
            "trade_type": trade_type,
            "expected_premium": expected_premium,
            "expected_darf": expected_darf,
            "expected_buyback": expected_buyback,
            "expected_option_buy": expected_option_buy,
            "expected_assignment": expected_assignment,
            "expected_sell": expected_sell,
            "expected_realized": expected_realized,
            "actual_premium": actual_premium,
            "actual_darf": actual_darf,
            "actual_buyback": actual_buyback,
            "actual_option_buy": actual_option_buy,
            "actual_assignment": actual_assignment,
            "actual_sell": actual_sell,
            "actual_realized": actual_realized,
            "diff_premium": _money_diff(actual_premium, expected_premium),
            "diff_darf": _money_diff(actual_darf, expected_darf),
            "diff_buyback": _money_diff(actual_buyback, expected_buyback),
            "diff_option_buy": _money_diff(actual_option_buy, expected_option_buy),
            "diff_assignment": _money_diff(actual_assignment, expected_assignment),
            "diff_sell": _money_diff(actual_sell, expected_sell),
            "diff_realized": _money_diff(actual_realized, expected_realized),
            "expected_net": expected_net,
            "actual_net": actual_net,
            "diff_net": _money_diff(actual_net, expected_net),
            "expected_cash_net": expected_cash_net,
            "actual_cash_net": actual_cash_net,
            "diff_cash_net": _money_diff(actual_cash_net, expected_cash_net),
            "expected_total_cash": expected_total_cash,
            "actual_total_cash": actual_total_cash,
            "diff_total_cash": _money_diff(actual_total_cash, expected_total_cash),
            "assignment_stock_ticker": assignment_stock_ticker,
            "assignment_stock_qty": assignment_stock_qty,
            "assignment_stock_price": assignment_stock_price,
            "sell_stock_ticker": sell_stock_ticker,
            "sell_stock_qty": sell_stock_qty,
            "sell_stock_price": sell_stock_price,
        }

        relevant_fields = [
            "expected_premium",
            "actual_premium",
            "actual_darf",
            "expected_buyback",
            "actual_buyback",
            "expected_option_buy",
            "actual_option_buy",
            "expected_assignment",
            "actual_assignment",
            "expected_sell",
            "actual_sell",
            "expected_realized",
            "actual_realized",
        ]
        if not any(row.get(field) is not None for field in relevant_fields):
            continue

        diff_messages = {
            "diff_premium": (
                "PREMIO_DIVERGENTE",
                "Premio esperado nao bate com o ledger.",
            ),
            "diff_darf": ("DARF_DIVERGENTE", "DARF esperado nao bate com o ledger."),
            "diff_buyback": (
                "RECOMPRA_DIVERGENTE",
                "Recompra de opcao vendida nao bate com o ledger BUY.",
            ),
            "diff_option_buy": (
                "COMPRA_OPCAO_DIVERGENTE",
                "Compra de opcao comprada nao bate com o ledger BUY.",
            ),
            "diff_assignment": (
                "ASSIGN_DIVERGENTE",
                "Exercicio de PUT nao bate com o ledger ASSIGN.",
            ),
            "diff_sell": (
                "SELL_DIVERGENTE",
                "Exercicio de CALL nao bate com o ledger SELL.",
            ),
            "diff_realized": (
                "REALIZED_DIVERGENTE",
                "Resultado realizado esperado nao bate com o ledger.",
            ),
        }
        for field, (code, message) in diff_messages.items():
            if _has_diff(row.get(field)):
                add_issue(pid, ticker, code, message)

        rows.append(row)

        for key in (
            "expected_premium",
            "expected_darf",
            "expected_buyback",
            "expected_option_buy",
            "expected_assignment",
            "expected_sell",
            "expected_realized",
            "actual_premium",
            "actual_darf",
            "actual_buyback",
            "actual_option_buy",
            "actual_assignment",
            "actual_sell",
            "actual_realized",
        ):
            if row.get(key) is not None:
                totals[key] += float(row.get(key) or 0.0)

    totals["expected_net"] = totals["expected_premium"] + totals["expected_darf"]
    totals["actual_net"] = totals["actual_premium"] + totals["actual_darf"]
    totals["expected_cash_net"] = (
        totals["expected_net"]
        + totals["expected_buyback"]
        + totals["expected_option_buy"]
    )
    totals["actual_cash_net"] = (
        totals["actual_net"] + totals["actual_buyback"] + totals["actual_option_buy"]
    )
    totals["expected_total_cash"] = (
        totals["expected_cash_net"]
        + totals["expected_assignment"]
        + totals["expected_sell"]
    )
    totals["actual_total_cash"] = (
        totals["actual_cash_net"] + totals["actual_assignment"] + totals["actual_sell"]
    )

    orphan_rows = []
    for pid, sums in ledger_sums.items():
        if pid in position_ids:
            continue
        if not any(
            sums.get(tx.value) is not None
            for tx in (
                finance.TransactionType.PREMIUM,
                finance.TransactionType.DARF,
                finance.TransactionType.BUY,
                finance.TransactionType.SELL,
                finance.TransactionType.ASSIGNMENT,
                finance.TransactionType.REALIZED,
            )
        ):
            continue
        orphan_rows.append(
            {
                "id": pid,
                "actual_premium": sums.get(finance.TransactionType.PREMIUM.value),
                "actual_darf": sums.get(finance.TransactionType.DARF.value),
                "actual_buy": sums.get(finance.TransactionType.BUY.value),
                "actual_sell": sums.get(finance.TransactionType.SELL.value),
                "actual_assignment": sums.get(finance.TransactionType.ASSIGNMENT.value),
                "actual_realized": sums.get(finance.TransactionType.REALIZED.value),
            }
        )
        add_issue(
            pid, f"#{pid}", "LEDGER_ORFAO", "Ledger aponta para posicao inexistente."
        )

    return {
        "rows": rows,
        "totals": totals,
        "orphan_rows": orphan_rows,
        "audit_issues": issues,
    }


__all__ = ["AuditIssue", "build_audit_reconciliation"]
