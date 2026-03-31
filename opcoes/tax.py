from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Optional, Sequence

from .portfolio import list_positions


@dataclass(frozen=True)
class TaxEvent:
    date: str
    period: str
    trade_type: str
    qty: int
    amount: float
    irrf: float
    phase: str
    position_id: Optional[int]
    ticker: Optional[str]
    underlying: Optional[str]
    is_simulated: bool


@dataclass
class TaxSummary:
    year: int
    month: int
    swing_net: float
    daytrade_net: float
    swing_ir: float
    daytrade_ir: float
    swing_irrf: float
    daytrade_irrf: float
    swing_taxable: float = 0.0
    daytrade_taxable: float = 0.0
    swing_loss_carry_in: float = 0.0
    daytrade_loss_carry_in: float = 0.0
    swing_loss_carry_out: float = 0.0
    daytrade_loss_carry_out: float = 0.0
    total_ir: float = 0.0
    total_irrf: float = 0.0
    net_ir_due: float = 0.0

    @property
    def period(self) -> str:
        return f"{self.year:04d}-{self.month:02d}"


def _normalize_trade_bucket(value: str | None) -> str:
    return "daytrade" if "day" in str(value or "").strip().lower() else "swing"


def _parse_period(period: str) -> tuple[int, int]:
    text = (period or "").strip()
    if len(text) != 7 or text[4] != "-":
        raise ValueError("Período inválido (use YYYY-MM).")
    year = int(text[:4])
    month = int(text[5:7])
    if month < 1 or month > 12:
        raise ValueError("Período inválido (mês).")
    return year, month


def _format_period(year: int, month: int) -> str:
    return f"{int(year):04d}-{int(month):02d}"


def build_position_tax_events(position: Mapping[str, object]) -> list[TaxEvent]:
    trade_type = _normalize_trade_bucket(str(position.get("trade_type") or "swing"))
    qty = int(position.get("qty") or 0)
    entry_price = float(position.get("entry_price") or 0.0)
    fees = float(position.get("fees") or 0.0)
    partial_qty = int(position.get("partial_qty") or 0)
    partial_price = position.get("partial_price")
    partial_date = str(position.get("partial_date") or "").strip()
    exit_date = str(position.get("exit_date") or "").strip()
    exit_price = position.get("exit_price")
    irrf = float(position.get("irrf") or 0.0)
    side = str(position.get("side") or "long").strip().lower()
    direction = -1 if side in {"short", "vendida", "vendido", "v"} else 1
    open_qty = max(qty - partial_qty, 0)

    events: list[TaxEvent] = []

    if partial_qty > 0 and partial_price is not None and partial_date:
        amount = direction * (float(partial_price) - entry_price) * partial_qty
        events.append(
            TaxEvent(
                date=partial_date,
                period=partial_date[:7],
                trade_type=trade_type,
                qty=int(partial_qty),
                amount=round(float(amount), 2),
                irrf=0.0,
                phase="partial",
                position_id=int(position.get("id")) if position.get("id") is not None else None,
                ticker=str(position.get("ticker") or "").strip().upper() or None,
                underlying=str(position.get("underlying") or "").strip().upper() or None,
                is_simulated=bool(position.get("is_simulated") or 0),
            )
        )

    if open_qty > 0 and exit_price is not None and exit_date:
        amount = (direction * (float(exit_price) - entry_price) * open_qty) - fees
        events.append(
            TaxEvent(
                date=exit_date,
                period=exit_date[:7],
                trade_type=trade_type,
                qty=int(open_qty),
                amount=round(float(amount), 2),
                irrf=round(float(irrf), 2),
                phase="close",
                position_id=int(position.get("id")) if position.get("id") is not None else None,
                ticker=str(position.get("ticker") or "").strip().upper() or None,
                underlying=str(position.get("underlying") or "").strip().upper() or None,
                is_simulated=bool(position.get("is_simulated") or 0),
            )
        )

    return [event for event in events if event.period and len(event.period) == 7]


def list_tax_events(
    *,
    is_simulated: Optional[bool] = False,
    positions: Optional[Sequence[Mapping[str, object]]] = None,
) -> list[TaxEvent]:
    rows = (
        list(positions)
        if positions is not None
        else list_positions(include_closed=True, is_simulated=is_simulated)
    )
    events: list[TaxEvent] = []
    for row in rows:
        if is_simulated is not None and bool(row.get("is_simulated") or 0) != bool(
            is_simulated
        ):
            continue
        events.extend(build_position_tax_events(row))

    phase_order = {"partial": 0, "close": 1}
    events.sort(
        key=lambda event: (
            event.date,
            phase_order.get(event.phase, 99),
            int(event.position_id or 0),
        )
    )
    return events


