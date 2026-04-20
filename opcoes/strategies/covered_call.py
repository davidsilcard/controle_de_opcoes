from __future__ import annotations

import re
from typing import Any, Dict, List, Mapping, Tuple

from .. import finance
from ..holdings import list_holding_snapshots
from ..market_data import (
    MarketDataClient,
    enrich_option_rows_with_live_market_data,
    enrich_positions_with_live_market_data,
    enrich_underlying_quote_with_live_market_data,
    format_market_timestamp_label,
    market_source_label,
    market_status_label,
)
from ..portfolio import list_positions
from ..perf import timed_stage
from ..snapshot_repository import fetch_latest_underlying_options, fetch_latest_underlying_quote
from ..settings import get_covered_call_settings, update_covered_call_settings
from ..utils import infer_option_type, parse_ptbr_number


def _get_int_arg(args: Mapping[str, Any], name: str, default: int) -> int:
    try:
        raw = args.get(name, default)
        return int(raw)
    except (TypeError, ValueError):
        return default


def _get_float_arg(args: Mapping[str, Any], name: str, default: float) -> float:
    try:
        raw = args.get(name, default)
        return float(raw)
    except (TypeError, ValueError):
        return default


def _get_bool_arg(args: Mapping[str, Any], name: str, default: bool) -> bool:
    raw: Any = None
    if hasattr(args, "getlist"):
        try:
            values = args.getlist(name)  # type: ignore[attr-defined]
            if values:
                raw = values[-1]
        except Exception:
            raw = None
    if raw is None and name in args:
        raw = args.get(name)
    if raw is None:
        return default
    if isinstance(raw, bool):
        return raw
    text = str(raw).strip().lower()
    if text in {"1", "true", "yes", "on", "sim", "s"}:
        return True
    if text in {"0", "false", "no", "off", "nao", "não", "n", ""}:
        return False
    return default


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _looks_like_equity_ticker(value: Any) -> bool:
    text = (value or "").strip().upper()
    if not text:
        return False
    return re.fullmatch(r"[A-Z]{4}\d{1,2}", text) is not None


def _is_short_strategy_position(pos: Dict, strategy_tag: str) -> bool:
    side = (pos.get("side") or "").strip().lower()
    if side == "long":
        return False
    if side == "short":
        return True
    return (pos.get("strategy_tag") or "").strip().lower() == strategy_tag


def _is_stock_lot_position(pos: Mapping[str, Any]) -> bool:
    ticker = (pos.get("ticker") or "").strip().upper()
    underlying = (pos.get("underlying") or "").strip().upper()
    strategy_tag = (pos.get("strategy_tag") or "").strip().lower()
    trade_type = (pos.get("trade_type") or "").strip().lower()
    if not ticker:
        return False
    if (pos.get("side") or "").strip().lower() == "short":
        return False
    open_qty = _safe_int(pos.get("open_qty") or pos.get("qty"))
    if open_qty <= 0:
        return False
    if strategy_tag == "estoque":
        return True
    if strategy_tag == "ranking":
        return False
    if trade_type == "stock":
        return True
    if underlying and ticker == underlying:
        return True
    if not underlying and _looks_like_equity_ticker(ticker):
        return True
    if _looks_like_equity_ticker(ticker) and _looks_like_equity_ticker(underlying):
        return True
    return False


def _stock_reference_underlying(pos: Mapping[str, Any]) -> str:
    if not _is_stock_lot_position(pos):
        return ""
    ticker = (pos.get("ticker") or "").strip().upper()
    underlying = (pos.get("underlying") or "").strip().upper()
    if _looks_like_equity_ticker(underlying):
        return underlying
    return ticker


