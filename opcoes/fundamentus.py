from __future__ import annotations

import datetime as dt
import http.cookiejar
import re
import unicodedata
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence
from urllib import parse, request

from .config import (
    get_postgres_shared_schema,
)
from .db_health import resolve_postgres_target
from .utils import parse_ptbr_number

SEARCH_URL = "https://www.fundamentus.com.br/buscaavancada.php"
RESULT_URL = "https://www.fundamentus.com.br/resultado.php"

RESULT_FIELDS = [
    "papel",
    "cotacao",
    "pl",
    "pvp",
    "psr",
    "div_yield",
    "p_ativo",
    "p_cap_giro",
    "p_ebit",
    "p_ativo_circ_liq",
    "ev_ebit",
    "ev_ebitda",
    "margem_ebit",
    "margem_liquida",
    "liquidez_corrente",
    "roic",
    "roe",
    "liquidez_2m",
    "patrimonio_liq",
    "div_bruta_patrim",
    "cresc_rec_5a",
]

NUMERIC_FIELDS = [f for f in RESULT_FIELDS if f != "papel"]


class FundamentusSchemaError(RuntimeError):
    """Indica que a estrutura publicada pelo Fundamentus mudou."""


# O Fundamentus pode inserir indicadores no meio da tabela. O contrato da
# aplicação é o nome da coluna, nunca sua posição no HTML.
_HEADER_FIELDS = {
    "papel": "papel",
    "cotacao": "cotacao",
    "pl": "pl",
    "pvp": "pvp",
    "psr": "psr",
    "divyield": "div_yield",
    "pativo": "p_ativo",
    "pcapgiro": "p_cap_giro",
    "pebit": "p_ebit",
    "pativcircliq": "p_ativo_circ_liq",
    "evebit": "ev_ebit",
    "evebitda": "ev_ebitda",
    "mrgbruta": "margem_bruta",
    "mrgebit": "margem_ebit",
    "mrgliq": "margem_liquida",
    "liqcorr": "liquidez_corrente",
    "roic": "roic",
    "roe": "roe",
    "liq2meses": "liquidez_2m",
    "patrimliq": "patrimonio_liq",
    "divbrutpatrim": "div_bruta_patrim",
    "divliqpatrim": "div_bruta_patrim",
    "crescrec5a": "cresc_rec_5a",
}

SNAPSHOT_STATUS_VALID = "valid"
SNAPSHOT_STATUS_QUARANTINED = "quarantined"


