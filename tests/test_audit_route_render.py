from __future__ import annotations

from opcoes.web import create_app


def test_audit_route_renders_realized_section(monkeypatch) -> None:
    monkeypatch.setattr(
        "opcoes.web.list_positions",
        lambda **_kwargs: [
            {
                "id": 1,
                "ticker": "ITSA4",
                "underlying": "ITSA4",
                "side": "long",
                "status": "closed",
                "qty": 100,
                "entry_price": 10.0,
                "fees": 2.0,
                "trade_type": "swing",
                "partial_qty": 0,
                "exit_price": 12.0,
                "exit_reason": "alvo",
                "is_simulated": False,
                "parent_position_id": None,
            }
        ],
    )
    monkeypatch.setattr(
        "opcoes.web.finance.get_ledger_sums_by_position",
        lambda **_kwargs: {
            1: {
                "REALIZED": 198.0,
            }
        },
    )
    monkeypatch.setattr("opcoes.web.build_position_tax_events", lambda _pos: [])

    app = create_app()
    app.testing = True
    client = app.test_client()

    response = client.get("/audit?mode=real&include_closed=1")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Resultado realizado (nao caixa)" in html
    assert "Realizado ledger" in html