def _build_underlying_quick_filter(
    positions_open: List[Dict],
    current_underlying: str,
    holding_snapshots: List[Dict[str, Any]] | None = None,
) -> List[Dict[str, Any]]:
    rows: Dict[str, Dict[str, Any]] = {}

    def _ensure_row(ticker: str) -> Dict[str, Any]:
        return rows.setdefault(
            ticker,
            {
                "ticker": ticker,
                "qty_real": 0,
                "qty_simulated": 0,
                "qty_total": 0,
                "has_open_calls": False,
            },
        )

    for pos in positions_open:
        ticker = (pos.get("ticker") or "").strip().upper()
        underlying = (pos.get("underlying") or "").strip().upper()
        open_qty = _safe_int(pos.get("open_qty") or pos.get("qty"))
        is_simulated = bool(pos.get("is_simulated"))

        if _is_stock_lot_position(pos):
            # Para ações em estoque, o ticker é a referência principal de navegação.
            ref_underlying = _stock_reference_underlying(pos)
            if not ref_underlying:
                continue
            item = _ensure_row(ref_underlying)
            if is_simulated:
                item["qty_simulated"] += open_qty
            else:
                item["qty_real"] += open_qty
            item["qty_total"] = int(item["qty_real"] + item["qty_simulated"])
            continue

        if (
            open_qty > 0
            and underlying
            and infer_option_type(ticker) == "CALL"
            and _is_short_strategy_position(pos, "covered_call")
        ):
            item = _ensure_row(underlying)
            item["has_open_calls"] = True

    selected = (current_underlying or "").strip().upper()
    if selected:
        _ensure_row(selected)

    for snapshot in holding_snapshots or []:
        ticker = (snapshot.get("ticker") or "").strip().upper()
        if not ticker:
            continue
        item = _ensure_row(ticker)
        if snapshot.get("is_simulated"):
            item["qty_simulated"] = max(
                int(item.get("qty_simulated") or 0),
                int(snapshot.get("shares_total") or 0),
            )
        else:
            item["qty_real"] = max(
                int(item.get("qty_real") or 0),
                int(snapshot.get("shares_total") or 0),
            )
        item["qty_total"] = int(item["qty_real"] + item["qty_simulated"])
        if int(snapshot.get("shares_reserved") or 0) > 0:
            item["has_open_calls"] = True

    ordered = sorted(
        rows.values(),
        key=lambda item: (
            item["ticker"] != selected,
            -int(item.get("qty_total") or 0),
            item["ticker"],
        ),
    )
    return ordered


def _bova_coverage(
    positions: List[Dict],
    underlying: str,
    *,
    holding_snapshot: Dict[str, Any] | None = None,
) -> Tuple[Dict[str, Any], List[Dict], List[Dict]]:
    """Replica a lógica original de _bova_coverage de web.py.

    - Lotes do ativo-objeto: referencia normalizada do lote == underlying
    - Calls do ativo-objeto: underlying == underlying e ticker != underlying
    """

    underlying = (underlying or "").strip().upper()
    if not underlying:
        return {}, [], []

    # Lotes do ativo-objeto (referencia normalizada do lote == underlying)
    bova_lots: List[Dict] = [
        p
        for p in positions
        if _stock_reference_underlying(p) == underlying
    ]
    # Calls do ativo-objeto (underlying == underlying, ticker != underlying, tipo CALL)
    call_positions: List[Dict] = [
        p
        for p in positions
        if (p.get("underlying") or "").strip().upper() == underlying
        and (p.get("ticker") or "").strip().upper() != underlying
        and infer_option_type(p.get("ticker")) == "CALL"
        and _is_short_strategy_position(p, "covered_call")
    ]

    # Ordena lotes e calls por data (FIFO)
    def _key_date(pos: Dict) -> str:
        return str(pos.get("trade_date") or "")

    bova_lots = sorted(bova_lots, key=_key_date)
    call_positions = sorted(call_positions, key=_key_date)

    # Inicializa cobertura por lote
    lot_infos: List[Dict] = []
    for p in bova_lots:
        open_qty = int(p.get("open_qty") or p.get("qty") or 0)
        lot_infos.append(
            {
                "id": p["id"],
                "trade_date": p.get("trade_date"),
                "qty_total": int(p.get("qty") or 0),
                "open_qty": open_qty,
                "covered": 0,
                "free": open_qty,
                "entry_price": float(p.get("entry_price") or 0.0),
            }
        )

    # Mapa auxiliar por id para lookup rápido durante a alocação.
    lot_by_id = {int(l["id"]): l for l in lot_infos if l.get("id") is not None}

    # Alocação FIFO: assumimos 1:1 entre opções e ações, respeitando parent_position_id quando existir.
    for call in call_positions:
        open_contracts = int(call.get("open_qty") or call.get("qty") or 0)
        need = open_contracts
        if need <= 0:
            continue
        parent_id = call.get("parent_position_id")
        lot = None
        if parent_id is not None:
            try:
                lot = lot_by_id.get(int(parent_id))
            except (TypeError, ValueError):
                lot = None
        if lot is None:
            # sem vínculo explícito: não aloca coberturas neste helper
            continue
        available = max(lot["open_qty"] - lot["covered"], 0)
        if available <= 0:
            continue
        alloc = min(available, need)
        lot["covered"] += alloc
        lot["free"] = max(lot["open_qty"] - lot["covered"], 0)

    # Resumo agregado
    shares_total = sum(l["open_qty"] for l in lot_infos)
    shares_covered = sum(int(c.get("open_qty") or c.get("qty") or 0) for c in call_positions)
    shares_free = max(shares_total - shares_covered, 0)

    free_min = None
    free_max = None
    free_avg = None
    if holding_snapshot is not None and int(holding_snapshot.get("shares_total") or 0) > 0:
        shares_total = int(holding_snapshot.get("shares_total") or 0)
        shares_covered = int(holding_snapshot.get("shares_reserved") or 0)
        shares_free = max(int(holding_snapshot.get("shares_free") or 0), 0)
        avg_price = holding_snapshot.get("avg_price")
        if avg_price is not None:
            free_min = float(avg_price)
            free_max = float(avg_price)
            free_avg = float(avg_price)
    elif shares_free > 0:
        free_sum = 0.0
        for l in lot_infos:
            f = l["free"]
            if f <= 0:
                continue
            price = l["entry_price"]
            free_sum += price * f
            if free_min is None or price < free_min:
                free_min = price
            if free_max is None or price > free_max:
                free_max = price
        free_avg = (free_sum / shares_free) if shares_free > 0 else None

    stock_summary: Dict[str, Any] = {
        "shares_total": int(shares_total),
        "shares_covered": int(shares_covered),
        "shares_free": int(shares_free),
        "free_min_price": free_min,
        "free_max_price": free_max,
        "free_avg_price": free_avg,
    }

    return stock_summary, lot_infos, call_positions


