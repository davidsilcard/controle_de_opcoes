from __future__ import annotations

from typing import Any, Dict, List, Mapping

from .. import finance
from ..report import ReportData, generate_report
from ..perf import timed_stage
from ..portfolio import list_positions
from ..ranking_guard import audit_ranking_positions
from ..utils import infer_option_type, parse_ptbr_number
from ..settings import (
    get_ranking_view_settings,
    get_strategy_settings,
    update_ranking_view_settings,
    update_strategy_settings,
)


def _get_int_arg(args: Mapping[str, Any], name: str, default: int) -> int:
    try:
        raw = args.get(name)
        if raw is None or str(raw).strip() == "":
            return default
        return int(raw)
    except (TypeError, ValueError):
        return default


def _get_text_arg(args: Mapping[str, Any], name: str, default: str) -> str:
    if name not in args:
        return default
    raw = args.get(name)
    return str(raw or "").strip()


def _compute_totals(positions: List[Dict]) -> Dict[str, Any]:
    total_purchase = 0.0
    total_current = 0.0
    total_pl = 0.0
    for pos in positions:
        qty = pos.get("qty") or 0
        open_qty = pos.get("open_qty") or 0
        entry = pos.get("entry_price") or 0.0
        last_price = pos.get("last_price")
        realized = pos.get("realized_pl") or 0.0
        pl = pos.get("pl")

        total_purchase += entry * qty
        if last_price is not None:
            total_current += last_price * open_qty
        total_current += realized
        if pl is not None:
            total_pl += pl

    total_pl_pct = (total_pl / total_purchase * 100.0) if total_purchase else None
    return {
        "total_purchase": total_purchase,
        "total_current": total_current,
        "total_pl": total_pl,
        "total_pl_pct": total_pl_pct,
    }


def _segment_opportunities(opps: List[Dict]) -> Dict[str, List[Dict]]:
    segments: Dict[str, List[Dict]] = {
        "carteira": [],
        "alavancagem": [],
        "aposta": [],
    }
    for o in opps:
        status = (o.get("Status_Moneyness") or "").lower()
        delta = o.get("delta")
        try:
            delta_val = abs(float(delta)) if delta is not None else None
        except (TypeError, ValueError):
            delta_val = None

        # Usa delta como critério principal quando disponível.
        if delta_val is not None:
            if delta_val >= 0.7:
                segments["carteira"].append(o)
                continue
            if 0.4 <= delta_val < 0.7:
                segments["alavancagem"].append(o)
                continue
            segments["aposta"].append(o)
            continue

        # Fallback para quando delta não estiver disponível.
        if "itm" in status:
            segments["carteira"].append(o)
            continue
        if "0-5% otm" in status or "colada" in status or "atm" in status:
            segments["alavancagem"].append(o)
            continue
        segments["aposta"].append(o)
    return segments


def _normalize_type(value: str | None, ticker: str | None = None) -> str:
    t = (value or "").strip().upper()
    if t in {"CALL", "PUT"}:
        return t
    inferred = infer_option_type(ticker or "")
    return inferred.upper() if inferred else ""


def _filter_by_type(items: List[Dict], opt_type: str | None) -> List[Dict]:
    if not opt_type:
        return items
    target = opt_type.strip().upper()
    filtered: List[Dict] = []
    for item in items:
        item_type = _normalize_type(item.get("option_type"), item.get("ticker"))
        if target == item_type:
            filtered.append(item)
    return filtered


def _filter_by_underlying(items: List[Dict], underlying_filter: str | None) -> List[Dict]:
    if not underlying_filter:
        return items
    target = underlying_filter.strip().upper()
    if not target:
        return items
    return [
        o
        for o in items
        if target in (o.get("underlying") or "").upper() or target in (o.get("ticker") or "").upper()
    ]


def _has_full_book(item: Mapping[str, Any]) -> bool:
    bid = parse_ptbr_number(item.get("best_bid"))
    ask = parse_ptbr_number(item.get("best_ask"))
    return bid is not None and bid > 0 and ask is not None and ask > 0


def _build_book_availability(
    opportunities: List[Dict[str, Any]],
    theoretical_opportunities: List[Dict[str, Any]],
) -> Dict[str, Any]:
    scoped = list(opportunities) + list(theoretical_opportunities)
    total_count = len(scoped)
    tradeable_count = sum(1 for item in scoped if _has_full_book(item))
    watchlist_count = max(total_count - tradeable_count, 0)
    watchlist_ratio = (watchlist_count / total_count) if total_count else 0.0
    watchlist_ratio_pct = watchlist_ratio * 100.0

    no_tradeable = total_count > 0 and tradeable_count == 0
    mass_missing = total_count >= 5 and watchlist_ratio >= 0.8
    show_warning = no_tradeable or mass_missing
    severity = "danger" if no_tradeable else "warning"

    return {
        "total_count": total_count,
        "tradeable_count": tradeable_count,
        "watchlist_count": watchlist_count,
        "watchlist_ratio_pct": watchlist_ratio_pct,
        "show_warning": show_warning,
        "no_tradeable": no_tradeable,
        "mass_missing": mass_missing,
        "severity": severity,
    }


