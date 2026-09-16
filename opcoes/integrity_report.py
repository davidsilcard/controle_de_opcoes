from __future__ import annotations

from typing import Any, Mapping, Sequence


_TOTAL_METRICS = (
    ("premium", "Prêmio"),
    ("darf", "DARF"),
    ("cash_net", "Caixa operacional"),
    ("total_cash", "Caixa total"),
    ("realized", "Resultado realizado"),
)


def _value(item: Any, name: str, default: Any = None) -> Any:
    if isinstance(item, Mapping):
        return item.get(name, default)
    return getattr(item, name, default)


def _category_for(code: str) -> tuple[str, str]:
    normalized = str(code or "").strip().upper()
    if normalized == "LEDGER_ORFAO":
        return "orphan", "Lançamento órfão"
    if "DUPLICIDADE" in normalized:
        return "duplicate", "Possível duplicidade"
    if normalized.endswith("_DIVERGENTE"):
        return "divergence", "Divergência financeira"
    return "state", "Estado incompatível"


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


def build_integrity_report(
    *,
    reconciliation_issues: Sequence[Any],
    position_issues: Sequence[Any],
    totals: Mapping[str, Any],
) -> dict[str, Any]:
    """Organiza diagnósticos existentes em um relatório somente leitura."""

    findings: list[dict[str, Any]] = []
    seen: set[tuple[int, str]] = set()
    for issue in [*reconciliation_issues, *position_issues]:
        code = str(_value(issue, "code", "") or "")
        position_id = int(_value(issue, "position_id", 0) or 0)
        key = (position_id, code)
        if key in seen:
            continue
        seen.add(key)
        category, category_label = _category_for(code)
        findings.append(
            {
                "category": category,
                "category_label": category_label,
                "position_id": position_id,
                "ticker": _value(issue, "ticker", "—") or "—",
                "code": code,
                "message": _value(issue, "message", "Sem detalhe disponível."),
                "action": _value(
                    issue,
                    "action",
                    "Revise os registros e a fonte antes de qualquer correção.",
                ),
            }
        )

    for metric, label in _TOTAL_METRICS:
        expected = _number(totals.get(f"expected_{metric}"))
        actual = _number(totals.get(f"actual_{metric}"))
        if expected is None or actual is None:
            continue
        difference = round(actual - expected, 2)
        if difference == 0.0:
            continue
        findings.append(
            {
                "category": "divergence",
                "category_label": "Divergência financeira",
                "position_id": 0,
                "ticker": "Total da auditoria",
                "code": f"TOTAL_{metric.upper()}_DIVERGENTE",
                "message": (
                    f"{label}: esperado R$ {expected:.2f}; "
                    f"registrado R$ {actual:.2f}; diferença R$ {difference:.2f}."
                ),
                "action": "Localize as posições divergentes; não ajuste totais diretamente.",
            }
        )

    findings.sort(
        key=lambda item: (
            {"orphan": 0, "duplicate": 1, "state": 2, "divergence": 3}[item["category"]],
            item["position_id"],
            item["code"],
        )
    )
    counts = {
        category: sum(1 for item in findings if item["category"] == category)
        for category in ("orphan", "duplicate", "state", "divergence")
    }
    return {
        "findings": findings,
        "counts": counts,
        "total": len(findings),
        "unverifiable_darf_count": int(totals.get("unverifiable_darf_count") or 0),
    }


__all__ = ["build_integrity_report"]
