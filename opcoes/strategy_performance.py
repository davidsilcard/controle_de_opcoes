from __future__ import annotations

import datetime as dt
from collections import defaultdict
from typing import Any, Mapping, Sequence

from .finance import TransactionType
from .utils import infer_option_type


STRATEGIES = ("cash_put", "covered_call")
PERFORMANCE_EVIDENCE_STATES = {"pending", "documents_exhausted"}


def _number(value: Any) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _positive_number(value: Any) -> float | None:
    number = _number(value)
    return number if number is not None and number > 0 else None


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _performance_evidence_state(position: Mapping[str, Any]) -> str:
    state = str(position.get("performance_evidence_state") or "pending").strip().lower()
    return state if state in PERFORMANCE_EVIDENCE_STATES else "pending"


def _days_between(start: Any, end: Any) -> int | None:
    try:
        start_date = dt.date.fromisoformat(str(start))
        end_date = dt.date.fromisoformat(str(end))
    except (TypeError, ValueError):
        return None
    return max((end_date - start_date).days, 1)


def _is_short_strategy_option(position: Mapping[str, Any]) -> bool:
    strategy = str(position.get("strategy_tag") or "").strip().lower()
    return (
        strategy in STRATEGIES
        and str(position.get("side") or "").strip().lower() == "short"
        and infer_option_type(position.get("ticker")) in {"CALL", "PUT"}
    )


def _is_call_exercise(position: Mapping[str, Any]) -> bool:
    return (
        str(position.get("strategy_tag") or "").strip().lower() == "covered_call"
        and infer_option_type(position.get("ticker")) == "CALL"
        and str(position.get("status") or "").strip().lower() == "closed"
        and "exerc" in str(position.get("exit_reason") or "").strip().lower()
    )


def _stock_results_by_parent(positions: Sequence[Mapping[str, Any]]) -> dict[int, list[Mapping[str, Any]]]:
    result: dict[int, list[Mapping[str, Any]]] = defaultdict(list)
    for position in positions:
        parent_id = _int(position.get("parent_position_id"))
        if parent_id <= 0:
            continue
        if str(position.get("strategy_tag") or "").strip().lower() != "covered_call":
            continue
        if infer_option_type(position.get("ticker")) in {"CALL", "PUT"}:
            continue
        result[parent_id].append(position)
    return result


def _contract_missing_reasons(
    *,
    position: Mapping[str, Any],
    strike: float | None,
) -> list[str]:
    reasons: list[str] = []
    if strike is None:
        reasons.append("strike nao preservado")
    if not str(position.get("contract_expiry") or "").strip():
        reasons.append("vencimento nao preservado")
    return reasons


def _return_base_missing_reasons(*, capital: float | None) -> list[str]:
    return ["capital de garantia nao declarado"] if capital is None else []


def _linkage_missing_reasons(
    *,
    position: Mapping[str, Any],
    stock_positions: Sequence[Mapping[str, Any]],
) -> list[str]:
    if _is_call_exercise(position) and len(stock_positions) != 1:
        return ["historico de acao da CALL exercida nao vinculado"]
    return []


def _warning_reasons(position: Mapping[str, Any]) -> list[str]:
    reasons: list[str] = []
    if bool(position.get("shared_fee_pending") or 0):
        note_ref = str(position.get("shared_fee_note_ref") or "").strip()
        reason = "taxas compartilhadas da nota sem rateio documental"
        if note_ref:
            reason += f" ({note_ref})"
        reasons.append(reason)
    return reasons


def _capital_for_position(
    position: Mapping[str, Any],
    *,
    strategy: str,
    strike: float | None,
    qty: int,
) -> tuple[float | None, Any, bool]:
    capital = _positive_number(position.get("capital_committed"))
    if capital is not None:
        return capital, position.get("capital_source"), False

    if strategy == "cash_put" and strike is not None and qty > 0:
        return round(strike * qty, 2), "strike_x_quantidade", True

    return None, position.get("capital_source"), False


