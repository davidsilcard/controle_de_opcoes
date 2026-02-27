import datetime as dt
import os
import sqlite3
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .config import get_data_backend, get_db_path, get_postgres_schema
from .db_health import resolve_postgres_target


class TransactionType(str, Enum):
    DEPOSIT = "DEPOSIT"      # Aporte novo
    WITHDRAWAL = "WITHDRAW"  # Retirada
    PREMIUM = "PREMIUM"      # Prêmio recebido de venda de opção
    ASSIGNMENT = "ASSIGN"    # Custo de exercício (compra da ação)
    BUY = "BUY"              # Compra direta de ativo
    SELL = "SELL"            # Venda direta de ativo
    DARF = "DARF"            # Provisão/pagamento de IR (DARF)
    DIVIDEND = "DIVIDEND"    # Dividendos recebidos


@dataclass
class Transaction:
    id: int
    date: str
    type: TransactionType
    amount: float
    description: Optional[str] = None
    position_id: Optional[int] = None  # Link opcional com uma posição específica
    is_simulated: bool = False
    position_strategy_tag: Optional[str] = None


def _sqlite_timeout_seconds() -> float:
    raw = os.getenv("OPCOES_SQLITE_TIMEOUT_SECONDS", "30").strip()
    try:
        value = float(raw)
    except ValueError:
        value = 30.0
    if value <= 0:
        value = 30.0
    return value


class _PgResult:
    def __init__(
        self,
        rows: Optional[list[Mapping[str, Any]]] = None,
        *,
        rowcount: int = 0,
        lastrowid: Optional[int] = None,
    ) -> None:
        self._rows = list(rows or [])
        self.rowcount = int(rowcount or 0)
        self.lastrowid = lastrowid

    def fetchone(self):
        if not self._rows:
            return None
        return self._rows[0]

    def fetchall(self):
        return list(self._rows)


class _DbConn:
    def __init__(
        self,
        *,
        backend: str,
        raw_conn: Any,
        pg_row_factory: Any = None,
    ) -> None:
        self.backend = backend
        self._raw_conn = raw_conn
        self._pg_row_factory = pg_row_factory

    def execute(self, query: str, params: Sequence[object] = ()):
        if self.backend == "sqlite":
            return self._raw_conn.execute(query, tuple(params))
        query_pg = query.replace("%", "%%").replace("?", "%s")
        with self._raw_conn.cursor(row_factory=self._pg_row_factory) as cur:
            cur.execute(query_pg, tuple(params))
            rowcount = int(cur.rowcount or 0)
            if cur.description is None:
                return _PgResult([], rowcount=rowcount)
            rows = cur.fetchall()
            return _PgResult(rows, rowcount=rowcount)

    def commit(self) -> None:
        self._raw_conn.commit()

    def rollback(self) -> None:
        self._raw_conn.rollback()

    def close(self) -> None:
        self._raw_conn.close()

    @property
    def in_transaction(self) -> bool:
        if self.backend == "sqlite":
            return bool(getattr(self._raw_conn, "in_transaction", False))
        info = getattr(self._raw_conn, "info", None)
        status = getattr(info, "transaction_status", None)
        if status is None:
            return False
        status_name = str(getattr(status, "name", status)).upper()
        return status_name not in {"IDLE", "UNKNOWN"}


def _quote_ident(value: str) -> str:
    return '"' + str(value).replace('"', '""') + '"'


def _first_col(row: Any) -> Any:
    if row is None:
        return None
    if isinstance(row, Mapping):
        values = list(row.values())
        return values[0] if values else None
    try:
        return row[0]
    except Exception:
        return None


def _connect_sqlite(*, ensure_schema: bool = False) -> _DbConn:
    db_path = get_db_path()
    timeout_seconds = _sqlite_timeout_seconds()
    raw_conn = sqlite3.connect(db_path, timeout=timeout_seconds)
    raw_conn.row_factory = sqlite3.Row
    raw_conn.execute(f"PRAGMA busy_timeout = {int(timeout_seconds * 1000)}")
    conn = _DbConn(backend="sqlite", raw_conn=raw_conn)
    if ensure_schema:
        _ensure_table(conn, commit=True)
    return conn


