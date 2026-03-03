from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .portfolio import list_positions


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


def compute_tax(
    month: int,
    year: int,
    *,
    is_simulated: Optional[bool] = False,
    db_path: Optional[Path] = None,
) -> TaxSummary:
    swing_gain = 0.0
    daytrade_gain = 0.0
    swing_irrf = 0.0
    daytrade_irrf = 0.0

    if db_path is not None:
        raise RuntimeError("Parâmetro db_path não é suportado no backend PostgreSQL.")
    rows = list_positions(include_closed=True, is_simulated=is_simulated)

    for row in rows:
        trade_type = str(row.get("trade_type") or "swing").strip().lower()
        partial_date = row.get("partial_date")
        partial_price = row.get("partial_price")
        partial_qty = int(row.get("partial_qty") or 0)
        qty = int(row.get("qty") or 0)
        entry = float(row.get("entry_price") or 0.0)
        fees = float(row.get("fees") or 0.0)
        exit_date = row.get("exit_date")
        exit_price = row.get("exit_price")
        irrf_value = float(row.get("irrf") or 0.0)
        side_raw = row.get("side")
        side = (side_raw or "long").strip().lower()
        direction = -1 if side in {"short", "vendida", "vendido", "v"} else 1

        def same_month(date_str: str) -> bool:
            if not date_str or len(date_str) < 7:
                return False
            parts = date_str.split("-")
            return int(parts[0]) == year and int(parts[1]) == month

        if partial_qty and partial_price is not None and same_month(str(partial_date)):
            gain = direction * (float(partial_price) - entry) * partial_qty
            if trade_type == "daytrade":
                daytrade_gain += gain
            else:
                swing_gain += gain

        open_qty = max(qty - (partial_qty or 0), 0)
        if exit_price is not None and same_month(str(exit_date)) and open_qty > 0:
            gain = direction * (float(exit_price) - entry) * open_qty - fees
            if trade_type == "daytrade":
                daytrade_gain += gain
            else:
                swing_gain += gain
            if irrf_value:
                if trade_type == "daytrade":
                    daytrade_irrf += irrf_value
                else:
                    swing_irrf += irrf_value

    swing_tax = 0.15 * swing_gain if swing_gain > 0 else 0.0
    daytrade_tax = 0.20 * daytrade_gain if daytrade_gain > 0 else 0.0

    return TaxSummary(
        year=year,
        month=month,
        swing_net=swing_gain,
        daytrade_net=daytrade_gain,
        swing_ir=swing_tax,
        daytrade_ir=daytrade_tax,
        swing_irrf=swing_irrf,
        daytrade_irrf=daytrade_irrf,
    )


__all__ = ["compute_tax", "TaxSummary"]