def _call_cashflow_summaries(
    call_positions: List[Dict],
    lots: List[Dict],
    *,
    avg_cost_fallback: float | None = None,
) -> List[Dict]:
    total_shares = sum(l.get("open_qty") or 0 for l in lots)
    avg_cost_global = avg_cost_fallback
    if total_shares > 0:
        cost_sum = sum((l.get("open_qty") or 0) * (l.get("entry_price") or 0.0) for l in lots)
        if cost_sum:
            avg_cost_global = cost_sum / total_shares

    lot_by_id = {int(l["id"]): l for l in lots if l.get("id") is not None}

    summaries: List[Dict] = []
    for pos in call_positions:
        qty = int(pos.get("open_qty") or pos.get("qty") or 0)
        if qty <= 0:
            continue
        trade_type = (pos.get("trade_type") or "swing").strip().lower()
        aliquota_acao = 0.15
        price_call = float(pos.get("entry_price") or 0.0)
        fees = float(pos.get("fees") or 0.0)
        strike = pos.get("strike")

        parent_id = pos.get("parent_position_id")
        local_avg_cost = avg_cost_global
        if parent_id is not None:
            try:
                lot = lot_by_id.get(int(parent_id))
            except (TypeError, ValueError):
                lot = None
            if lot is not None:
                local_avg_cost = float(lot.get("entry_price") or 0.0)

        premium_bruto = price_call * qty
        premium_amount = finance.calculate_option_premium(
            entry_price=price_call,
            qty=qty,
            fees=fees,
        )
        darf_premio = finance.calculate_darf_provision(
            premium_amount=premium_amount,
            trade_type=trade_type,
        )
        ir_premio = -darf_premio
        premio_liq = premium_amount + darf_premio

        pl_expira = premio_liq
        pl_expira_pct = None

        pl_exercicio = None
        avg_cost = local_avg_cost
        pl_exercicio_pct = None
        if local_avg_cost is not None and strike is not None:
            try:
                strike_val = float(strike)
            except (TypeError, ValueError):
                strike_val = None
            if strike_val is not None:
                ganho_papel = (strike_val - local_avg_cost) * qty
                ir_papel = max(0.0, ganho_papel) * aliquota_acao
                ganho_bruto_total = premium_bruto + ganho_papel
                pl_exercicio = ganho_bruto_total - fees - ir_premio - ir_papel

        capital = None
        if local_avg_cost is not None and qty > 0:
            capital = local_avg_cost * qty
        if capital and pl_expira is not None:
            pl_expira_pct = (pl_expira / capital) * 100.0
        if capital and pl_exercicio is not None:
            pl_exercicio_pct = (pl_exercicio / capital) * 100.0

        summaries.append(
            {
                "position_id": pos.get("id"),
                "lot_id": pos.get("parent_position_id"),
                "ticker": pos.get("ticker"),
                "qty": qty,
                "open_qty": qty,
                "strike": strike,
                "avg_cost": avg_cost,
                "premium_bruto": premium_bruto,
                "premio_liq": premio_liq,
                "pl_expira": pl_expira,
                "pl_exercicio": pl_exercicio,
                "pl_expira_pct": pl_expira_pct,
                "pl_exercicio_pct": pl_exercicio_pct,
            }
        )
    return summaries