def _connect_postgres(*, ensure_schema: bool = False) -> _DbConn:
    target, errors = resolve_postgres_target()
    if target is None:
        reasons = "; ".join(errors) if errors else "configuração ausente"
        raise RuntimeError(f"PostgreSQL não configurado: {reasons}")
    try:
        import psycopg
        from psycopg.rows import dict_row
    except Exception as exc:
        raise RuntimeError(
            "Driver psycopg não encontrado. Instale com: uv add psycopg[binary]"
        ) from exc

    schema = get_postgres_schema()
    raw_conn = psycopg.connect(target.dsn, row_factory=dict_row)
    with raw_conn.cursor() as cur:
        cur.execute(f"CREATE SCHEMA IF NOT EXISTS {_quote_ident(schema)}")
        cur.execute(f"SET search_path TO {_quote_ident(schema)}")
    conn = _DbConn(backend="postgres", raw_conn=raw_conn, pg_row_factory=dict_row)
    if ensure_schema:
        _ensure_table(conn, commit=True)
    return conn


def _get_conn(*, ensure_schema: bool = False) -> _DbConn:
    backend = get_data_backend()
    if backend == "postgres":
        try:
            return _connect_postgres(ensure_schema=ensure_schema)
        except Exception:
            return _connect_sqlite(ensure_schema=ensure_schema)
    return _connect_sqlite(ensure_schema=ensure_schema)


def _wrap_existing_conn(conn: Any) -> _DbConn:
    if isinstance(conn, _DbConn):
        return conn
    module_name = conn.__class__.__module__
    if module_name.startswith("sqlite3"):
        return _DbConn(backend="sqlite", raw_conn=conn)
    return _DbConn(backend="postgres", raw_conn=conn)


def _resolve_conn(
    conn: Optional[Any],
    *,
    ensure_schema: bool = False,
) -> tuple[_DbConn, bool]:
    if conn is None:
        return _get_conn(ensure_schema=ensure_schema), True
    db = _wrap_existing_conn(conn)
    if ensure_schema:
        _ensure_table(db, commit=not db.in_transaction)
    return db, False


def _ensure_table(conn: _DbConn, *, commit: bool) -> None:
    if conn.backend == "postgres":
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ledger (
                id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                date TEXT NOT NULL,
                type TEXT NOT NULL,
                amount DOUBLE PRECISION NOT NULL,
                description TEXT,
                position_id BIGINT
            )
            """
        )
    else:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ledger (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                type TEXT NOT NULL,
                amount REAL NOT NULL,
                description TEXT,
                position_id INTEGER
            )
            """
        )
    # Garantir colunas extras em versões antigas do banco
    if conn.backend == "postgres":
        existing = {
            str(row["column_name"])
            for row in conn.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND table_name = 'ledger'
                """
            ).fetchall()
        }
    else:
        existing = {
            row[1]
            for row in conn.execute('PRAGMA table_info("ledger")').fetchall()
            if row and len(row) > 1
        }
    if "is_simulated" not in existing:
        if conn.backend == "postgres":
            conn.execute('ALTER TABLE ledger ADD COLUMN IF NOT EXISTS "is_simulated" INTEGER DEFAULT 0')
        else:
            conn.execute('ALTER TABLE ledger ADD COLUMN "is_simulated" INTEGER DEFAULT 0')
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ledger_type_position_id ON ledger (type, position_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ledger_position_id ON ledger (position_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ledger_date ON ledger (date DESC)")
    if commit:
        conn.commit()


def _normalize_strategy_tag(value: Optional[str]) -> Optional[str]:
    text = (value or "").strip().lower()
    return text or None


def _table_exists(conn: _DbConn, table_name: str) -> bool:
    if conn.backend == "postgres":
        row = conn.execute("SELECT to_regclass(?)", (table_name,)).fetchone()
        return _first_col(row) is not None
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ? LIMIT 1",
        (table_name,),
    ).fetchone()
    return row is not None


def _has_positions_table(conn: _DbConn) -> bool:
    return _table_exists(conn, "positions")


def _has_ledger_table(conn: _DbConn) -> bool:
    return _table_exists(conn, "ledger")


def option_tax_rate(trade_type: str) -> float:
    """Retorna alíquota de IR para opções: 20% day trade, 15% swing."""
    return 0.20 if "day" in (trade_type or "").lower() else 0.15


def calculate_option_premium(*, entry_price: float, qty: int, fees: float = 0.0) -> float:
    """Calcula prêmio líquido de taxas para venda de opção."""
    return (float(entry_price) * int(qty)) - float(fees or 0.0)


def calculate_darf_provision(*, premium_amount: float, trade_type: str) -> float:
    """Calcula provisão de DARF (valor negativo), arredondada a centavos."""
    base_ir = max(0.0, float(premium_amount))
    if base_ir <= 0:
        return 0.0
    return -round(base_ir * option_tax_rate(trade_type), 2)


def add_transaction(
    date: str,
    type: TransactionType,
    amount: float,
    description: str = None,
    position_id: int = None,
    is_simulated: bool = False,
    conn: Optional[Any] = None,
) -> int:
    """Registra uma transação financeira."""
    db, owns_conn = _resolve_conn(conn, ensure_schema=True)
    try:
        type_value = type.value if isinstance(type, TransactionType) else str(type)
        params = (date, type_value, amount, description, position_id, 1 if is_simulated else 0)
        if db.backend == "postgres":
            row = db.execute(
                """
                INSERT INTO ledger (date, type, amount, description, position_id, is_simulated)
                VALUES (?, ?, ?, ?, ?, ?)
                RETURNING id
                """,
                params,
            ).fetchone()
            tx_id = _first_col(row)
        else:
            cur = db.execute(
                """
                INSERT INTO ledger (date, type, amount, description, position_id, is_simulated)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                params,
            )
            tx_id = getattr(cur, "lastrowid", None)
        if tx_id is None:
            raise RuntimeError("Falha ao obter id da transação inserida.")
        if owns_conn:
            db.commit()
        return int(tx_id)
    finally:
        if owns_conn:
            db.close()


