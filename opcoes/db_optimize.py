from __future__ import annotations

from typing import Optional

from .db_health import resolve_postgres_target
from .db_migration import sanitize_schema_name


def _quote_ident(value: str) -> str:
    return '"' + str(value).replace('"', '""') + '"'


def optimize_postgres_schema(
    *,
    schema: str,
    include_analyze: bool = True,
) -> dict:
    target, errors = resolve_postgres_target()
    if target is None:
        reasons = "; ".join(errors) if errors else "configuração ausente"
        raise RuntimeError(f"PostgreSQL não configurado: {reasons}")

    try:
        import psycopg
    except Exception as exc:
        raise RuntimeError(
            "Driver psycopg não encontrado. Instale com: uv add psycopg[binary]"
        ) from exc

    schema_name = sanitize_schema_name(schema)
    schema_q = _quote_ident(schema_name)

    statements = [
        # Queries de posições usam latest snapshot por ticker.
        f"CREATE INDEX IF NOT EXISTS idx_option_snapshots_ticker_snapshot_date ON {schema_q}.option_snapshots (ticker, snapshot_date DESC)",
        # Queries de HV/recorrência filtram por underlying + janela temporal.
        f"CREATE INDEX IF NOT EXISTS idx_underlying_snapshots_underlying_snapshot_date ON {schema_q}.underlying_snapshots (underlying, snapshot_date DESC)",
        # Filtros recorrentes da tela de posições.
        f"CREATE INDEX IF NOT EXISTS idx_positions_status_trade_date ON {schema_q}.positions (status, trade_date DESC, id DESC)",
        f"CREATE INDEX IF NOT EXISTS idx_positions_strategy_status ON {schema_q}.positions (strategy_tag, status)",
        # Auditoria/financeiro.
        f"CREATE INDEX IF NOT EXISTS idx_ledger_type_position_id ON {schema_q}.ledger (type, position_id)",
        f"CREATE INDEX IF NOT EXISTS idx_ledger_position_id ON {schema_q}.ledger (position_id)",
        f"CREATE INDEX IF NOT EXISTS idx_ledger_date ON {schema_q}.ledger (date DESC)",
    ]

    applied: list[str] = []
    analyzed: list[str] = []
    skipped: list[str] = []

    with psycopg.connect(target.dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(f"CREATE SCHEMA IF NOT EXISTS {schema_q}")
            for sql in statements:
                try:
                    cur.execute(sql)
                    applied.append(sql)
                except Exception as exc:
                    # Tabela pode não existir em schema novo; não falha hard.
                    skipped.append(f"{sql} -- {exc}")

            if include_analyze:
                for table in ("option_snapshots", "underlying_snapshots", "positions", "ledger"):
                    try:
                        cur.execute(f"ANALYZE {schema_q}.{_quote_ident(table)}")
                        analyzed.append(table)
                    except Exception:
                        continue

    return {
        "schema": schema_name,
        "postgres_target": target.redacted_dsn,
        "applied": applied,
        "analyzed": analyzed,
        "skipped": skipped,
    }


__all__ = ["optimize_postgres_schema"]