def _normalize_header(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def _resolve_result_headers(headers: Sequence[str]) -> Dict[str, int]:
    if not headers:
        raise FundamentusSchemaError("A tabela de resultado nao trouxe cabecalhos.")

    positions: Dict[str, int] = {}
    unknown_headers: List[str] = []
    duplicate_fields: List[str] = []
    for index, header in enumerate(headers):
        field = _HEADER_FIELDS.get(_normalize_header(header))
        if field is None:
            unknown_headers.append(header)
            continue
        if field in positions:
            duplicate_fields.append(header)
            continue
        positions[field] = index

    missing_fields = [field for field in RESULT_FIELDS if field not in positions]
    if unknown_headers or duplicate_fields or missing_fields:
        details: List[str] = []
        if unknown_headers:
            details.append("cabecalho desconhecido: " + ", ".join(unknown_headers))
        if duplicate_fields:
            details.append("cabecalho duplicado: " + ", ".join(duplicate_fields))
        if missing_fields:
            details.append("campos obrigatorios ausentes: " + ", ".join(missing_fields))
        raise FundamentusSchemaError("; ".join(details))
    return positions


@dataclass(frozen=True)
class FundamentusFilterConfig:
    liq_2m_min: float = 1_000_000.0
    div_bruta_patrim_max: float = 2.0
    cresc_rec_5a_min: float = 0.0
    div_yield_min: float = 6.0
    roe_min: float = 15.0
    margem_liquida_min: float = 10.0
    margem_liquida_allow_zero: bool = True


class _FundamentusTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._in_table = False
        self._in_thead = False
        self._in_tbody = False
        self._in_row = False
        self._in_cell = False
        self._cell_parts: List[str] = []
        self.headers: List[str] = []
        self.rows: List[List[str]] = []
        self._current_row: List[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        if tag == "table":
            for key, value in attrs:
                if key == "id" and value == "resultado":
                    self._in_table = True
                    break
        if not self._in_table:
            return
        if tag == "thead":
            self._in_thead = True
        elif tag == "tbody":
            self._in_tbody = True
        elif tag == "tr":
            self._in_row = True
            self._current_row = []
        elif tag in ("th", "td"):
            self._in_cell = True
            self._cell_parts = []

    def handle_endtag(self, tag: str) -> None:
        if not self._in_table:
            return
        if self._in_cell and tag in ("th", "td"):
            text = " ".join("".join(self._cell_parts).split())
            if self._in_thead and tag == "th":
                self.headers.append(text)
            elif self._in_tbody and tag == "td":
                self._current_row.append(text)
            self._in_cell = False
        elif tag == "tr":
            if self._in_tbody and self._current_row:
                self.rows.append(self._current_row)
            self._in_row = False
        elif tag == "thead":
            self._in_thead = False
        elif tag == "tbody":
            self._in_tbody = False
        elif tag == "table":
            self._in_table = False

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._cell_parts.append(data)


def parse_result_table(html: str) -> List[Dict[str, str]]:
    parser = _FundamentusTableParser()
    parser.feed(html)
    positions = _resolve_result_headers(parser.headers)
    results: List[Dict[str, str]] = []
    for row_number, row in enumerate(parser.rows, start=1):
        if len(row) != len(parser.headers):
            raise FundamentusSchemaError(
                "Linha "
                f"{row_number} trouxe {len(row)} colunas; esperado {len(parser.headers)}."
            )
        payload = {field: row[positions[field]] for field in RESULT_FIELDS}
        results.append(payload)
    return results


def normalize_rows(rows: Sequence[Dict[str, str]]) -> List[Dict[str, object]]:
    normalized: List[Dict[str, object]] = []
    for row in rows:
        papel = (row.get("papel") or "").strip().upper()
        if not papel:
            continue
        entry: Dict[str, object] = {"papel": papel}
        for field in NUMERIC_FIELDS:
            entry[field] = parse_ptbr_number(row.get(field))
        normalized.append(entry)
    return normalized


def evaluate_row(
    row: Dict[str, object], cfg: FundamentusFilterConfig
) -> Dict[str, object]:
    papel = (row.get("papel") or "").strip().upper()

    def reject(
        step: int, rule: str, value: Optional[float], reason: str
    ) -> Dict[str, object]:
        return {
            "papel": papel,
            "status": "rejected",
            "failed_step": step,
            "failed_rule": rule,
            "failed_value": value,
            "reason": reason,
        }

    liq_2m = row.get("liquidez_2m")
    if liq_2m is None:
        return reject(1, "liq_2m_min", None, "missing_liquidez_2m")
    if liq_2m < cfg.liq_2m_min:
        return reject(1, "liq_2m_min", float(liq_2m), "liquidez_2m_below_min")

    div_bruta = row.get("div_bruta_patrim")
    if div_bruta is None:
        return reject(2, "div_bruta_patrim_max", None, "missing_div_bruta_patrim")
    if div_bruta > cfg.div_bruta_patrim_max:
        return reject(
            2, "div_bruta_patrim_max", float(div_bruta), "div_bruta_patrim_above_max"
        )

    cresc_rec = row.get("cresc_rec_5a")
    if cresc_rec is None:
        return reject(3, "cresc_rec_5a_min", None, "missing_cresc_rec_5a")
    if cresc_rec < cfg.cresc_rec_5a_min:
        return reject(3, "cresc_rec_5a_min", float(cresc_rec), "cresc_rec_5a_below_min")

    div_yield = row.get("div_yield")
    if div_yield is None:
        return reject(4, "div_yield_min", None, "missing_div_yield")
    if div_yield < cfg.div_yield_min:
        return reject(4, "div_yield_min", float(div_yield), "div_yield_below_min")

    roe = row.get("roe")
    if roe is None:
        return reject(5, "roe_min", None, "missing_roe")
    if roe < cfg.roe_min:
        return reject(5, "roe_min", float(roe), "roe_below_min")

    margem = row.get("margem_liquida")
    if margem is None:
        return reject(6, "margem_liquida_rule", None, "missing_margem_liquida")
    if not (
        margem >= cfg.margem_liquida_min
        or (cfg.margem_liquida_allow_zero and margem == 0)
    ):
        return reject(
            6, "margem_liquida_rule", float(margem), "margem_liquida_out_of_rule"
        )

    return {
        "papel": papel,
        "status": "approved",
        "failed_step": None,
        "failed_rule": None,
        "failed_value": None,
        "reason": "approved",
    }


def evaluate_rows(
    rows: Sequence[Dict[str, object]], cfg: Optional[FundamentusFilterConfig] = None
) -> List[Dict[str, object]]:
    cfg = cfg or FundamentusFilterConfig()
    results: List[Dict[str, object]] = []
    for row in rows:
        papel = (row.get("papel") or "").strip()
        if not papel:
            continue
        results.append(evaluate_row(row, cfg))
    return results


def fetch_fundamentus_results(
    *,
    pl_min: float = 0.0,
    patrim_min: float = 0.0,
    timeout: float = 30.0,
) -> List[Dict[str, str]]:
    params = {
        "pl_min": f"{pl_min:.2f}".rstrip("0").rstrip("."),
        "patrim_min": f"{patrim_min:.2f}".rstrip("0").rstrip("."),
        "negociada": "ON",
        "ordem": "1",
    }
    payload = parse.urlencode(params).encode("ascii")

    jar = http.cookiejar.CookieJar()
    opener = request.build_opener(request.HTTPCookieProcessor(jar))
    opener.addheaders = [
        (
            "User-Agent",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
        ),
        ("Referer", SEARCH_URL),
    ]

    opener.open(SEARCH_URL, timeout=timeout)
    req = request.Request(
        RESULT_URL,
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with opener.open(req, timeout=timeout) as resp:
        html = resp.read().decode("iso-8859-1", errors="replace")
    return parse_result_table(html)


class _PgResult:
    def __init__(
        self, rows: Optional[list[Mapping[str, Any]]] = None, *, rowcount: int = 0
    ) -> None:
        self._rows = list(rows or [])
        self.rowcount = int(rowcount or 0)
        self.lastrowid = None

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
        query_pg = query.replace("%", "%%").replace("?", "%s")
        with self._raw_conn.cursor(row_factory=self._pg_row_factory) as cur:
            cur.execute(query_pg, tuple(params))
            rowcount = int(cur.rowcount or 0)
            if cur.description is None:
                return _PgResult([], rowcount=rowcount)
            rows = cur.fetchall()
            return _PgResult(rows, rowcount=rowcount)

    def executemany(self, query: str, params_seq: Sequence[Sequence[object]]) -> None:
        query_pg = query.replace("%", "%%").replace("?", "%s")
        with self._raw_conn.cursor() as cur:
            cur.executemany(query_pg, params_seq)

    def commit(self) -> None:
        self._raw_conn.commit()

    def close(self) -> None:
        self._raw_conn.close()

    def rollback(self) -> None:
        self._raw_conn.rollback()


def _quote_ident(value: str) -> str:
    return '"' + str(value).replace('"', '""') + '"'


def _connect_postgres() -> _DbConn:
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

    schema = get_postgres_shared_schema()
    raw_conn = psycopg.connect(target.dsn, row_factory=dict_row)
    with raw_conn.cursor() as cur:
        cur.execute(f"CREATE SCHEMA IF NOT EXISTS {_quote_ident(schema)}")
        cur.execute(f"SET search_path TO {_quote_ident(schema)}")
    conn = _DbConn(backend="postgres", raw_conn=raw_conn, pg_row_factory=dict_row)
    _ensure_tables(conn)
    return conn


def _connect(db_path: Optional[Path] = None) -> _DbConn:
    if db_path is not None:
        raise RuntimeError("Parâmetro db_path não é suportado no backend PostgreSQL.")
    return _connect_postgres()


def _ensure_tables(conn: _DbConn) -> None:
    if conn.backend == "postgres":
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS fundamentus_snapshots (
                snapshot_date TEXT NOT NULL,
                papel TEXT NOT NULL,
                cotacao DOUBLE PRECISION,
                pl DOUBLE PRECISION,
                pvp DOUBLE PRECISION,
                psr DOUBLE PRECISION,
                div_yield DOUBLE PRECISION,
                p_ativo DOUBLE PRECISION,
                p_cap_giro DOUBLE PRECISION,
                p_ebit DOUBLE PRECISION,
                p_ativo_circ_liq DOUBLE PRECISION,
                ev_ebit DOUBLE PRECISION,
                ev_ebitda DOUBLE PRECISION,
                margem_ebit DOUBLE PRECISION,
                margem_liquida DOUBLE PRECISION,
                liquidez_corrente DOUBLE PRECISION,
                roic DOUBLE PRECISION,
                roe DOUBLE PRECISION,
                liquidez_2m DOUBLE PRECISION,
                patrimonio_liq DOUBLE PRECISION,
                div_bruta_patrim DOUBLE PRECISION,
                cresc_rec_5a DOUBLE PRECISION,
                PRIMARY KEY (snapshot_date, papel)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS fundamentus_runs (
                snapshot_date TEXT PRIMARY KEY,
                pl_min DOUBLE PRECISION,
                patrim_min DOUBLE PRECISION,
                negociada INTEGER,
                source_url TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS fundamentus_signals (
                snapshot_date TEXT NOT NULL,
                papel TEXT NOT NULL,
                status TEXT NOT NULL,
                failed_step INTEGER,
                failed_rule TEXT,
                failed_value DOUBLE PRECISION,
                reason TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (snapshot_date, papel)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS fundamentus_filter_runs (
                snapshot_date TEXT PRIMARY KEY,
                liq_2m_min DOUBLE PRECISION,
                div_bruta_patrim_max DOUBLE PRECISION,
                cresc_rec_5a_min DOUBLE PRECISION,
                div_yield_min DOUBLE PRECISION,
                roe_min DOUBLE PRECISION,
                margem_liquida_min DOUBLE PRECISION,
                margem_liquida_allow_zero INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS fundamentus_snapshot_integrity (
                snapshot_date TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                reason TEXT,
                assessed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
    else:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS fundamentus_snapshots (
                snapshot_date TEXT NOT NULL,
                papel TEXT NOT NULL,
                cotacao REAL,
                pl REAL,
                pvp REAL,
                psr REAL,
                div_yield REAL,
                p_ativo REAL,
                p_cap_giro REAL,
                p_ebit REAL,
                p_ativo_circ_liq REAL,
                ev_ebit REAL,
                ev_ebitda REAL,
                margem_ebit REAL,
                margem_liquida REAL,
                liquidez_corrente REAL,
                roic REAL,
                roe REAL,
                liquidez_2m REAL,
                patrimonio_liq REAL,
                div_bruta_patrim REAL,
                cresc_rec_5a REAL,
                PRIMARY KEY (snapshot_date, papel)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS fundamentus_runs (
                snapshot_date TEXT PRIMARY KEY,
                pl_min REAL,
                patrim_min REAL,
                negociada INTEGER,
                source_url TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS fundamentus_signals (
                snapshot_date TEXT NOT NULL,
                papel TEXT NOT NULL,
                status TEXT NOT NULL,
                failed_step INTEGER,
                failed_rule TEXT,
                failed_value REAL,
                reason TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (snapshot_date, papel)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS fundamentus_filter_runs (
                snapshot_date TEXT PRIMARY KEY,
                liq_2m_min REAL,
                div_bruta_patrim_max REAL,
                cresc_rec_5a_min REAL,
                div_yield_min REAL,
                roe_min REAL,
                margem_liquida_min REAL,
                margem_liquida_allow_zero INTEGER,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS fundamentus_snapshot_integrity (
                snapshot_date TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                reason TEXT,
                assessed_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
    conn.commit()


def _snapshot_is_visible_sql(table_alias: str) -> str:
    return (
        "NOT EXISTS ("
        "SELECT 1 FROM fundamentus_snapshot_integrity integrity "
        f"WHERE integrity.snapshot_date = {table_alias}.snapshot_date "
        f"AND integrity.status = '{SNAPSHOT_STATUS_QUARANTINED}'"
        ")"
    )


def _set_snapshot_integrity(
    conn: _DbConn,
    *,
    snapshot_date: str,
    status: str,
    reason: Optional[str],
) -> None:
    if status not in {SNAPSHOT_STATUS_VALID, SNAPSHOT_STATUS_QUARANTINED}:
        raise ValueError(f"Status de integridade invalido: {status}")
    if conn.backend == "postgres":
        conn.execute(
            """
            INSERT INTO fundamentus_snapshot_integrity (snapshot_date, status, reason)
            VALUES (?, ?, ?)
            ON CONFLICT (snapshot_date) DO UPDATE SET
                status = EXCLUDED.status,
                reason = EXCLUDED.reason,
                assessed_at = CURRENT_TIMESTAMP
            """,
            (snapshot_date, status, reason),
        )
    else:
        conn.execute(
            """
            INSERT OR REPLACE INTO fundamentus_snapshot_integrity
            (snapshot_date, status, reason)
            VALUES (?, ?, ?)
            """,
            (snapshot_date, status, reason),
        )


def save_snapshot(
    rows: Sequence[Dict[str, str]],
    *,
    snapshot_date: Optional[str] = None,
    pl_min: float = 0.0,
    patrim_min: float = 0.0,
    negociada: bool = True,
    db_path: Optional[Path] = None,
) -> int:
    snapshot_date = snapshot_date or dt.date.today().isoformat()
    normalized = normalize_rows(rows)
    payload = [
        (
            snapshot_date,
            row.get("papel"),
            row.get("cotacao"),
            row.get("pl"),
            row.get("pvp"),
            row.get("psr"),
            row.get("div_yield"),
            row.get("p_ativo"),
            row.get("p_cap_giro"),
            row.get("p_ebit"),
            row.get("p_ativo_circ_liq"),
            row.get("ev_ebit"),
            row.get("ev_ebitda"),
            row.get("margem_ebit"),
            row.get("margem_liquida"),
            row.get("liquidez_corrente"),
            row.get("roic"),
            row.get("roe"),
            row.get("liquidez_2m"),
            row.get("patrimonio_liq"),
            row.get("div_bruta_patrim"),
            row.get("cresc_rec_5a"),
        )
        for row in normalized
    ]

    conn = _connect(db_path)
    try:
        if conn.backend == "postgres":
            conn.execute(
                """
                INSERT INTO fundamentus_runs
                (snapshot_date, pl_min, patrim_min, negociada, source_url)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT (snapshot_date) DO UPDATE SET
                    pl_min = EXCLUDED.pl_min,
                    patrim_min = EXCLUDED.patrim_min,
                    negociada = EXCLUDED.negociada,
                    source_url = EXCLUDED.source_url,
                    created_at = CURRENT_TIMESTAMP
                """,
                (
                    snapshot_date,
                    float(pl_min),
                    float(patrim_min),
                    1 if negociada else 0,
                    RESULT_URL,
                ),
            )
        else:
            conn.execute(
                """
                INSERT OR REPLACE INTO fundamentus_runs
                (snapshot_date, pl_min, patrim_min, negociada, source_url)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    snapshot_date,
                    float(pl_min),
                    float(patrim_min),
                    1 if negociada else 0,
                    RESULT_URL,
                ),
            )
        if payload:
            if conn.backend == "postgres":
                conn.executemany(
                    """
                    INSERT INTO fundamentus_snapshots (
                        snapshot_date, papel, cotacao, pl, pvp, psr, div_yield, p_ativo, p_cap_giro,
                        p_ebit, p_ativo_circ_liq, ev_ebit, ev_ebitda, margem_ebit, margem_liquida,
                        liquidez_corrente, roic, roe, liquidez_2m, patrimonio_liq, div_bruta_patrim,
                        cresc_rec_5a
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT (snapshot_date, papel) DO UPDATE SET
                        cotacao = EXCLUDED.cotacao,
                        pl = EXCLUDED.pl,
                        pvp = EXCLUDED.pvp,
                        psr = EXCLUDED.psr,
                        div_yield = EXCLUDED.div_yield,
                        p_ativo = EXCLUDED.p_ativo,
                        p_cap_giro = EXCLUDED.p_cap_giro,
                        p_ebit = EXCLUDED.p_ebit,
                        p_ativo_circ_liq = EXCLUDED.p_ativo_circ_liq,
                        ev_ebit = EXCLUDED.ev_ebit,
                        ev_ebitda = EXCLUDED.ev_ebitda,
                        margem_ebit = EXCLUDED.margem_ebit,
                        margem_liquida = EXCLUDED.margem_liquida,
                        liquidez_corrente = EXCLUDED.liquidez_corrente,
                        roic = EXCLUDED.roic,
                        roe = EXCLUDED.roe,
                        liquidez_2m = EXCLUDED.liquidez_2m,
                        patrimonio_liq = EXCLUDED.patrimonio_liq,
                        div_bruta_patrim = EXCLUDED.div_bruta_patrim,
                        cresc_rec_5a = EXCLUDED.cresc_rec_5a
                    """,
                    payload,
                )
            else:
                conn.executemany(
                    """
                    INSERT OR REPLACE INTO fundamentus_snapshots (
                        snapshot_date, papel, cotacao, pl, pvp, psr, div_yield, p_ativo, p_cap_giro,
                        p_ebit, p_ativo_circ_liq, ev_ebit, ev_ebitda, margem_ebit, margem_liquida,
                        liquidez_corrente, roic, roe, liquidez_2m, patrimonio_liq, div_bruta_patrim,
                        cresc_rec_5a
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    payload,
                )
        if payload:
            _set_snapshot_integrity(
                conn,
                snapshot_date=snapshot_date,
                status=SNAPSHOT_STATUS_VALID,
                reason=None,
            )
        conn.commit()
    finally:
        conn.close()
    return len(payload)


def save_signals(
    signals: Sequence[Dict[str, object]],
    *,
    snapshot_date: str,
    cfg: Optional[FundamentusFilterConfig] = None,
    db_path: Optional[Path] = None,
) -> int:
    cfg = cfg or FundamentusFilterConfig()
    payload = [
        (
            snapshot_date,
            s.get("papel"),
            s.get("status"),
            s.get("failed_step"),
            s.get("failed_rule"),
            s.get("failed_value"),
            s.get("reason"),
        )
        for s in signals
        if s.get("papel")
    ]
    conn = _connect(db_path)
    try:
        if conn.backend == "postgres":
            conn.execute(
                """
                INSERT INTO fundamentus_filter_runs (
                    snapshot_date, liq_2m_min, div_bruta_patrim_max, cresc_rec_5a_min, div_yield_min,
                    roe_min, margem_liquida_min, margem_liquida_allow_zero
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (snapshot_date) DO UPDATE SET
                    liq_2m_min = EXCLUDED.liq_2m_min,
                    div_bruta_patrim_max = EXCLUDED.div_bruta_patrim_max,
                    cresc_rec_5a_min = EXCLUDED.cresc_rec_5a_min,
                    div_yield_min = EXCLUDED.div_yield_min,
                    roe_min = EXCLUDED.roe_min,
                    margem_liquida_min = EXCLUDED.margem_liquida_min,
                    margem_liquida_allow_zero = EXCLUDED.margem_liquida_allow_zero,
                    created_at = CURRENT_TIMESTAMP
                """,
                (
                    snapshot_date,
                    float(cfg.liq_2m_min),
                    float(cfg.div_bruta_patrim_max),
                    float(cfg.cresc_rec_5a_min),
                    float(cfg.div_yield_min),
                    float(cfg.roe_min),
                    float(cfg.margem_liquida_min),
                    1 if cfg.margem_liquida_allow_zero else 0,
                ),
            )
        else:
            conn.execute(
                """
                INSERT OR REPLACE INTO fundamentus_filter_runs (
                    snapshot_date, liq_2m_min, div_bruta_patrim_max, cresc_rec_5a_min, div_yield_min,
                    roe_min, margem_liquida_min, margem_liquida_allow_zero
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot_date,
                    float(cfg.liq_2m_min),
                    float(cfg.div_bruta_patrim_max),
                    float(cfg.cresc_rec_5a_min),
                    float(cfg.div_yield_min),
                    float(cfg.roe_min),
                    float(cfg.margem_liquida_min),
                    1 if cfg.margem_liquida_allow_zero else 0,
                ),
            )
        if payload:
            if conn.backend == "postgres":
                conn.executemany(
                    """
                    INSERT INTO fundamentus_signals (
                        snapshot_date, papel, status, failed_step, failed_rule, failed_value, reason
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT (snapshot_date, papel) DO UPDATE SET
                        status = EXCLUDED.status,
                        failed_step = EXCLUDED.failed_step,
                        failed_rule = EXCLUDED.failed_rule,
                        failed_value = EXCLUDED.failed_value,
                        reason = EXCLUDED.reason,
                        created_at = CURRENT_TIMESTAMP
                    """,
                    payload,
                )
            else:
                conn.executemany(
                    """
                    INSERT OR REPLACE INTO fundamentus_signals (
                        snapshot_date, papel, status, failed_step, failed_rule, failed_value, reason
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    payload,
                )
        conn.commit()
    finally:
        conn.close()
    return len(payload)


def quarantine_snapshots(
    *,
    start_date: str,
    end_date: str,
    reason: str,
    db_path: Optional[Path] = None,
) -> int:
    """Preserva snapshots inválidos para auditoria, sem deixá-los alimentar a estratégia."""

    start = dt.date.fromisoformat(start_date).isoformat()
    end = dt.date.fromisoformat(end_date).isoformat()
    if start > end:
        raise ValueError("A data inicial deve ser menor ou igual à data final.")
    normalized_reason = (reason or "").strip()
    if not normalized_reason:
        raise ValueError("Informe o motivo da quarentena.")

    conn = _connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT DISTINCT snapshot_date
            FROM fundamentus_snapshots
            WHERE snapshot_date BETWEEN ? AND ?
            ORDER BY snapshot_date
            """,
            (start, end),
        ).fetchall()
        for row in rows:
            _set_snapshot_integrity(
                conn,
                snapshot_date=str(row["snapshot_date"]),
                status=SNAPSHOT_STATUS_QUARANTINED,
                reason=normalized_reason,
            )
        conn.commit()
        return len(rows)
    finally:
        conn.close()


def list_quarantined_snapshots(
    *,
    db_path: Optional[Path] = None,
) -> List[Dict[str, object]]:
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT snapshot_date, status, reason, assessed_at
            FROM fundamentus_snapshot_integrity
            WHERE status = ?
            ORDER BY snapshot_date
            """,
            (SNAPSHOT_STATUS_QUARANTINED,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_snapshot_integrity(
    *,
    snapshot_date: str,
    db_path: Optional[Path] = None,
) -> Optional[Dict[str, object]]:
    conn = _connect(db_path)
    try:
        row = conn.execute(
            """
            SELECT snapshot_date, status, reason, assessed_at
            FROM fundamentus_snapshot_integrity
            WHERE snapshot_date = ?
            """,
            (snapshot_date,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def scrape_and_store(
    *,
    pl_min: float = 0.0,
    patrim_min: float = 0.0,
    timeout: float = 30.0,
    snapshot_date: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> int:
    rows = fetch_fundamentus_results(
        pl_min=pl_min, patrim_min=patrim_min, timeout=timeout
    )
    if not rows:
        raise FundamentusSchemaError("A fonte retornou uma tabela vazia.")
    return save_snapshot(
        rows,
        snapshot_date=snapshot_date,
        pl_min=pl_min,
        patrim_min=patrim_min,
        negociada=True,
        db_path=db_path,
    )


def apply_filters(
    *,
    snapshot_date: Optional[str] = None,
    cfg: Optional[FundamentusFilterConfig] = None,
    db_path: Optional[Path] = None,
) -> Dict[str, int]:
    cfg = cfg or FundamentusFilterConfig()
    snap = snapshot_date or latest_snapshot_date(db_path=db_path)
    if not snap:
        return {"total": 0, "approved": 0, "rejected": 0}
    rows = fetch_snapshot(snapshot_date=snap, db_path=db_path)
    if not rows:
        return {"total": 0, "approved": 0, "rejected": 0}
    signals = evaluate_rows(rows, cfg)
    save_signals(signals, snapshot_date=snap, cfg=cfg, db_path=db_path)
    approved = sum(1 for s in signals if s.get("status") == "approved")
    rejected = sum(1 for s in signals if s.get("status") == "rejected")
    return {"total": len(signals), "approved": approved, "rejected": rejected}


def latest_snapshot_date(db_path: Optional[Path] = None) -> Optional[str]:
    conn = _connect(db_path)
    try:
        row = conn.execute(
            f"""
            SELECT MAX(snapshot_date) AS d
            FROM fundamentus_snapshots snapshot
            WHERE {_snapshot_is_visible_sql('snapshot')}
            """
        ).fetchone()
        return row["d"] if row else None
    finally:
        conn.close()


def fetch_snapshot(
    *,
    snapshot_date: Optional[str] = None,
    limit: Optional[int] = None,
    db_path: Optional[Path] = None,
) -> List[Dict[str, object]]:
    conn = _connect(db_path)
    try:
        snap = snapshot_date or latest_snapshot_date(db_path=db_path)
        if not snap:
            return []
        query = (
            "SELECT * FROM fundamentus_snapshots snapshot "
            f"WHERE snapshot.snapshot_date = ? AND {_snapshot_is_visible_sql('snapshot')}"
        )
        params: list[object] = [snap]
        if limit:
            query += " LIMIT ?"
            params.append(int(limit))
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def fetch_signals(
    *,
    snapshot_date: Optional[str] = None,
    status: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> List[Dict[str, object]]:
    conn = _connect(db_path)
    try:
        snap = snapshot_date or latest_snapshot_date(db_path=db_path)
        if not snap:
            return []
        query = (
            "SELECT * FROM fundamentus_signals signal "
            f"WHERE signal.snapshot_date = ? AND {_snapshot_is_visible_sql('signal')}"
        )
        params: list[object] = [snap]
        if status:
            query += " AND status = ?"
            params.append(status)
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def fetch_filter_run(
    *,
    snapshot_date: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> Optional[Dict[str, object]]:
    conn = _connect(db_path)
    try:
        snap = snapshot_date or latest_snapshot_date(db_path=db_path)
        if not snap:
            return None
        row = conn.execute(
            """
            SELECT *
            FROM fundamentus_filter_runs filter_run
            WHERE filter_run.snapshot_date <= ?
              AND {visible_sql}
            ORDER BY filter_run.snapshot_date DESC
            LIMIT 1
            """.format(
                visible_sql=_snapshot_is_visible_sql("filter_run")
            ),
            (snap,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def fetch_signal_dates(
    *,
    end_date: Optional[str] = None,
    limit: int = 2,
    db_path: Optional[Path] = None,
) -> List[str]:
    conn = _connect(db_path)
    try:
        query = (
            "SELECT DISTINCT signal.snapshot_date FROM fundamentus_signals signal "
            f"WHERE {_snapshot_is_visible_sql('signal')}"
        )
        params: list[object] = []
        if end_date:
            query += " AND signal.snapshot_date <= ?"
            params.append(end_date)
        query += " ORDER BY snapshot_date DESC"
        if limit and limit > 0:
            query += " LIMIT ?"
            params.append(int(limit))
        rows = conn.execute(query, params).fetchall()
        return [row["snapshot_date"] for row in rows if row and row["snapshot_date"]]
    finally:
        conn.close()


def fetch_approved_ranking(
    *,
    window_days: Optional[int] = None,
    snapshot_date: Optional[str] = None,
    limit: int = 20,
    db_path: Optional[Path] = None,
) -> Dict[str, object]:
    conn = _connect(db_path)
    try:
        end_date = snapshot_date or latest_snapshot_date(db_path=db_path)
        if not end_date:
            return {
                "rows": [],
                "start_date": None,
                "end_date": None,
                "window_days": window_days,
            }
        start_date: Optional[str] = None
        if window_days and window_days > 0:
            try:
                end_dt = dt.date.fromisoformat(end_date)
                start_dt = end_dt - dt.timedelta(days=max(window_days - 1, 0))
                start_date = start_dt.isoformat()
            except ValueError:
                start_date = None

        query = (
            "SELECT signal.papel, COUNT(*) AS approvals FROM fundamentus_signals signal "
            f"WHERE signal.status = 'approved' AND {_snapshot_is_visible_sql('signal')}"
        )
        params: list[object] = []
        if start_date:
            query += " AND signal.snapshot_date BETWEEN ? AND ?"
            params.extend([start_date, end_date])
        elif snapshot_date:
            query += " AND signal.snapshot_date <= ?"
            params.append(end_date)
        query += " GROUP BY signal.papel ORDER BY approvals DESC, signal.papel ASC"
        if limit:
            query += " LIMIT ?"
            params.append(int(limit))
        rows = conn.execute(query, params).fetchall()
        return {
            "rows": [{"papel": r["papel"], "approvals": r["approvals"]} for r in rows],
            "start_date": start_date,
            "end_date": end_date,
            "window_days": window_days,
        }
    finally:
        conn.close()


__all__ = [
    "FundamentusFilterConfig",
    "FundamentusSchemaError",
    "fetch_fundamentus_results",
    "parse_result_table",
    "normalize_rows",
    "evaluate_row",
    "evaluate_rows",
    "save_snapshot",
    "save_signals",
    "quarantine_snapshots",
    "list_quarantined_snapshots",
    "get_snapshot_integrity",
    "scrape_and_store",
    "apply_filters",
    "latest_snapshot_date",
    "fetch_snapshot",
    "fetch_signals",
    "fetch_filter_run",
    "fetch_signal_dates",
    "fetch_approved_ranking",
]
