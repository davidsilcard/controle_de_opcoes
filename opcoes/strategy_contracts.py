from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


PROTECTED_STRATEGIES = frozenset({"cash_put", "covered_call", "ranking", "estoque"})


class StrategyContractError(ValueError):
    """Erro de contrato operacional entre a aba Posicoes e uma estrategia."""


@dataclass(frozen=True)
class FieldContract:
    name: str
    label: str
    numeric: bool = False
    integer: bool = False
    boolean: bool = False


IDENTITY_FIELDS: tuple[FieldContract, ...] = (
    FieldContract("ticker", "ticker"),
    FieldContract("underlying", "ativo"),
    FieldContract("trade_date", "data de entrada"),
    FieldContract("qty", "quantidade", numeric=True, integer=True),
    FieldContract("entry_price", "preco de entrada", numeric=True),
    FieldContract("trade_type", "tipo"),
    FieldContract("side", "posicao"),
    FieldContract("strategy_tag", "estrategia"),
    FieldContract("is_simulated", "modo real/simulado", boolean=True),
    FieldContract("parent_position_id", "vinculo legado", numeric=True, integer=True),
)


def normalize_strategy(value: Any) -> str:
    return str(value or "").strip().lower()


def is_protected_strategy(value: Any) -> bool:
    return normalize_strategy(value) in PROTECTED_STRATEGIES


def _empty(value: Any) -> bool:
    return value is None or str(value).strip() == ""


def _norm_text(value: Any) -> str:
    return str(value or "").strip()


def _norm_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in {"1", "true", "sim", "yes", "on"}


def _norm_number(value: Any, *, integer: bool) -> float | int | None:
    if _empty(value):
        return None
    if isinstance(value, str):
        value = value.strip().replace(",", ".")
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if integer:
        return int(number)
    return round(number, 8)


def _field_value(value: Any, field: FieldContract) -> Any:
    if field.boolean:
        return _norm_bool(value)
    if field.numeric:
        return _norm_number(value, integer=field.integer)
    if field.name in {"strategy_tag", "side", "trade_type"}:
        return str(value or "").strip().lower()
    return _norm_text(value)


def _changed_fields(
    existing: dict[str, Any],
    proposed: dict[str, Any],
    fields: Iterable[FieldContract],
) -> list[str]:
    changed: list[str] = []
    for field in fields:
        old = _field_value(existing.get(field.name), field)
        new = _field_value(proposed.get(field.name), field)
        if old != new:
            changed.append(field.label)
    return changed


def validate_position_identity_update(
    *,
    existing: dict[str, Any] | None,
    proposed: dict[str, Any],
) -> None:
    """Impede que a tabela generica altere a identidade de uma estrategia.

    A aba Posicoes pode ajustar fechamento, notas, taxas e campos auxiliares.
    Ela nao deve reclassificar uma operacao ja criada como outra estrategia,
    outro lado ou outro ativo. Esse tipo de correcao exige fluxo proprio, com
    motivo e evidencia.
    """

    if not existing:
        return

    existing_strategy = normalize_strategy(existing.get("strategy_tag"))
    proposed_strategy = normalize_strategy(proposed.get("strategy_tag"))
    if not (is_protected_strategy(existing_strategy) or is_protected_strategy(proposed_strategy)):
        return

    changed = _changed_fields(existing, proposed, IDENTITY_FIELDS)
    if not changed:
        return

    changed_display = ", ".join(changed)
    raise StrategyContractError(
        "A aba Posicoes bloqueou a alteracao de campos estruturais "
        f"({changed_display}) de uma operacao com estrategia. "
        "Use o fluxo da propria estrategia ou um ajuste manual supervisionado."
    )
