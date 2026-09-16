from __future__ import annotations

from opcoes.record_timeline import build_position_history_timeline


def test_position_timeline_compares_each_revision_with_the_next_state() -> None:
    position = {
        "id": 47,
        "ticker": "GGBRD221",
        "status": "closed",
        "qty": 400,
        "entry_price": 0.2,
        "exit_date": "2026-04-17",
    }
    history = [
        {
            "id": 1,
            "occurred_at": "2026-04-17T10:00:00Z",
            "change_kind": "UPDATE",
            "actor": "david",
            "reason": "Confirmação de fechamento",
            "prior_values": {**position, "status": "open", "exit_date": None},
        },
        {
            "id": 2,
            "occurred_at": "2026-04-18T10:00:00Z",
            "change_kind": "UPDATE",
            "actor": "david",
            "reason": "Correção de quantidade",
            "prior_values": {**position, "qty": 300},
        },
    ]

    timeline = build_position_history_timeline(position, history)

    assert [entry["id"] for entry in timeline] == [2, 1]
    latest = timeline[0]
    assert latest["reason"] == "Correção de quantidade"
    assert latest["changes"] == [
        {
            "field": "qty",
            "label": "Quantidade",
            "before": "300",
            "after": "400",
        }
    ]
    earlier = timeline[1]
    assert [change["field"] for change in earlier["changes"]] == [
        "status",
        "qty",
        "exit_date",
    ]