def get_balance(mode: str = "all") -> float:
    """
    Retorna o saldo atual.
    mode: "all" (padrão), "real" (apenas não simuladas), "simulated" (apenas fictícias).
    """
    mode = (mode or "all").lower()
    conn = _get_conn()
    try:
        if not _has_ledger_table(conn):
            return 0.0
        where = ""
        params: list[object] = []
        if mode == "real":
            where = "WHERE is_simulated = 0"
        elif mode == "simulated":
            where = "WHERE is_simulated = 1"
        row = conn.execute(f"SELECT SUM(amount) as total FROM ledger {where}", params).fetchone()
        if not row:
            return 0.0
        if isinstance(row, Mapping):
            total = row.get("total")
        else:
            total = row[0]
        return float(total) if total is not None else 0.0
    finally:
        conn.close()


def get_monthly_premiums(
    limit_months: int = 12,
    *,
    is_simulated: Optional[bool] = False,
    include_darf: bool = False,
    include_buyback: bool = False,
    strategy_tag: Optional[str] = None,
) -> List[dict]:
    """Retorna soma de prêmios agrupados por mês (YYYY-MM).

    - is_simulated: False (padrão) -> somente real; True -> somente simulado; None -> ambos.
    - include_darf: soma também DARF (negativo) para exibir líquido fiscal (PREMIUM - DARF).
    - include_buyback: soma também recompras (`BUY`) vinculadas à opção
      (descrição iniciando em `Recompra opção`), para visão operacional de caixa.
    """
    conn = _get_conn()
    try:
        if not _has_ledger_table(conn):
            return []
        strategy = _normalize_strategy_tag(strategy_tag)
        where: list[str] = []
        params: list[object] = []
        use_strategy_filter = strategy is not None
        if use_strategy_filter and not _has_positions_table(conn):
            return []
        type_filters = ["l.type = ?"]
        params.append(TransactionType.PREMIUM.value)
        if include_darf:
            # DARF de provisão é lançado com position_id; evita misturar com DARF "pago" (manual).
            type_filters.append("(l.type = ? AND l.position_id IS NOT NULL)")
            params.append(TransactionType.DARF.value)
        if include_buyback:
            # Recompra registrada automaticamente no encerramento de opção vendida.
            type_filters.append(
                "(l.type = ? AND l.position_id IS NOT NULL AND COALESCE(l.description, '') LIKE 'Recompra opção %')"
            )
            params.append(TransactionType.BUY.value)
        where.append(f"({' OR '.join(type_filters)})")
        if is_simulated is not None:
            where.append("COALESCE(l.is_simulated, 0) = ?")
            params.append(1 if is_simulated else 0)
        if use_strategy_filter:
            where.append("l.position_id IS NOT NULL")
            where.append("COALESCE(LOWER(p.strategy_tag), '') = ?")
            params.append(strategy)
            from_clause = "FROM ledger l LEFT JOIN positions p ON p.id = l.position_id"
        else:
            from_clause = "FROM ledger l"

        query = f"""
            SELECT substr(l.date, 1, 7) AS month, SUM(l.amount) AS total
            {from_clause}
            WHERE {' AND '.join(where)}
            GROUP BY month
            ORDER BY month DESC
            LIMIT ?
        """
        rows = conn.execute(query, (*params, int(limit_months))).fetchall()
        # Inverte para ordem cronológica (gráfico)
        results = [{"month": r["month"], "total": r["total"]} for r in rows]
        return results[::-1]
    finally:
        conn.close()


