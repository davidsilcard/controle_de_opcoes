from __future__ import annotations

import argparse
import datetime as dt
from typing import Iterable, List, Optional

import yfinance as yf

from .config import (
    get_postgres_shared_schema,
    reset_pg_schema_override,
    set_pg_schema_override,
)
from .db import open_db


def _list_underlyings(conn) -> List[str]:
    rows = conn.execute("SELECT DISTINCT underlying FROM option_snapshots").fetchall()
    symbols: List[str] = []
    for row in rows:
        if not row:
            continue
        try:
            value = row["underlying"]
        except Exception:
            value = row[0]
        if value:
            symbols.append(str(value).strip().upper())
    return symbols


def _ensure_underlyings_table(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS underlying_snapshots (
            snapshot_date TEXT NOT NULL,
            underlying TEXT NOT NULL,
            price DOUBLE PRECISION,
            price_date TEXT,
            mm200 DOUBLE PRECISION,
            return_3m DOUBLE PRECISION,
            trend_flag INTEGER,
            trend_reason TEXT,
            PRIMARY KEY (snapshot_date, underlying)
        )
        """
    )
    conn.commit()


def _insert_price(
    conn,
    *,
    underlying: str,
    date_iso: str,
    price: float,
) -> None:
    conn.execute(
        """
        INSERT INTO underlying_snapshots (snapshot_date, underlying, price, price_date)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (snapshot_date, underlying) DO UPDATE SET
            price = EXCLUDED.price,
            price_date = EXCLUDED.price_date
        """,
        (date_iso, underlying, price, date_iso),
    )


def _symbol_to_yf(sym: str) -> str:
    # B3 tickers no Yahoo Finance normalmente são <TICKER>.SA
    return f"{sym}.SA"


def _backfill_prices(
    conn,
    *,
    underlyings: Iterable[str],
    days: int,
) -> None:
    today = dt.date.today()
    start = today - dt.timedelta(days=days)
    for sym in sorted({u for u in underlyings if u}):
        yf_sym = _symbol_to_yf(sym)
        print(f"Baixando {yf_sym} (desde {start.isoformat()})...")
        hist = yf.download(
            yf_sym,
            start=start.isoformat(),
            end=today.isoformat(),
            interval="1d",
            progress=False,
            auto_adjust=False,
        )
        if hist.empty:
            print(f"  - sem dados para {yf_sym}")
            continue
        for idx, row in hist.iterrows():
            val = row.get("Close")
            try:
                price = float(val.item() if hasattr(val, "item") else val)
            except Exception:
                continue
            if price <= 0:
                continue
            date_iso = idx.date().isoformat() if hasattr(idx, "date") else str(idx)[:10]
            _insert_price(conn, underlying=sym, date_iso=date_iso, price=price)
        conn.commit()
        print(f"  - OK ({len(hist)} cotações)")


def backfill_prices(
    *,
    days: int = 90,
    underlyings: Optional[Iterable[str]] = None,
) -> None:
    """Preenche histórico de preços diários em PostgreSQL usando yfinance."""
    token = set_pg_schema_override(get_postgres_shared_schema())
    try:
        conn = open_db()
    finally:
        reset_pg_schema_override(token)
    try:
        _ensure_underlyings_table(conn)
        if underlyings is None:
            symbols = _list_underlyings(conn)
        else:
            symbols = [u.strip().upper() for u in underlyings if u and u.strip()]
        if not symbols:
            print("Nenhum underlying encontrado para backfill.")
            return
        _backfill_prices(conn, underlyings=symbols, days=max(days, 1))
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill de preços diários via yfinance para underlying_snapshots (PostgreSQL)."
    )
    parser.add_argument(
        "--days",
        type=int,
        default=90,
        help="Quantos dias de histórico baixar (default: 90)",
    )
    parser.add_argument(
        "--underlying",
        action="append",
        help="Underlying específico (pode repetir). Se não informar, usa todos do banco.",
    )
    args = parser.parse_args()

    underlyings: Optional[Iterable[str]] = None
    if args.underlying:
        underlyings = {u.strip().upper() for u in args.underlying if u and u.strip()}

    backfill_prices(days=max(args.days, 1), underlyings=underlyings)


if __name__ == "__main__":
    main()