def _parse_float(value) -> float | None:
    try:
        return float(parse_ptbr_number(value))
    except Exception:
        return None


def _pick_call_premium(row: Mapping[str, Any]) -> tuple[float | None, str]:
    for key in ("best_bid", "ultimo", "preco_teorico"):
        val = _parse_float(row.get(key))
        if val is not None and val > 0:
            return val, key
    return None, ""


def _extrinsic_pct_spot_from_premium_ref(
    *,
    premium_ref: float | None,
    strike: float | None,
    underlying_price: float | None,
) -> float | None:
    if premium_ref is None or underlying_price is None or underlying_price <= 0:
        return None
    intrinsic = 0.0
    if strike is not None:
        intrinsic = max(float(underlying_price) - float(strike), 0.0)
    extrinsic = max(float(premium_ref) - intrinsic, 0.0)
    return (extrinsic / float(underlying_price)) * 100.0


def _apply_buyback_metrics(
    call_positions: List[Dict],
    *,
    buyback_target_pct: float,
) -> List[Dict]:
    output: List[Dict] = []
    for pos in call_positions:
        pos_data = dict(pos)
        entry = pos_data.get("entry_price") or 0.0
        last_price = pos_data.get("last_price")
        open_qty = pos_data.get("open_qty") or pos_data.get("qty") or 0

        buyback_profit_per_share = None
        buyback_profit_total = None
        buyback_profit_pct = None
        buyback_target_hit = False

        if entry and last_price is not None and open_qty:
            try:
                buyback_profit_per_share = float(entry) - float(last_price)
                buyback_profit_total = buyback_profit_per_share * int(open_qty)
                if entry > 0:
                    buyback_profit_pct = (buyback_profit_per_share / float(entry)) * 100.0
            except Exception:
                buyback_profit_per_share = None
                buyback_profit_total = None
                buyback_profit_pct = None

        if buyback_profit_pct is not None and buyback_target_pct is not None:
            buyback_target_hit = buyback_profit_pct >= float(buyback_target_pct)

        pos_data["buyback_profit_per_share"] = buyback_profit_per_share
        pos_data["buyback_profit_total"] = buyback_profit_total
        pos_data["buyback_profit_pct"] = buyback_profit_pct
        pos_data["buyback_target_hit"] = buyback_target_hit
        output.append(pos_data)
    return output


