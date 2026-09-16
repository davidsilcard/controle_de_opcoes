from __future__ import annotations

import json
from typing import Any, Mapping, Sequence


_POSITION_FIELDS = (
    ("ticker", "Ticker"),
    ("underlying", "Ativo-base"),
    ("strategy_tag", "Estratégia"),
    ("side", "Lado"),
    ("status", "Status"),
    ("qty", "Quantidade"),
    ("entry_price", "Preço de entrada"),
    ("fees", "Taxas"),
    ("trade_date", "Data de abertura"),
    ("exit_date", "Data de fechamento"),
    ("exit_price", "Preço de fechamento"),
    ("exit_reason", "Motivo do fechamento"),
    ("contract_strike", "Strike do contrato"),
    ("contract_expiry", "Vencimento do contrato"),
    ("capital_committed", "Capital de garantia"),
    ("performance_source_ref", "Fonte informada"),
    ("notes", "Observações"),
    ("void_reason", "Motivo da anulação"),
)


def _as_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return dict(decoded) if isinstance(decoded, Mapping) else {}
    return {}


def _normalized_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    return str(value).strip()


def _display_value(value: Any) -> str:
    normalized = _normalized_value(value)
    if normalized is None or normalized == "":
        return "—"
    return str(normalized)


def build_position_history_timeline(
    position: Mapping[str, Any],
    history_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Converte pré-imagens imutáveis em alterações legíveis para a posição."""

    rows = [dict(row) for row in history_rows]
    timeline: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        before = _as_mapping(row.get("prior_values"))
        after = (
            _as_mapping(rows[index + 1].get("prior_values"))
            if index + 1 < len(rows)
            else dict(position)
        )
        changes = []
        for field, label in _POSITION_FIELDS:
            old_value = _normalized_value(before.get(field))
            new_value = _normalized_value(after.get(field))
            if old_value == new_value:
                continue
            changes.append(
                {
                    "field": field,
                    "label": label,
                    "before": _display_value(before.get(field)),
                    "after": _display_value(after.get(field)),
                }
            )
        timeline.append(
            {
                "id": row.get("id"),
                "occurred_at": row.get("occurred_at"),
                "change_kind": row.get("change_kind"),
                "actor": row.get("actor") or "system",
                "reason": row.get("reason") or "Motivo não informado no registro legado.",
                "changes": changes,
            }
        )
    return list(reversed(timeline))


__all__ = ["build_position_history_timeline"]
