from __future__ import annotations

from opcoes.web import create_app


class _Db:
    def close(self) -> None:
        pass


def test_position_history_route_is_read_only_and_renders_audit_timeline(monkeypatch) -> None:
    position = {
        "id": 47,
        "ticker": "GGBRD221",
        "strategy_tag": "covered_call",
        "status": "closed",
        "qty": 400,
        "trade_date": "2026-03-17",
        "exit_date": "2026-04-17",
    }
    monkeypatch.setattr("opcoes.web.get_position", lambda _position_id: position)
    monkeypatch.setattr("opcoes.web.open_db", lambda: _Db())
    monkeypatch.setattr(
        "opcoes.web.list_change_history",
        lambda _db, **_kwargs: [
            {
                "id": 3,
                "occurred_at": "2026-04-18T10:00:00Z",
                "change_kind": "UPDATE",
                "actor": "david",
                "reason": "Fechamento confirmado",
                "prior_values": {**position, "status": "open", "exit_date": None},
            }
        ],
    )

    app = create_app()
    app.testing = True
    response = app.test_client().get("/positions/47/history")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Histórico da posição #47 GGBRD221" in html
    assert "Consulta somente leitura" in html
    assert "Fechamento confirmado" in html
    assert "Data de fechamento" in html
    assert "2026-04-17" in html


def test_position_history_redirects_when_position_does_not_exist(monkeypatch) -> None:
    monkeypatch.setattr("opcoes.web.get_position", lambda _position_id: None)

    app = create_app()
    app.testing = True
    response = app.test_client().get("/positions/999/history")

    assert response.status_code in (302, 303)
    assert "/positions?position_error=" in response.headers["Location"]