def get_transactions(
    limit: int = 50,
    *,
    is_simulated: Optional[bool] = None,
    strategy_tag: Optional[str] = None,
    include_unlinked: bool = True,
) -> List[Transaction]:
    conn = _get_conn()
    try:
        if not _has_ledger_table(conn):
            return []
        where: list[str] = []
        params: list[object] = []
        strategy = _normalize_strategy_tag(strategy_tag)
        has_positions = _has_positions_table(conn)

        if is_simulated is not None:
            where.append("COALESCE(l.is_simulated, 0) = ?")
            params.append(1 if is_simulated else 0)

        if strategy:
            if has_positions:
                if include_unlinked:
                    where.append("(l.position_id IS NULL OR COALESCE(LOWER(p.strategy_tag), '') = ?)")
                else:
                    where.append("COALESCE(LOWER(p.strategy_tag), '') = ?")
                params.append(strategy)
            elif include_unlinked:
                where.append("l.position_id IS NULL")
            else:
                return []

        where_clause = f"WHERE {' AND '.join(where)}" if where else ""
        if has_positions:
            query = f"""
                SELECT l.*, p.strategy_tag AS position_strategy_tag
                FROM ledger l
                LEFT JOIN positions p ON p.id = l.position_id
                {where_clause}
                ORDER BY l.date DESC, l.id DESC
                LIMIT ?
            """
        else:
            query = f"""
                SELECT l.*
                FROM ledger l
                {where_clause}
                ORDER BY l.date DESC, l.id DESC
                LIMIT ?
            """
        rows = conn.execute(query, (*params, int(limit))).fetchall()
        return [
            Transaction(
                id=r["id"],
                date=r["date"],
                type=TransactionType(r["type"]),
                amount=r["amount"],
                description=r["description"],
                position_id=r["position_id"],
                is_simulated=bool(r["is_simulated"] or 0) if "is_simulated" in r.keys() else False,
                position_strategy_tag=(r["position_strategy_tag"] if "position_strategy_tag" in r.keys() else None),
            )
            for r in rows
        ]
    finally:
        conn.close()


def get_ledger_sums_by_position(
    *,
    types: Optional[List[TransactionType]] = None,
    is_simulated: Optional[bool] = None,
    conn: Optional[Any] = None,
) -> Dict[int, Dict[str, float]]:
    db, owns_conn = _resolve_conn(conn)
    try:
        if not _has_ledger_table(db):
            return {}
        where: list[str] = ["position_id IS NOT NULL"]
        params: list[object] = []
        if types:
            placeholders = ",".join("?" for _ in types)
            where.append(f"type IN ({placeholders})")
            params.extend([t.value if isinstance(t, TransactionType) else str(t) for t in types])
        if is_simulated is not None:
            where.append("COALESCE(is_simulated, 0) = ?")
            params.append(1 if is_simulated else 0)

        query = f"""
            SELECT position_id, type, SUM(amount) AS total
            FROM ledger
            WHERE {' AND '.join(where)}
            GROUP BY position_id, type
        """
        rows = db.execute(query, params).fetchall()
        result: Dict[int, Dict[str, float]] = {}
        for r in rows:
            pid = int(r["position_id"])
            if pid not in result:
                result[pid] = {}
            result[pid][str(r["type"])] = float(r["total"] or 0.0)
        return result
    finally:
        if owns_conn:
            db.close()