def build_strategy_performance(
    positions: Sequence[Mapping[str, Any]],
    *,
    ledger_sums: Mapping[int, Mapping[str, float]],
    is_simulated: bool | None = False,
) -> dict[str, Any]:
    """Build auditable state and performance metrics without writing history."""

    filtered = [
        dict(position)
        for position in positions
        if _is_short_strategy_option(position)
        and (
            is_simulated is None
            or bool(position.get("is_simulated") or 0) == bool(is_simulated)
        )
    ]
    stock_by_parent = _stock_results_by_parent(positions)
    cycles: list[dict[str, Any]] = []
    summaries: dict[str, dict[str, Any]] = {
        strategy: {
            "strategy": strategy,
            "cycles": 0,
            "closed_cycles": 0,
            "open_cycles": 0,
            "complete_cycles": 0,
            "incomplete_cycles": 0,
            "result_complete_cycles": 0,
            "return_complete_cycles": 0,
            "warning_cycles": 0,
            "option_premium": 0.0,
            "option_result": 0.0,
            "stock_result": 0.0,
            "total_result": 0.0,
            "darf_provision": 0.0,
            "capital_sum": 0.0,
            "capital_days": 0.0,
        }
        for strategy in STRATEGIES
    }

    for position in filtered:
        position_id = _int(position.get("id"))
        strategy = str(position.get("strategy_tag") or "").strip().lower()
        ledger = ledger_sums.get(position_id, {})
        premium = round(float(ledger.get(TransactionType.PREMIUM.value, 0.0)), 2)
        darf_provision = round(float(ledger.get(TransactionType.DARF.value, 0.0)), 2)
        status = str(position.get("status") or "").strip().lower()
        option_result = None
        if status == "closed" and TransactionType.REALIZED.value in ledger:
            option_result = round(float(ledger[TransactionType.REALIZED.value]), 2)

        strike = _positive_number(position.get("contract_strike"))
        qty = _int(position.get("qty"))
        capital, capital_source, capital_is_derived = _capital_for_position(
            position,
            strategy=strategy,
            strike=strike,
            qty=qty,
        )
        stock_positions = stock_by_parent.get(position_id, [])
        stock_result = 0.0
        if len(stock_positions) == 1:
            stock_result = round(float(stock_positions[0].get("pl") or 0.0), 2)
        contract_missing_reasons = _contract_missing_reasons(
            position=position,
            strike=strike,
        )
        return_base_missing_reasons = _return_base_missing_reasons(capital=capital)
        linkage_missing_reasons = _linkage_missing_reasons(
            position=position,
            stock_positions=stock_positions,
        )
        warning_reasons = _warning_reasons(position)
        reasons = [
            *contract_missing_reasons,
            *return_base_missing_reasons,
            *linkage_missing_reasons,
        ]
        is_contract_complete = not contract_missing_reasons
        is_return_base_complete = not return_base_missing_reasons
        is_linkage_complete = not linkage_missing_reasons
        is_complete = not reasons
        days = _days_between(position.get("trade_date"), position.get("exit_date")) if status == "closed" else None
        total_result = None
        if option_result is not None:
            total_result = round(option_result + stock_result, 2)
        is_result_complete = total_result is not None and is_linkage_complete
        is_return_complete = is_result_complete and is_return_base_complete
        return_pct = (
            round((total_result / capital) * 100.0, 4)
            if is_return_complete and total_result is not None and capital is not None
            else None
        )
        annualized_return_pct = (
            round(return_pct * 365.0 / days, 4)
            if return_pct is not None and days is not None
            else None
        )
        cycle = {
            "position_id": position_id,
            "strategy": strategy,
            "ticker": position.get("ticker"),
            "underlying": position.get("underlying"),
            "option_type": infer_option_type(position.get("ticker")),
            "status": status,
            "trade_date": position.get("trade_date"),
            "exit_date": position.get("exit_date"),
            "exit_reason": position.get("exit_reason"),
            "qty": qty,
            "strike": strike,
            "expiry": position.get("contract_expiry"),
            "capital": capital,
            "capital_source": capital_source,
            "capital_is_derived": capital_is_derived,
            "source_ref": position.get("performance_source_ref"),
            "performance_evidence_state": _performance_evidence_state(position),
            "performance_evidence_note": position.get("performance_evidence_note"),
            "shared_fee_note_ref": position.get("shared_fee_note_ref"),
            "premium": premium,
            "darf_provision": darf_provision,
            "option_result": option_result,
            "stock_result": stock_result if _is_call_exercise(position) else None,
            "total_result": total_result,
            "days": days,
            "return_pct": return_pct,
            "annualized_return_pct": annualized_return_pct,
            "is_contract_complete": is_contract_complete,
            "is_return_base_complete": is_return_base_complete,
            "is_linkage_complete": is_linkage_complete,
            "is_complete": is_complete,
            "is_result_complete": is_result_complete,
            "is_return_complete": is_return_complete,
            "contract_missing_reasons": contract_missing_reasons,
            "return_base_missing_reasons": return_base_missing_reasons,
            "linkage_missing_reasons": linkage_missing_reasons,
            "missing_reasons": reasons,
            "warning_reasons": warning_reasons,
            "stock_position_id": stock_positions[0].get("id") if len(stock_positions) == 1 else None,
        }
        cycles.append(cycle)

        summary = summaries[strategy]
        summary["cycles"] += 1
        summary["option_premium"] += premium
        summary["darf_provision"] += darf_provision
        if option_result is not None:
            summary["option_result"] += option_result
        if _is_call_exercise(position):
            summary["stock_result"] += stock_result
        if total_result is not None:
            summary["total_result"] += total_result
        if warning_reasons:
            summary["warning_cycles"] += 1
        if status == "closed":
            summary["closed_cycles"] += 1
            if is_complete:
                summary["complete_cycles"] += 1
            else:
                summary["incomplete_cycles"] += 1
            if is_result_complete:
                summary["result_complete_cycles"] += 1
            if is_return_complete and capital is not None:
                summary["return_complete_cycles"] += 1
                summary["capital_sum"] += capital
                if days is not None:
                    summary["capital_days"] += capital * days
        else:
            summary["open_cycles"] += 1

    for summary in summaries.values():
        complete_result = sum(
            float(cycle["total_result"] or 0.0)
            for cycle in cycles
            if cycle["strategy"] == summary["strategy"]
            and cycle["is_result_complete"]
            and cycle["total_result"] is not None
        )
        return_result = sum(
            float(cycle["total_result"] or 0.0)
            for cycle in cycles
            if cycle["strategy"] == summary["strategy"]
            and cycle["is_return_complete"]
            and cycle["total_result"] is not None
        )
        capital_sum = float(summary["capital_sum"] or 0.0)
        capital_days = float(summary["capital_days"] or 0.0)
        summary["complete_result"] = round(complete_result, 2)
        summary["return_result"] = round(return_result, 2)
        summary["weighted_return_pct"] = (
            round((return_result / capital_sum) * 100.0, 4)
            if capital_sum > 0
            else None
        )
        summary["annualized_return_pct"] = (
            round((return_result / capital_days) * 365.0 * 100.0, 4)
            if capital_days > 0
            else None
        )
        for key in (
            "option_premium",
            "option_result",
            "stock_result",
            "total_result",
            "darf_provision",
            "capital_sum",
            "capital_days",
        ):
            summary[key] = round(float(summary[key]), 2)

    totals = {
        "cycles": sum(item["cycles"] for item in summaries.values()),
        "closed_cycles": sum(item["closed_cycles"] for item in summaries.values()),
        "open_cycles": sum(item["open_cycles"] for item in summaries.values()),
        "complete_cycles": sum(item["complete_cycles"] for item in summaries.values()),
        "incomplete_cycles": sum(item["incomplete_cycles"] for item in summaries.values()),
        "result_complete_cycles": sum(
            item["result_complete_cycles"] for item in summaries.values()
        ),
        "return_complete_cycles": sum(
            item["return_complete_cycles"] for item in summaries.values()
        ),
        "warning_cycles": sum(item["warning_cycles"] for item in summaries.values()),
        "option_premium": round(sum(item["option_premium"] for item in summaries.values()), 2),
        "option_result": round(sum(item["option_result"] for item in summaries.values()), 2),
        "stock_result": round(sum(item["stock_result"] for item in summaries.values()), 2),
        "total_result": round(sum(item["total_result"] for item in summaries.values()), 2),
        "darf_provision": round(sum(item["darf_provision"] for item in summaries.values()), 2),
        "capital_sum": round(sum(item["capital_sum"] for item in summaries.values()), 2),
        "capital_days": round(sum(item["capital_days"] for item in summaries.values()), 2),
    }
    totals["coverage_pct"] = (
        round((totals["complete_cycles"] / totals["closed_cycles"]) * 100.0, 2)
        if totals["closed_cycles"]
        else 100.0
    )
    totals["complete_result"] = round(
        sum(item["complete_result"] for item in summaries.values()), 2
    )
    totals["return_result"] = round(
        sum(item["return_result"] for item in summaries.values()), 2
    )
    totals["weighted_return_pct"] = (
        round((totals["return_result"] / totals["capital_sum"]) * 100.0, 4)
        if totals["capital_sum"] > 0
        else None
    )
    totals["annualized_return_pct"] = (
        round((totals["return_result"] / totals["capital_days"]) * 365.0 * 100.0, 4)
        if totals["capital_days"] > 0
        else None
    )
    incomplete = [cycle for cycle in cycles if not cycle["is_complete"]]
    incomplete.sort(
        key=lambda cycle: abs(float(cycle["total_result"] or cycle["premium"] or 0.0)),
        reverse=True,
    )
    warnings = [cycle for cycle in cycles if cycle["warning_reasons"]]
    warnings.sort(
        key=lambda cycle: abs(float(cycle["total_result"] or cycle["premium"] or 0.0)),
        reverse=True,
    )
    cycles.sort(key=lambda cycle: (cycle["trade_date"] or "", cycle["position_id"]), reverse=True)
    return {
        "cycles": cycles,
        "incomplete_cycles": incomplete,
        "warning_cycles": warnings,
        "summaries": [summaries[strategy] for strategy in STRATEGIES],
        "totals": totals,
    }


__all__ = ["STRATEGIES", "build_strategy_performance"]
