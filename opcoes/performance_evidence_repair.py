from __future__ import annotations

import math
from dataclasses import asdict, dataclass, replace
from typing import Any, Mapping

from .db import db_transaction
from .portfolio import _ensure_tables, update_position_performance_metadata
from .utils import infer_option_type


class PerformanceEvidenceRepairError(RuntimeError):
    """Raised when documented performance metadata cannot be recorded safely."""


@dataclass(frozen=True)
class PerformanceEvidenceRepairPlan:
    position_id: int
    ticker: str
    contract_strike: float | None
    capital_committed: float | None
    contract_update_required: bool
    capital_update_required: bool
    source_update_required: bool

    @property
    def update_required(self) -> bool:
        return any(
            (
                self.contract_update_required,
                self.capital_update_required,
                self.source_update_required,
            )
        )

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["update_required"] = self.update_required
        return result


def _money(value: Any, *, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise PerformanceEvidenceRepairError(f"{label} inválido.") from exc
    if result <= 0 or not math.isfinite(result):
        raise PerformanceEvidenceRepairError(f"{label} deve ser maior que zero.")
    return round(result, 6)


def _same_money(left: Any, right: Any) -> bool:
    try:
        return round(float(left or 0.0) - float(right or 0.0), 6) == 0.0
    except (TypeError, ValueError):
        return False


def _append_source(existing: Any, incoming: str) -> str:
    parts = [part.strip() for part in str(existing or "").split("|") if part.strip()]
    if incoming not in parts:
        parts.append(incoming)
    return " | ".join(parts)


def build_performance_evidence_repair_plan(
    *,
    position: Mapping[str, Any],
    expected_ticker: str,
    contract_strike: Any = None,
    expected_expiry: str | None = None,
    capital_committed: Any = None,
) -> PerformanceEvidenceRepairPlan:
    try:
        position_id = int(position.get("id") or 0)
    except (TypeError, ValueError) as exc:
        raise PerformanceEvidenceRepairError("ID da posição inválido.") from exc
    if position_id <= 0:
        raise PerformanceEvidenceRepairError("ID da posição inválido.")

    ticker = str(position.get("ticker") or "").strip().upper()
    if ticker != str(expected_ticker or "").strip().upper():
        raise PerformanceEvidenceRepairError(
            f"A posição #{position_id} não corresponde ao ticker esperado."
        )
    if infer_option_type(ticker) not in {"CALL", "PUT"}:
        raise PerformanceEvidenceRepairError("A posição informada não é uma opção.")
    if str(position.get("side") or "").strip().lower() != "short":
        raise PerformanceEvidenceRepairError("O reparo atende somente opções vendidas.")
    strategy = str(position.get("strategy_tag") or "").strip().lower()
    if strategy not in {"covered_call", "cash_put"}:
        raise PerformanceEvidenceRepairError("A posição não pertence a uma estratégia de opção vendida.")

    parsed_strike = (
        _money(contract_strike, label="Strike") if contract_strike is not None else None
    )
    parsed_capital = (
        _money(capital_committed, label="Capital comprometido")
        if capital_committed is not None
        else None
    )
    if parsed_capital is not None and strategy != "covered_call":
        raise PerformanceEvidenceRepairError(
            "Garantia histórica só pode ser registrada para Covered Call."
        )
    if parsed_strike is not None:
        current_expiry = str(position.get("contract_expiry") or "").strip()
        if not expected_expiry or current_expiry != expected_expiry:
            raise PerformanceEvidenceRepairError(
                "O vencimento atual não confere com a evidência esperada."
            )
        current_strike = position.get("contract_strike")
        if current_strike is not None and not _same_money(current_strike, parsed_strike):
            raise PerformanceEvidenceRepairError(
                "A posição já possui strike diferente; não sobrescreva sem reparo específico."
            )
    if parsed_capital is not None:
        current_capital = position.get("capital_committed")
        if current_capital is not None and not _same_money(current_capital, parsed_capital):
            raise PerformanceEvidenceRepairError(
                "A posição já possui garantia diferente; não sobrescreva sem nova auditoria."
            )

    return PerformanceEvidenceRepairPlan(
        position_id=position_id,
        ticker=ticker,
        contract_strike=parsed_strike,
        capital_committed=parsed_capital,
        contract_update_required=parsed_strike is not None
        and not _same_money(position.get("contract_strike"), parsed_strike),
        capital_update_required=parsed_capital is not None
        and not _same_money(position.get("capital_committed"), parsed_capital),
        source_update_required=False,
    )


def repair_performance_evidence(
    *,
    position_id: int,
    expected_ticker: str,
    contract_strike: Any = None,
    expected_expiry: str | None = None,
    contract_source_ref: str | None = None,
    capital_committed: Any = None,
    capital_source_ref: str | None = None,
    apply: bool = False,
) -> dict[str, Any]:
    if contract_strike is None and capital_committed is None:
        raise PerformanceEvidenceRepairError("Informe strike ou garantia histórica.")
    contract_source = str(contract_source_ref or "").strip()
    capital_source = str(capital_source_ref or "").strip()
    if contract_strike is not None and not contract_source:
        raise PerformanceEvidenceRepairError("Informe a fonte documental do strike.")
    if capital_committed is not None and not capital_source:
        raise PerformanceEvidenceRepairError("Informe a fonte documental da garantia.")
    try:
        resolved_id = int(position_id)
    except (TypeError, ValueError) as exc:
        raise PerformanceEvidenceRepairError("ID da posição inválido.") from exc
    if resolved_id <= 0:
        raise PerformanceEvidenceRepairError("ID da posição inválido.")

    lock = " FOR UPDATE" if apply else ""
    with db_transaction() as conn:
        _ensure_tables(conn, commit=False)
        position = conn.execute(
            f"SELECT * FROM positions WHERE id = %s{lock}", (resolved_id,)
        ).fetchone()
        if position is None:
            raise PerformanceEvidenceRepairError("Posição não encontrada.")
        plan = build_performance_evidence_repair_plan(
            position=position,
            expected_ticker=expected_ticker,
            contract_strike=contract_strike,
            expected_expiry=expected_expiry,
            capital_committed=capital_committed,
        )
        merged_contract_source = _append_source(
            position.get("performance_source_ref"), contract_source
        ) if contract_source else str(position.get("performance_source_ref") or "").strip()
        current_capital_source = str(position.get("capital_source_ref") or "").strip()
        merged_capital_source = _append_source(current_capital_source, capital_source) if capital_source else current_capital_source
        source_update_required = bool(
            (contract_source and merged_contract_source != str(position.get("performance_source_ref") or "").strip())
            or (capital_source and merged_capital_source != current_capital_source)
        )
        plan = replace(plan, source_update_required=source_update_required)
        if apply and plan.update_required:
            changes: dict[str, Any] = {}
            if plan.contract_update_required:
                changes["contract_strike"] = plan.contract_strike
                changes["performance_evidence_state"] = "pending"
            if plan.capital_update_required:
                changes["capital_committed"] = plan.capital_committed
                changes["capital_source"] = "garantia_documentada"
            if contract_source and merged_contract_source:
                changes["performance_source_ref"] = merged_contract_source
            if capital_source and merged_capital_source:
                changes["capital_source_ref"] = merged_capital_source
            update_position_performance_metadata(
                position_id=plan.position_id,
                conn=conn,
                **changes,
            )

    result = plan.to_dict()
    result["applied"] = bool(apply and plan.update_required)
    return result


__all__ = [
    "PerformanceEvidenceRepairError",
    "PerformanceEvidenceRepairPlan",
    "build_performance_evidence_repair_plan",
    "repair_performance_evidence",
]