def recalc_position_premium_and_darf(
    *,
    position_id: int,
    trade_date: str,
    ticker: str,
    qty: int,
    premium_amount: float,
    trade_type: str,
    is_simulated: bool,
    conn: Optional[Any] = None,
) -> Dict[str, float]:
    """Recalcula (upsert) prêmio e DARF vinculados a uma posição."""
    db, owns_conn = _resolve_conn(conn, ensure_schema=True)
    try:
        cur = db.execute(
            """
            SELECT id, type
            FROM ledger
            WHERE position_id = ? AND type IN (?, ?)
            ORDER BY id ASC
            """,
            (int(position_id), TransactionType.PREMIUM.value, TransactionType.DARF.value),
        )
        rows = cur.fetchall()
        by_type: Dict[str, List[int]] = {TransactionType.PREMIUM.value: [], TransactionType.DARF.value: []}
        for r in rows:
            by_type[str(r["type"])].append(int(r["id"]))

        # PREMIUM
        if premium_amount > 0:
            if by_type[TransactionType.PREMIUM.value]:
                tx_id = by_type[TransactionType.PREMIUM.value][0]
                db.execute(
                    """
                    UPDATE ledger
                    SET date = ?, amount = ?, description = ?, is_simulated = ?
                    WHERE id = ?
                    """,
                    (
                        trade_date,
                        float(premium_amount),
                        f"Prêmio {ticker} ({int(qty)}x)",
                        1 if is_simulated else 0,
                        tx_id,
                    ),
                )
                extra_ids = by_type[TransactionType.PREMIUM.value][1:]
                if extra_ids:
                    db.execute(
                        f"DELETE FROM ledger WHERE id IN ({','.join('?' for _ in extra_ids)})",
                        extra_ids,
                    )
            else:
                add_transaction(
                    date=trade_date,
                    type=TransactionType.PREMIUM,
                    amount=float(premium_amount),
                    description=f"Prêmio {ticker} ({int(qty)}x)",
                    position_id=position_id,
                    is_simulated=is_simulated,
                    conn=db,
                )
        else:
            ids = by_type[TransactionType.PREMIUM.value]
            if ids:
                db.execute(
                    f"DELETE FROM ledger WHERE id IN ({','.join('?' for _ in ids)})",
                    ids,
                )

        # DARF
        aliquota_opts = option_tax_rate(trade_type)
        darf_amount = calculate_darf_provision(
            premium_amount=premium_amount,
            trade_type=trade_type,
        )

        if darf_amount != 0.0:
            if by_type[TransactionType.DARF.value]:
                tx_id = by_type[TransactionType.DARF.value][0]
                db.execute(
                    """
                    UPDATE ledger
                    SET date = ?, amount = ?, description = ?, is_simulated = ?
                    WHERE id = ?
                    """,
                    (
                        trade_date,
                        float(darf_amount),
                        f"Provisão DARF {ticker} ({int(aliquota_opts*100)}%)",
                        1 if is_simulated else 0,
                        tx_id,
                    ),
                )
                extra_ids = by_type[TransactionType.DARF.value][1:]
                if extra_ids:
                    db.execute(
                        f"DELETE FROM ledger WHERE id IN ({','.join('?' for _ in extra_ids)})",
                        extra_ids,
                    )
            else:
                add_transaction(
                    date=trade_date,
                    type=TransactionType.DARF,
                    amount=float(darf_amount),
                    description=f"Provisão DARF {ticker} ({int(aliquota_opts*100)}%)",
                    position_id=position_id,
                    is_simulated=is_simulated,
                    conn=db,
                )
        else:
            ids = by_type[TransactionType.DARF.value]
            if ids:
                db.execute(
                    f"DELETE FROM ledger WHERE id IN ({','.join('?' for _ in ids)})",
                    ids,
                )

        if owns_conn:
            db.commit()

        return {
            "premium": float(premium_amount),
            "darf": float(darf_amount),
        }
    finally:
        if owns_conn:
            db.close()


