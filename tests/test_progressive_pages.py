from __future__ import annotations

from opcoes.web import create_app


def test_ranking_route_renders_progressive_placeholder(monkeypatch) -> None:
    monkeypatch.setattr(
        "opcoes.web._build_ranking_shell_page_context",
        lambda **_kwargs: {
            "min_score": 10,
            "limit": 50,
            "recurring_days": 30,
            "recurring_limit": 20,
            "underlying_filter": "PETR",
            "option_type_filter": "CALL",
        },
    )
    app = create_app()
    app.testing = True
    client = app.test_client()

    response = client.get("/")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'id="ranking-dashboard"' in html
    assert 'hx-get="/partial/ranking?' in html
    assert "Carregando ranking, tabelas e posições..." in html


def test_ranking_partial_renders_data(monkeypatch) -> None:
    monkeypatch.setattr(
        "opcoes.web.get_ranking_context",
        lambda _args: {
            "empty_state_message": "",
            "data": type(
                "ReportData",
                (),
                {
                    "snapshot_date": "2026-04-21",
                    "opportunities": [
                        {
                            "ticker": "PETRA999",
                            "underlying": "PETR4",
                            "score_total": 12.3,
                            "best_ask": 1.2,
                            "best_bid": 1.1,
                            "ultimo": 1.15,
                            "preco_teorico": 1.0,
                            "%_Alta_p_2x": 4.5,
                        }
                    ],
                    "theoretical_opportunities": [],
                    "recurring_opportunities": [],
                },
            )(),
            "option_type_filter": "CALL",
            "book_availability": {
                "show_warning": False,
                "severity": "warning",
                "no_tradeable": False,
                "watchlist_count": 0,
                "total_count": 1,
            },
            "positions_real": [],
            "positions_simulated": [],
        },
    )
    app = create_app()
    app.testing = True
    client = app.test_client()

    response = client.get("/partial/ranking")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Snapshot: 2026-04-21" in html
    assert "PETRA999" in html


def test_fundamentus_route_renders_progressive_placeholder(monkeypatch) -> None:
    monkeypatch.setattr(
        "opcoes.web._build_fundamentus_shell_page_context",
        lambda **_kwargs: {
            "snapshot_date": "2026-04-21",
            "limit": 100,
            "status_filter": "approved",
            "ranking_window_days": 30,
        },
    )
    app = create_app()
    app.testing = True
    client = app.test_client()

    response = client.get("/fundamentus")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'id="fundamentus-dashboard"' in html
    assert 'hx-get="/fundamentus/partial/dashboard?' in html
    assert "Carregando filtros aplicados, ranking histórico e tabela Fundamentus..." in html


def test_fundamentus_partial_renders_rows(monkeypatch) -> None:
    monkeypatch.setattr(
        "opcoes.web.get_fundamentus_context",
        lambda _args: {
            "message": "ok",
            "snapshot_date": "2026-04-21",
            "rows": [
                {
                    "papel": "PETR4",
                    "cotacao": 37.5,
                    "preco_teto": 42.0,
                    "div_yield": 12.0,
                    "roe": 20.0,
                    "sector": "Energia",
                    "signal": type("Signal", (), {"status": "approved"})(),
                }
            ],
            "signals_available": True,
            "status_label": "Aprovadas",
            "approved_count": 1,
            "rejected_count": 0,
            "filtered_rows_count": 1,
            "total_rows": 1,
            "put_target_vencimento": None,
            "ranking_window": [],
        },
    )
    app = create_app()
    app.testing = True
    client = app.test_client()

    response = client.get("/fundamentus/partial/dashboard")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Snapshot: 2026-04-21" in html
    assert "PETR4" in html
    assert "Aprovada" in html