def _compute_bucket_for_period(
    *,
    bucket: str,
    target_period: str,
    events: Sequence[TaxEvent],
) -> dict[str, float]:
    carry = 0.0
    month_net = 0.0
    month_irrf = 0.0
    prior_periods = sorted(
        {
            event.period
            for event in events
            if event.trade_type == bucket and event.period < target_period
        }
    )

    for period in prior_periods:
        period_total = round(
            sum(
                float(event.amount)
                for event in events
                if event.trade_type == bucket and event.period == period
            ),
            2,
        )
        if period_total >= 0:
            carry = max(carry - period_total, 0.0)
        else:
            carry += abs(period_total)

    month_net = round(
        sum(
            float(event.amount)
            for event in events
            if event.trade_type == bucket and event.period == target_period
        ),
        2,
    )
    month_irrf = round(
        sum(
            float(event.irrf)
            for event in events
            if event.trade_type == bucket and event.period == target_period
        ),
        2,
    )

    carry_in = round(carry, 2)
    if month_net > 0:
        taxable = max(month_net - carry_in, 0.0)
        carry_out = max(carry_in - month_net, 0.0)
    elif month_net < 0:
        taxable = 0.0
        carry_out = carry_in + abs(month_net)
    else:
        taxable = 0.0
        carry_out = carry_in

    rate = 0.20 if bucket == "daytrade" else 0.15
    return {
        "net": round(month_net, 2),
        "irrf": round(month_irrf, 2),
        "carry_in": round(carry_in, 2),
        "carry_out": round(carry_out, 2),
        "taxable": round(taxable, 2),
        "ir": round(taxable * rate, 2),
    }


def compute_tax_from_events(
    *,
    month: int,
    year: int,
    events: Sequence[TaxEvent],
) -> TaxSummary:
    target_period = _format_period(year, month)
    swing = _compute_bucket_for_period(
        bucket="swing",
        target_period=target_period,
        events=events,
    )
    daytrade = _compute_bucket_for_period(
        bucket="daytrade",
        target_period=target_period,
        events=events,
    )
    total_ir = round(float(swing["ir"]) + float(daytrade["ir"]), 2)
    total_irrf = round(float(swing["irrf"]) + float(daytrade["irrf"]), 2)
    net_ir_due = round(max(total_ir - total_irrf, 0.0), 2)
    return TaxSummary(
        year=int(year),
        month=int(month),
        swing_net=float(swing["net"]),
        daytrade_net=float(daytrade["net"]),
        swing_ir=float(swing["ir"]),
        daytrade_ir=float(daytrade["ir"]),
        swing_irrf=float(swing["irrf"]),
        daytrade_irrf=float(daytrade["irrf"]),
        swing_taxable=float(swing["taxable"]),
        daytrade_taxable=float(daytrade["taxable"]),
        swing_loss_carry_in=float(swing["carry_in"]),
        daytrade_loss_carry_in=float(daytrade["carry_in"]),
        swing_loss_carry_out=float(swing["carry_out"]),
        daytrade_loss_carry_out=float(daytrade["carry_out"]),
        total_ir=total_ir,
        total_irrf=total_irrf,
        net_ir_due=net_ir_due,
    )


def compute_tax(
    month: int,
    year: int,
    *,
    is_simulated: Optional[bool] = False,
    db_path=None,
) -> TaxSummary:
    if db_path is not None:
        raise RuntimeError("Parâmetro db_path não é suportado no backend PostgreSQL.")
    events = list_tax_events(is_simulated=is_simulated)
    return compute_tax_from_events(month=month, year=year, events=events)


def list_monthly_tax_summaries(
    *,
    periods: Sequence[str],
    is_simulated: Optional[bool] = False,
    positions: Optional[Sequence[Mapping[str, object]]] = None,
) -> list[TaxSummary]:
    events = list_tax_events(is_simulated=is_simulated, positions=positions)
    summaries: list[TaxSummary] = []
    for period in periods:
        year, month = _parse_period(period)
        summaries.append(
            compute_tax_from_events(month=month, year=year, events=events)
        )
    return summaries


def list_tax_events_for_period(
    *,
    period: str,
    is_simulated: Optional[bool] = False,
    positions: Optional[Sequence[Mapping[str, object]]] = None,
) -> list[TaxEvent]:
    _parse_period(period)
    events = list_tax_events(is_simulated=is_simulated, positions=positions)
    return [event for event in events if event.period == period]


__all__ = [
    "TaxEvent",
    "TaxSummary",
    "build_position_tax_events",
    "compute_tax",
    "compute_tax_from_events",
    "list_monthly_tax_summaries",
    "list_tax_events",
    "list_tax_events_for_period",
]