def sync_short_option_buyback(
    *,
    position_id: int,
    ticker: str,
    qty: int,
    partial_qty: Optional[int],
    status: Optional[str],
    exit_date: Optional[str],
    exit_price: Optional[float],
    is_simulated: bool,
    conn: Optional[Any] = None,
) -> float:
    """Sincroniza a recompra de encerramento (BUY) para opção vendida."""

    db, owns_conn = _resolve_conn(conn, ensure_schema=True)
    try:
        cur = db.execute(
            """
            SELECT id
            FROM ledger
            WHERE position_id = ?
              AND type = ?
              AND COALESCE(description, '') LIKE 'Recompra opção %'
            ORDER BY id ASC
            """,
            (int(position_id), TransactionType.BUY.value),
        )
        existing_ids = [int(r["id"]) for r in cur.fetchall()]

        is_closed = (status or "").strip().lower() == "closed"
        close_qty = max(int(qty or 0) - int(partial_qty or 0), 0)
        close_date = (exit_date or "").strip()
        close_price = float(exit_price or 0.0)
        should_have = is_closed and bool(close_date) and close_qty > 0 and close_price > 0.0

        if not should_have:
            if existing_ids:
                db.execute(
                    f"DELETE FROM ledger WHERE id IN ({','.join('?' for _ in existing_ids)})",
                    existing_ids,
                )
            if owns_conn:
                db.commit()
            return 0.0

        amount = -round(close_price * close_qty, 2)
        description = f"Recompra opção {ticker} ({close_qty}x)"

        if existing_ids:
            db.execute(
                """
                UPDATE ledger
                SET date = ?, amount = ?, description = ?, is_simulated = ?
                WHERE id = ?
                """,
                (
                    close_date,
                    amount,
                    description,
                    1 if is_simulated else 0,
                    existing_ids[0],
                ),
            )
            extra_ids = existing_ids[1:]
            if extra_ids:
                db.execute(
                    f"DELETE FROM ledger WHERE id IN ({','.join('?' for _ in extra_ids)})",
                    extra_ids,
                )
        else:
            add_transaction(
                date=close_date,
                type=TransactionType.BUY,
                amount=amount,
                description=description,
                position_id=position_id,
                is_simulated=is_simulated,
                conn=db,
            )

        if owns_conn:
            db.commit()
        return amount
    finally:
        if owns_conn:
            db.close()


def get_premium_position_ids(position_ids: Optional[List[int]] = None) -> set[int]:
    if position_ids is not None and not position_ids:
        return set()
    conn = _get_conn()
    try:
        if not _has_ledger_table(conn):
            return set()
        params: list[object] = [TransactionType.PREMIUM.value]
        query = "SELECT DISTINCT position_id FROM ledger WHERE type = ? AND position_id IS NOT NULL"
        if position_ids:
            placeholders = ",".join("?" for _ in position_ids)
            query += f" AND position_id IN ({placeholders})"
            params.extend([int(pid) for pid in position_ids])
        rows = conn.execute(query, params).fetchall()
        return {int(r["position_id"]) for r in rows if r["position_id"] is not None}
    finally:
        conn.close()


def has_position_premium(position_id: int) -> bool:
    conn = _get_conn()
    try:
        if not _has_ledger_table(conn):
            return False
        row = conn.execute(
            "SELECT 1 FROM ledger WHERE type = ? AND position_id = ? LIMIT 1",
            (TransactionType.PREMIUM.value, int(position_id)),
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def update_transaction(
    tx_id: int,
    *,
    date: Optional[str] = None,
    type: Optional[TransactionType] = None,
    amount: Optional[float] = None,
    description: Optional[str] = None,
    is_simulated: Optional[bool] = None,
) -> None:
    """Atualiza campos básicos de uma transação existente."""
    fields = []
    params: list[object] = []
    if date is not None:
        fields.append("date = ?")
        params.append(date)
    if type is not None:
        if isinstance(type, TransactionType):
            type_val = type.value
        else:
            type_val = str(type)
        fields.append("type = ?")
        params.append(type_val)
    if amount is not None:
        fields.append("amount = ?")
        params.append(float(amount))
    if description is not None:
        fields.append("description = ?")
        params.append(description)
    if is_simulated is not None:
        fields.append("is_simulated = ?")
        params.append(1 if is_simulated else 0)
    if not fields:
        return

    params.append(int(tx_id))
    conn = _get_conn(ensure_schema=True)
    try:
        cur = conn.execute(
            f"UPDATE ledger SET {', '.join(fields)} WHERE id = ?",
            params,
        )
        conn.commit()
        if cur.rowcount == 0:
            raise ValueError(f"Transação {tx_id} não encontrada.")
    finally:
        conn.close()


def delete_transaction(tx_id: int) -> None:
    """Remove uma transação do ledger."""
    conn = _get_conn(ensure_schema=True)
    try:
        conn.execute("DELETE FROM ledger WHERE id = ?", (int(tx_id),))
        conn.commit()
    finally:
        conn.close()