def _empty_ranking_options_pnl() -> Dict[str, Any]:
    by_type = {
        "CALL": {
            "closed_count": 0,
            "open_count": 0,
            "open_cost": 0.0,
            "realized": 0.0,
            "profit": 0.0,
            "loss": 0.0,
        },
        "PUT": {
            "closed_count": 0,
            "open_count": 0,
            "open_cost": 0.0,
            "realized": 0.0,
            "profit": 0.0,
            "loss": 0.0,
        },
    }
    return {
        "has_rows": False,
        "closed_count": 0,
        "open_count": 0,
        "open_cost": 0.0,
        "closed_entry_cost": 0.0,
        "realized": 0.0,
        "profit": 0.0,
        "loss": 0.0,
        "win_rate_pct": None,
        "by_type": by_type,
        "closed_rows": [],
        "open_rows": [],
    }


def build_ranking_options_pnl_summary(
    positions: List[Mapping[str, Any]],
    *,
    ledger_sums: Mapping[int, Mapping[str, float]],
    option_type_filter: str = "",
    underlying_filter: str = "",
    row_limit: int = 12,
) -> Dict[str, Any]:
    summary = _empty_ranking_options_pnl()
    type_filter = (option_type_filter or "").strip().upper()
    underlying_target = (underlying_filter or "").strip().upper()

    for pos in positions:
        if str(pos.get("strategy_tag") or "").strip().lower() != "ranking":
            continue
        if str(pos.get("side") or "").strip().lower() != "long":
            continue

        ticker = str(pos.get("ticker") or "").strip().upper()
        option_type = infer_option_type(ticker)
        if option_type not in {"CALL", "PUT"}:
            continue
        if type_filter and option_type != type_filter:
            continue

        underlying = str(pos.get("underlying") or "").strip().upper()
        if underlying_target and underlying_target not in underlying and underlying_target not in ticker:
            continue

        pid = int(pos.get("id") or 0)
        qty = int(pos.get("qty") or 0)
        entry_price = float(pos.get("entry_price") or 0.0)
        status = str(pos.get("status") or "").strip().lower()
        sums = ledger_sums.get(pid, {})

        expected_buy = round(
            finance.calculate_option_purchase(
                entry_price=entry_price,
                qty=qty,
                fees=finance.long_option_entry_buy_fees(pos),
            ),
            2,
        )
        buy_amount = float(sums.get(finance.TransactionType.BUY.value) or expected_buy)
        entry_cost = abs(round(buy_amount, 2))
        realized = round(float(sums.get(finance.TransactionType.REALIZED.value) or 0.0), 2)
        row = {
            "id": pid,
            "ticker": ticker,
            "underlying": underlying,
            "option_type": option_type,
            "trade_date": str(pos.get("trade_date") or ""),
            "qty": qty,
            "entry_price": entry_price,
            "entry_cost": entry_cost,
            "status": status,
            "exit_date": str(pos.get("exit_date") or ""),
            "exit_price": pos.get("exit_price"),
            "exit_reason": str(pos.get("exit_reason") or ""),
            "realized": realized,
            "result_class": "profit" if realized > 0 else ("loss" if realized < 0 else "flat"),
        }

        summary["has_rows"] = True
        bucket = summary["by_type"][option_type]
        if status == "closed":
            summary["closed_count"] += 1
            summary["closed_entry_cost"] = round(float(summary["closed_entry_cost"]) + entry_cost, 2)
            summary["realized"] = round(float(summary["realized"]) + realized, 2)
            bucket["closed_count"] += 1
            bucket["realized"] = round(float(bucket["realized"]) + realized, 2)
            if realized > 0:
                summary["profit"] = round(float(summary["profit"]) + realized, 2)
                bucket["profit"] = round(float(bucket["profit"]) + realized, 2)
            elif realized < 0:
                summary["loss"] = round(float(summary["loss"]) + realized, 2)
                bucket["loss"] = round(float(bucket["loss"]) + realized, 2)
            summary["closed_rows"].append(row)
        else:
            summary["open_count"] += 1
            summary["open_cost"] = round(float(summary["open_cost"]) + entry_cost, 2)
            bucket["open_count"] += 1
            bucket["open_cost"] = round(float(bucket["open_cost"]) + entry_cost, 2)
            summary["open_rows"].append(row)

    closed_count = int(summary["closed_count"] or 0)
    if closed_count:
        winning = sum(1 for row in summary["closed_rows"] if row["realized"] > 0)
        summary["win_rate_pct"] = round(winning / closed_count * 100.0, 1)

    summary["closed_rows"].sort(
        key=lambda row: (row.get("exit_date") or "", int(row.get("id") or 0)),
        reverse=True,
    )
    summary["open_rows"].sort(
        key=lambda row: (row.get("trade_date") or "", int(row.get("id") or 0)),
        reverse=True,
    )
    summary["closed_rows"] = summary["closed_rows"][: max(int(row_limit or 0), 0)]
    summary["open_rows"] = summary["open_rows"][: max(int(row_limit or 0), 0)]
    return summary


