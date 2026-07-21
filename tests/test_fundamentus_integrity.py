from __future__ import annotations

import pytest

from opcoes.fundamentus import (
    FundamentusFilterConfig,
    fetch_approved_ranking,
    fetch_signals,
    fetch_snapshot,
    latest_snapshot_date,
    list_quarantined_snapshots,
    quarantine_snapshots,
    save_signals,
    save_snapshot,
)


pytestmark = pytest.mark.requires_postgres


def _row(papel: str) -> dict[str, object]:
    return {
        "papel": papel,
        "liquidez_2m": 2_000_000.0,
        "div_bruta_patrim": 0.4,
        "cresc_rec_5a": 5.0,
        "div_yield": 8.0,
        "roe": 18.0,
        "margem_liquida": 12.0,
    }


def _approved_signal(papel: str) -> dict[str, object]:
    return {
        "papel": papel,
        "status": "approved",
        "failed_step": None,
        "failed_rule": None,
        "failed_value": None,
        "reason": "approved",
    }


def test_quarantined_snapshots_are_preserved_but_excluded_from_strategy() -> None:
    save_snapshot([_row("PETR4")], snapshot_date="2026-05-01")
    save_signals(
        [_approved_signal("PETR4")],
        snapshot_date="2026-05-01",
        cfg=FundamentusFilterConfig(),
    )
    save_snapshot([_row("VALE3")], snapshot_date="2026-05-04")
    save_signals(
        [_approved_signal("VALE3")],
        snapshot_date="2026-05-04",
        cfg=FundamentusFilterConfig(),
    )

    assert latest_snapshot_date() == "2026-05-04"
    assert (
        quarantine_snapshots(
            start_date="2026-05-04",
            end_date="2026-05-04",
            reason="Coleta com colunas deslocadas.",
        )
        == 1
    )

    assert latest_snapshot_date() == "2026-05-01"
    assert fetch_snapshot(snapshot_date="2026-05-04") == []
    assert fetch_signals(snapshot_date="2026-05-04") == []
    assert list_quarantined_snapshots()[0]["snapshot_date"] == "2026-05-04"

    ranking = fetch_approved_ranking(snapshot_date="2026-05-04")
    assert ranking["rows"] == [{"papel": "PETR4", "approvals": 1}]


def test_recollection_releases_snapshot_from_quarantine() -> None:
    save_snapshot([_row("PETR4")], snapshot_date="2026-05-04")
    quarantine_snapshots(
        start_date="2026-05-04",
        end_date="2026-05-04",
        reason="Coleta com colunas deslocadas.",
    )

    save_snapshot([_row("PETR4")], snapshot_date="2026-05-04")

    assert latest_snapshot_date() == "2026-05-04"
    assert len(fetch_snapshot(snapshot_date="2026-05-04")) == 1
    assert list_quarantined_snapshots() == []
