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
            "changes_reference_date": "2026-04-20",
            "entered_opportunities": ["PETR4"],
            "exited_opportunities": ["VALE3"],
            "ranking_total": [{"papel": "PETR4", "approvals": 4}],
            "rows": [
                {
                    "papel": "PETR4",
                    "cotacao": 37.5,
                    "preco_teto": 42.0,
                    "pl": 5.0,
                    "pvp": 1.2,
                    "psr": 1.1,
                    "div_yield": 12.0,
                    "p_ativo": 1.0,
                    "p_cap_giro": 1.0,
                    "p_ebit": 1.0,
                    "p_ativo_circ_liq": 1.0,
                    "ev_ebit": 1.0,
                    "ev_ebitda": 1.0,
                    "margem_ebit": 10.0,
                    "margem_liquida": 10.0,
                    "liquidez_corrente": 1.1,
                    "roic": 10.0,
                    "roe": 20.0,
                    "liquidez_2m": 1000000.0,
                    "patrimonio_liq": 5000000.0,
                    "div_bruta_patrim": 0.2,
                    "cresc_rec_5a": 5.0,
                    "peg_ratio": 1.0,
                    "sector": "Energia",
                    "signal": type(
                        "Signal",
                        (),
                        {"status": "approved", "reason_label": "Aprovada em todos os filtros.", "reason": "approved", "failed_step": None},
                    )(),
                }
            ],
            "signals_available": True,
            "status_label": "Aprovadas",
            "status_filter": "approved",
            "limit": 100,
            "ranking_window_days": 30,
            "approved_count": 1,
            "rejected_count": 0,
            "filtered_rows_count": 1,
            "total_rows": 1,
            "put_target_vencimento": "2026-05-15",
            "put_score_formula": "score didatico",
            "put_min_premium_pct": 0.5,
            "put_min_score": 4.0,
            "put_watchlist_count": 0,
            "put_profile_breakdown": [{"label": "Conservadora", "count": 1}],
            "put_opportunities": [
                {
                    "papel": "PETRQ33",
                    "cotacao": 37.5,
                    "contrato": "PETRQ33",
                    "strike": 34.0,
                    "preco_ref": 0.8,
                    "premium_source": "best_bid",
                    "premio_pct": 2.1,
                    "premio_mensal_pct": 2.1,
                    "distancia_strike_pct": 9.0,
                    "put_score": 7.5,
                    "put_profile": "Equilibrada",
                    "execution_note": "Acompanha book",
                    "dias_ate_vencimento": 18,
                }
            ],
            "put_distance_limit_pct": 15.0,
            "put_target_monthly_yield_pct": 1.0,
            "put_snapshot_date": "2026-04-21",
            "ranking_window": [{"papel": "PETR4", "approvals": 2}],
            "ranking_window_start": "2026-03-22",
            "ranking_window_end": "2026-04-21",
            "target_yield_pct": 8.0,
            "sector_breakdown": [{"label": "Energia", "count": 1, "pct": 100.0, "color": "#4e79a7"}],
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
    assert "Oportunidades de PUTs" in html
    assert "Mudancas na lista de aprovadas" in html
    assert "Divisao por setor" in html
    assert 'data-default-sort-index="9"' in html