def calculate_ranking_strategy(
    data: ReportData,
    min_score: int,
    limit: int,
    recurring_days: int,
    recurring_limit: int,
    underlying_filter: str,
    option_type_filter: str,
) -> Dict[str, Any]:
    """
    Pure strategy logic for Ranking.
    Filters opportunities, processes alerts, and calculates totals.
    """
    # Filtering Logic
    opportunities = list(data.opportunities)
    theoretical_opportunities = list(data.theoretical_opportunities)
    rational_opportunities = list(data.rational_opportunities)
    lottery_opportunities = list(data.lottery_opportunities)
    recurring_opportunities = list(data.recurring_opportunities)

    if option_type_filter:
        opportunities = _filter_by_type(opportunities, option_type_filter)
        theoretical_opportunities = _filter_by_type(theoretical_opportunities, option_type_filter)
        rational_opportunities = _filter_by_type(rational_opportunities, option_type_filter)
        lottery_opportunities = _filter_by_type(lottery_opportunities, option_type_filter)
        recurring_opportunities = _filter_by_type(recurring_opportunities, option_type_filter)

    if underlying_filter:
        opportunities = _filter_by_underlying(opportunities, underlying_filter)
        theoretical_opportunities = _filter_by_underlying(theoretical_opportunities, underlying_filter)
        rational_opportunities = _filter_by_underlying(rational_opportunities, underlying_filter)
        lottery_opportunities = _filter_by_underlying(lottery_opportunities, underlying_filter)
        recurring_opportunities = _filter_by_underlying(recurring_opportunities, underlying_filter)

    filtered_data = ReportData(
        snapshot_date=data.snapshot_date,
        opportunities=opportunities,
        theoretical_opportunities=theoretical_opportunities,
        rational_opportunities=rational_opportunities,
        lottery_opportunities=lottery_opportunities,
        positions=data.positions,
        alerts=data.alerts,
        recurring_opportunities=recurring_opportunities,
        recurring_window_start=data.recurring_window_start,
        recurring_window_days=data.recurring_window_days,
        recurring_snapshot_days=data.recurring_snapshot_days,
        hv_window_days=data.hv_window_days,
    )

    # Alert Processing
    alerts_map: Dict[int, List[str]] = {}
    for alert in filtered_data.alerts:
        pos = alert.get("position")
        if not pos:
            continue
        alerts_map[pos.get("id")] = alert.get("reasons", [])

    # Positions & Totals
    positions_real = [p for p in filtered_data.positions if not p.get("is_simulated")]
    positions_simulated = [p for p in filtered_data.positions if p.get("is_simulated")]
    totals_real = _compute_totals(positions_real)
    totals_simulated = _compute_totals(positions_simulated)
    
    # Segmentation
    all_opps = list(filtered_data.opportunities) + list(filtered_data.theoretical_opportunities)
    segments = _segment_opportunities(all_opps)
    book_availability = _build_book_availability(
        filtered_data.opportunities,
        filtered_data.theoretical_opportunities,
    )

    return {
        "data": filtered_data,
        "min_score": min_score,
        "limit": limit,
        "recurring_days": recurring_days,
        "recurring_limit": recurring_limit,
        "underlying_filter": underlying_filter,
        "option_type_filter": option_type_filter,
        "alerts_map": alerts_map,
        "totals_real": totals_real,
        "totals_simulated": totals_simulated,
        "positions_real": positions_real,
        "positions_simulated": positions_simulated,
        "segments": segments,
        "book_availability": book_availability,
        "ranking_audit_issues": [],
        "ranking_options_pnl": _empty_ranking_options_pnl(),
    }


def _build_empty_report_data() -> ReportData:
    return ReportData(
        snapshot_date="-",
        opportunities=[],
        theoretical_opportunities=[],
        rational_opportunities=[],
        lottery_opportunities=[],
        positions=[],
        alerts=[],
        recurring_opportunities=[],
        recurring_window_start=None,
        recurring_window_days=0,
        recurring_snapshot_days=0,
        hv_window_days=21,
    )


