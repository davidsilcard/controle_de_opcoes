from __future__ import annotations

import re
from typing import Optional

# Series tradicionais da B3: A-L = calls, M-X = puts.
CALL_SERIES = set("ABCDEFGHIJKL")
PUT_SERIES = set("MNOPQRSTUVWX")
_B3_OPTION_SERIES_RE = re.compile(r"^[A-Z]{4}([A-Z])(?=\d)")


def infer_option_type(ticker: str) -> Optional[str]:
    """Infere CALL/PUT apenas para tickers no padrao de opcao da B3."""

    if not ticker:
        return None
    text = str(ticker).strip().upper()
    if not text:
        return None

    # Exige raiz de 4 letras + serie + digitos para nao confundir
    # acoes como BBAS3 com opcoes.
    match = _B3_OPTION_SERIES_RE.match(text)
    series_letter: Optional[str] = match.group(1) if match else None
    if series_letter is None:
        return None

    if series_letter in CALL_SERIES:
        return "CALL"
    if series_letter in PUT_SERIES:
        return "PUT"
    return None


def format_decimal(value: Optional[float], decimals: int = 2, signed: bool = False) -> str:
    """Formata float para string PT-BR (virgula decimal)."""
    if value is None:
        return ""
    fmt = f"{{:.{decimals}f}}"
    txt = fmt.format(value).replace(".", ",")
    if signed and value > 0:
        txt = f"+{txt}"
    return txt


def parse_ptbr_number(value: object) -> Optional[float]:
    """Converte strings com virgula/porcentagem em float."""

    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            return float(value)
        except Exception:  # noqa: BLE001
            return None
    text = str(value).strip()
    if not text:
        return None
    cleaned = (
        text.replace("\xa0", "")
        .replace("\u2212", "-")
        .replace("%", "")
        .replace("+", "")
        .replace(" ", "")
    )
    if not cleaned or cleaned == "-":
        return None
    cleaned = cleaned.replace('"', "").replace("'", "")
    has_comma = "," in cleaned
    has_dot = "." in cleaned
    if has_comma and has_dot:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    elif has_comma:
        cleaned = cleaned.replace(",", ".")
    elif has_dot and re.fullmatch(r"\d{1,3}(?:\.\d{3})+", cleaned):
        cleaned = cleaned.replace(".", "")
    try:
        return float(cleaned)
    except ValueError:
        return None


__all__ = ["infer_option_type", "format_decimal", "parse_ptbr_number", "CALL_SERIES", "PUT_SERIES"]