def calculate_covered_call_strategy(
    underlying: str,
    positions_open: List[Dict],
    options_rows: List[Dict],
    quote: Dict | None,
    min_extrinsic: float,
    min_days: int,
    max_days: int,
    min_dist_strike: float,
    buyback_target_pct: float,
    target_upside_pct: float,
    only_target_hits: bool,
    holding_snapshots: List[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    """
    Pure strategy logic for Covered Call.
    Calculates coverage, cashflows, and finds best suggestions based on provided data.
    """
    positions_real = [p for p in positions_open if not p.get("is_simulated")]
    positions_simulated = [p for p in positions_open if p.get("is_simulated")]

    holding_map = {
        (str(item.get("ticker") or "").strip().upper(), bool(item.get("is_simulated"))): item
        for item in (holding_snapshots or [])
        if (item.get("ticker") or "").strip()
    }
    stock_real, lots_real, covered_real = _bova_coverage(
        positions_real,
        underlying,
        holding_snapshot=holding_map.get((underlying, False)),
    )
    stock_sim, lots_sim, covered_sim = _bova_coverage(
        positions_simulated,
        underlying,
        holding_snapshot=holding_map.get((underlying, True)),
    )

    spot_price = _parse_float(quote.get("price") if quote else None)
    avg_free_price = stock_real.get("free_avg_price")
    if avg_free_price is None:
        avg_free_price = stock_sim.get("free_avg_price")
    base_price = None
    if avg_free_price is not None and spot_price is not None:
        base_price = max(float(avg_free_price), float(spot_price))
    elif avg_free_price is not None:
        base_price = float(avg_free_price)
    elif spot_price is not None:
        base_price = float(spot_price)
    target_price = None
    if base_price is not None:
        target_price = base_price * (1.0 + (float(target_upside_pct or 0.0) / 100.0))
    strike_floor_price = stock_real.get("free_avg_price")
    if strike_floor_price is None:
        strike_floor_price = stock_sim.get("free_avg_price")
    if strike_floor_price is None:
        strike_floor_price = stock_real.get("free_max_price")
    if strike_floor_price is None:
        strike_floor_price = stock_sim.get("free_max_price")

    call_summary_real = _call_cashflow_summaries(
        covered_real,
        lots_real,
        avg_cost_fallback=stock_real.get("free_avg_price"),
    )
    call_summary_sim = _call_cashflow_summaries(
        covered_sim,
        lots_sim,
        avg_cost_fallback=stock_sim.get("free_avg_price"),
    )
    covered_real = _apply_buyback_metrics(covered_real, buyback_target_pct=buyback_target_pct)
    covered_sim = _apply_buyback_metrics(covered_sim, buyback_target_pct=buyback_target_pct)

    # Reuses the existing helper, but we need to adapt _fetch_bova_suggestions logic
    # to accept rows instead of fetching them.
    # Since _fetch_bova_suggestions was tightly coupled with fetching, we'll inline/adapt its filtering logic here
    # or extract a pure filter function.
    # To keep it clean, let's look at _fetch_bova_suggestions again.
    # It fetches AND filters. We should split it.
    
    # Let's do the filtering here directly on options_rows
    all_suggestions: List[Dict] = []
    for r in options_rows:
        opt_type = (r.get("option_type") or infer_option_type(r.get("ticker")) or "").upper()
        if opt_type and opt_type != "CALL":
            continue
        dias_uteis = _parse_float(r["dias_uteis"])
        if dias_uteis is None:
            continue
        if dias_uteis < min_days or dias_uteis > max_days:
            continue
        strike = _parse_float(r["strike"])
        underlying_price = _parse_float(r["underlying_price"])
        premium, premium_source = _pick_call_premium(r)
        extrinsic_ref_pct = _extrinsic_pct_spot_from_premium_ref(
            premium_ref=premium,
            strike=strike,
            underlying_price=underlying_price,
        )
        extrinsic = extrinsic_ref_pct
        if extrinsic is None:
            extrinsic = _parse_float(r["extrinsic_pct_spot"])
        if extrinsic is None or extrinsic < min_extrinsic:
            continue
        dist = _parse_float(r["dist_perc_strike"])
        if dist is None or dist < min_dist_strike:
            continue
        if (
            strike_floor_price is not None
            and strike is not None
            and float(strike) < float(strike_floor_price)
        ):
            continue
        effective_sale_price = (strike + premium) if (strike is not None and premium is not None) else None
        target_hit = bool(target_price is not None and effective_sale_price is not None and effective_sale_price >= target_price)
        strike_target_hit = bool(target_price is not None and strike is not None and strike >= target_price)
        premium_pct_base = None
        if base_price and base_price > 0 and premium is not None:
            premium_pct_base = (premium / base_price) * 100.0
        meta_advantage_pct = None
        if target_price and target_price > 0 and effective_sale_price is not None:
            meta_advantage_pct = ((effective_sale_price / target_price) - 1.0) * 100.0

        suggestion = {
            "ticker": r["ticker"],
            "underlying": r["underlying"],
            "vencimento": r["vencimento"],
            "dias_uteis": int(dias_uteis),
            "strike": strike,
            "dist_perc_strike": _parse_float(r["dist_perc_strike"]),
            "underlying_price": underlying_price,
            "extrinsic_pct_spot": extrinsic,
            "pct_2x": _parse_float(r["pct_2x"]),
            "score_total": _parse_float(r["score_total"]),
            "premium_ref": premium,
            "premium_source": premium_source,
            "market_status": r.get("market_status"),
            "market_time_utc": r.get("market_time_utc"),
            "underlying_market_status": r.get("underlying_market_status"),
            "effective_sale_price": effective_sale_price,
            "target_hit": target_hit,
            "strike_target_hit": strike_target_hit,
            "premium_pct_base": premium_pct_base,
            "meta_advantage_pct": meta_advantage_pct,
        }
        all_suggestions.append(suggestion)

    all_suggestions.sort(
        key=lambda s: (
            not bool(s.get("target_hit")),
            s.get("dias_uteis") or 0,
            -(s.get("extrinsic_pct_spot") or 0.0),
        )
    )
    hits_count = sum(1 for s in all_suggestions if s.get("target_hit"))
    if only_target_hits:
        suggestions = [s for s in all_suggestions if s.get("target_hit")]
    else:
        suggestions = all_suggestions

    if only_target_hits:
        ranking_pool = suggestions
    else:
        target_pool = [s for s in suggestions if s.get("target_hit")]
        ranking_pool = target_pool if target_pool else suggestions
    best_idx = None
    best_score = None
    for idx, s in enumerate(ranking_pool):
        extr = s.get("extrinsic_pct_spot")
        dias = s.get("dias_uteis")
        if extr is None or dias is None or dias <= 0:
            continue
        score = extr / dias
        if best_score is None or score > best_score:
            best_score = score
            best_idx = idx
    if best_idx is not None:
        ranking_pool[best_idx]["best_flag"] = True
        ranking_pool[best_idx]["best_yield_per_day"] = best_score

    return {
        "underlying": underlying,
        "underlying_quote": quote,
        "stock_real": stock_real,
        "stock_sim": stock_sim,
        "covered_real": covered_real,
        "covered_sim": covered_sim,
        "lots_real": lots_real,
        "lots_sim": lots_sim,
        "call_summary_real": call_summary_real,
        "call_summary_sim": call_summary_sim,
        "suggestions": suggestions,
        "sell_target": {
            "upside_pct": float(target_upside_pct or 0.0),
            "spot_price": spot_price,
            "avg_free_price": avg_free_price,
            "strike_floor_price": strike_floor_price,
            "base_price": base_price,
            "target_price": target_price,
            "hits_count": hits_count,
        },
        "buyback_target_pct": buyback_target_pct,
        "buyback_candidates_real": [p for p in covered_real if p.get("buyback_target_hit")],
        "buyback_candidates_simulated": [p for p in covered_sim if p.get("buyback_target_hit")],
    }


def get_covered_call_context(
    args: Mapping[str, Any],
    *,
    market_data_client: MarketDataClient | None = None,
    persist_settings: bool = True,
    include_financial_sections: bool = True,
) -> Dict[str, Any]:
    defaults = get_covered_call_settings()

    underlying = (args.get("underlying") or defaults.underlying).strip().upper()
    min_extrinsic = _get_float_arg(args, "min_extrinsic", defaults.min_extrinsic)
    min_days = _get_int_arg(args, "min_days", defaults.min_days)
    max_days = _get_int_arg(args, "max_days", defaults.max_days)
    min_dist_strike = _get_float_arg(args, "min_dist_strike", defaults.min_dist_strike)
    target_upside_pct = _get_float_arg(args, "target_upside_pct", 12.0)
    only_target_hits = _get_bool_arg(args, "only_target_hits", defaults.only_target_hits)

    # IO / Data Fetching
    with timed_stage("covered_call.positions_open"):
        positions_open = list_positions(include_closed=False)
    positions_open = enrich_positions_with_live_market_data(
        positions_open,
        client=market_data_client,
    )
    with timed_stage("covered_call.holding_snapshots"):
        holding_snapshots = list_holding_snapshots(
            underlying_filter=underlying or None,
            positions_open=positions_open,
        )
    underlying_quick_filter = _build_underlying_quick_filter(
        positions_open,
        underlying,
        holding_snapshots,
    )
    # We fetch rows here instead of inside the helper
    with timed_stage("covered_call.options_rows"):
        options_rows = fetch_latest_underlying_options(underlying=underlying)
    options_rows = enrich_option_rows_with_live_market_data(
        options_rows,
        underlying=underlying,
        client=market_data_client,
    )
    with timed_stage("covered_call.underlying_quote"):
        quote = fetch_latest_underlying_quote(underlying)
    quote = enrich_underlying_quote_with_live_market_data(
        quote,
        underlying=underlying,
        client=market_data_client,
    )

    if args and persist_settings:
        update_covered_call_settings(
            underlying=underlying,
            min_extrinsic=min_extrinsic,
            min_days=min_days,
            max_days=max_days,
            min_dist_strike=min_dist_strike,
            buyback_target_pct=defaults.buyback_target_pct,
            only_target_hits=only_target_hits,
        )

    ctx = calculate_covered_call_strategy(
        underlying=underlying,
        positions_open=positions_open,
        options_rows=options_rows,
        quote=quote,
        min_extrinsic=min_extrinsic,
        min_days=min_days,
        max_days=max_days,
        min_dist_strike=min_dist_strike,
        buyback_target_pct=defaults.buyback_target_pct,
        target_upside_pct=target_upside_pct,
        only_target_hits=only_target_hits,
        holding_snapshots=holding_snapshots,
    )

    # Visão financeira didática para cliente:
    # - prêmio líquido fiscal: PREMIUM + DARF
    # - resultado operacional: PREMIUM + DARF + recompra (BUY)
    monthly_premiums: list[dict[str, Any]] = []
    simulated_monthly_premiums: list[dict[str, Any]] = []
    monthly_operational_result: list[dict[str, Any]] = []
    simulated_monthly_operational_result: list[dict[str, Any]] = []
    if include_financial_sections:
        monthly_premiums = finance.get_monthly_premiums(
            include_darf=True,
            include_buyback=False,
            is_simulated=False,
            strategy_tag="covered_call",
        )
        simulated_monthly_premiums = finance.get_monthly_premiums(
            include_darf=True,
            include_buyback=False,
            is_simulated=True,
            strategy_tag="covered_call",
        )
        monthly_operational_result = finance.get_monthly_premiums(
            include_darf=True,
            include_buyback=True,
            is_simulated=False,
            strategy_tag="covered_call",
        )
        simulated_monthly_operational_result = finance.get_monthly_premiums(
            include_darf=True,
            include_buyback=True,
            is_simulated=True,
            strategy_tag="covered_call",
        )

    ctx["filters"] = {
        "min_extrinsic": min_extrinsic,
        "min_days": min_days,
        "max_days": max_days,
        "min_dist_strike": min_dist_strike,
        "target_upside_pct": target_upside_pct,
        "only_target_hits": only_target_hits,
    }
    ctx["underlying_quick_filter"] = underlying_quick_filter
    ctx["monthly_premiums"] = monthly_premiums
    ctx["simulated_monthly_premiums"] = simulated_monthly_premiums
    ctx["monthly_operational_result"] = monthly_operational_result
    ctx["simulated_monthly_operational_result"] = simulated_monthly_operational_result
    if ctx.get("underlying_quote"):
        ctx["underlying_quote"]["market_status_label"] = market_status_label(
            ctx["underlying_quote"].get("market_status")
        )
        ctx["underlying_quote"]["market_source_label"] = market_source_label(
            ctx["underlying_quote"].get("market_price_source")
        )
        ctx["underlying_quote"]["market_time_display"] = format_market_timestamp_label(
            ctx["underlying_quote"].get("market_time_utc")
            or ctx["underlying_quote"].get("price_date")
            or ctx["underlying_quote"].get("snapshot_date")
        )
    for key in ("covered_real", "covered_sim", "suggestions"):
        for item in ctx.get(key, []) or []:
            if isinstance(item, dict):
                item["market_status_label"] = market_status_label(item.get("market_status"))
                item["market_source_label"] = market_source_label(
                    item.get("market_price_source") or item.get("market_premium_source")
                )
                item["market_time_display"] = format_market_timestamp_label(
                    item.get("market_time_utc")
                    or item.get("underlying_price_date")
                    or item.get("snapshot_date")
                    or item.get("last_snapshot_date")
                )
                item["underlying_market_status_label"] = market_status_label(
                    item.get("underlying_market_status")
                )
                item["underlying_market_time_display"] = format_market_timestamp_label(
                    item.get("underlying_market_time_utc")
                    or item.get("underlying_price_date")
                    or item.get("snapshot_date")
                    or item.get("last_snapshot_date")
                )
    return ctx