def _resolve_ranking_inputs(
    args: Mapping[str, Any],
    *,
    persist_settings: bool,
) -> Dict[str, Any]:
    strat_settings = get_strategy_settings()
    ranking_settings = get_ranking_view_settings()

    min_score = _get_int_arg(args, "min_score", strat_settings.min_score)
    limit = _get_int_arg(args, "limit", strat_settings.limit_opportunities)
    recurring_days = _get_int_arg(args, "recurring_days", strat_settings.recurring_days)
    recurring_limit = _get_int_arg(args, "recurring_limit", ranking_settings.recurring_limit)

    underlying_filter = _get_text_arg(args, "underlying", ranking_settings.underlying_filter).upper()
    option_type_filter = _get_text_arg(args, "option_type", ranking_settings.option_type_filter).upper()
    if option_type_filter in {"CALLS", "CALL"}:
        option_type_filter = "CALL"
    elif option_type_filter in {"PUTS", "PUT"}:
        option_type_filter = "PUT"
    else:
        option_type_filter = ""

    should_persist_filters = any(
        key in args
        for key in (
            "min_score",
            "limit",
            "recurring_days",
            "recurring_limit",
            "underlying",
            "option_type",
        )
    )
    if should_persist_filters and persist_settings:
        update_strategy_settings(
            min_score=min_score,
            limit_opportunities=limit,
            recurring_days=recurring_days,
        )
        update_ranking_view_settings(
            recurring_limit=recurring_limit,
            underlying_filter=underlying_filter,
            option_type_filter=option_type_filter,
        )

    return {
        "min_score": min_score,
        "limit": limit,
        "recurring_days": recurring_days,
        "recurring_limit": recurring_limit,
        "underlying_filter": underlying_filter,
        "option_type_filter": option_type_filter,
    }


def get_ranking_context(args: Mapping[str, Any]) -> Dict[str, Any]:
    resolved = _resolve_ranking_inputs(args, persist_settings=True)
    min_score = int(resolved["min_score"])
    limit = int(resolved["limit"])
    recurring_days = int(resolved["recurring_days"])
    recurring_limit = int(resolved["recurring_limit"])
    underlying_filter = str(resolved["underlying_filter"])
    option_type_filter = str(resolved["option_type_filter"])

    # IO / Data Fetching
    empty_state_message = ""
    try:
        with timed_stage("ranking.generate_report"):
            data: ReportData = generate_report(
                min_score=min_score,
                limit=limit,
                recurring_days=recurring_days,
                recurring_limit=recurring_limit,
            )
    except RuntimeError as exc:
        # Primeiro acesso de usuário novo: ainda sem snapshots.
        if "Nenhum snapshot encontrado" in str(exc):
            data = _build_empty_report_data()
            empty_state_message = (
                "Ainda não há snapshots na base compartilhada. "
                "Rode a coleta (scrape) para começar a visualizar oportunidades."
            )
        else:
            raise
    except Exception as exc:
        # Primeiro acesso: schema ainda não inicializado para snapshots.
        if "option_snapshots" in str(exc).lower() and "does not exist" in str(exc).lower():
            data = _build_empty_report_data()
            empty_state_message = (
                "Ainda não há snapshots na base compartilhada. "
                "Rode a coleta (scrape) para começar a visualizar oportunidades."
            )
        else:
            raise

    # Pure Logic Delegation
    with timed_stage("ranking.calculate_strategy"):
        ctx = calculate_ranking_strategy(
            data=data,
            min_score=min_score,
            limit=limit,
            recurring_days=recurring_days,
            recurring_limit=recurring_limit,
            underlying_filter=underlying_filter,
            option_type_filter=option_type_filter,
        )
    with timed_stage("ranking.audit"):
        audit_positions = list_positions(include_closed=True)
        ledger_sums = finance.get_ledger_sums_by_position(
            types=[
                finance.TransactionType.BUY,
                finance.TransactionType.REALIZED,
            ]
        )
        ctx["ranking_audit_issues"] = audit_ranking_positions(
            audit_positions,
            ledger_sums=ledger_sums,
        )
        ctx["ranking_options_pnl"] = build_ranking_options_pnl_summary(
            audit_positions,
            ledger_sums=ledger_sums,
            option_type_filter=option_type_filter,
            underlying_filter=underlying_filter,
        )
    if empty_state_message:
        ctx["empty_state_message"] = empty_state_message
    return ctx


def get_ranking_shell_context(args: Mapping[str, Any]) -> Dict[str, Any]:
    return _resolve_ranking_inputs(args, persist_settings=True)
