from __future__ import annotations

from opcoes.web import create_app


def _sample_ranking_opportunity(*, ticker: str, underlying: str) -> dict[str, object]:
    return {
        "ticker": ticker,
        "underlying": underlying,
        "score_total": 12.3,
        "best_ask": 1.2,
        "best_bid": 1.1,
        "ultimo": 1.15,
        "preco_teorico": 1.0,
        "preco_max_10_pct": 1.1,
        "preco_max_20_pct": 1.2,
        "desconto_teorico_pct": 5.0,
        "spread_pct": 3.0,
        "illiquidez_flag": False,
        "distorcao_preco_pct": 2.5,
        "distorcao_flag": False,
        "%_Alta_p_2x": 4.5,
        "custo_pct": 1.8,
        "extrinsic_value": 0.6,
        "extrinsic_pct_spot": 1.2,
        "breakeven_price": 49.0,
        "breakeven_dist_pct": 3.5,
        "prob_be_pct": 66.0,
        "underlying_price_date": "2026-04-21",
        "underlying_price": 48.2,
        "dias_uteis": 17,
        "vol_impl_perc": 28.5,
        "iv_rank_180d": 65.0,
        "hv_21d": 22.1,
        "hv_63d": 23.4,
        "hv_126d": 24.0,
        "hv_252d": 25.2,
        "iv_hv_spread": 4.5,
        "hv_ref_window": 21,
        "iv_score": 7,
        "em2x_score": 8,
        "vol_fluxo_5d": 12345.0,
        "prob_itm_pct": 31.0,
        "Status_Moneyness": "ITM",
    }


def _sample_ranking_position(*, position_id: int, ticker: str) -> dict[str, object]:
    return {
        "id": position_id,
        "ticker": ticker,
        "trade_date": "2026-04-10",
        "qty": 100,
        "entry_price": 1.0,
        "last_price": 1.1,
        "strike": 50.0,
        "dias_uteis": 17,
        "pl": 10.0,
        "pl_pct": 10.0,
        "breakeven_price": 49.0,
        "score_total": 12.3,
        "trend_flag": "1",
    }


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
    opp = _sample_ranking_opportunity(ticker="PETRA999", underlying="PETR4")
    watch = {
        **_sample_ranking_opportunity(ticker="PETRB888", underlying="PETR4"),
        "best_ask": None,
        "best_bid": None,
        "spread_pct": None,
    }
    recurring = {
        **_sample_ranking_opportunity(ticker="PETRC777", underlying="PETR4"),
        "hits": 3,
        "presence_pct": 50.0,
        "last_seen": "2026-04-21",
    }
    monkeypatch.setattr(
        "opcoes.web.get_ranking_context",
        lambda _args: {
            "empty_state_message": "",
            "data": type(
                "ReportData",
                (),
                {
                    "snapshot_date": "2026-04-21",
                    "opportunities": [opp],
                    "theoretical_opportunities": [watch],
                    "rational_opportunities": [opp],
                    "lottery_opportunities": [opp],
                    "recurring_opportunities": [recurring],
                    "recurring_window_start": "2026-03-22",
                    "recurring_window_days": 30,
                    "recurring_snapshot_days": 6,
                },
            )(),
            "option_type_filter": "CALL",
            "book_availability": {
                "show_warning": False,
                "severity": "warning",
                "no_tradeable": False,
                "watchlist_count": 1,
                "total_count": 2,
                "watchlist_ratio_pct": 50.0,
            },
            "positions_real": [
                _sample_ranking_position(position_id=1, ticker="PETRA999")
            ],
            "positions_simulated": [
                _sample_ranking_position(position_id=2, ticker="PETRS111")
            ],
            "totals_real": {
                "total_purchase": 100.0,
                "total_current": 110.0,
                "total_pl": 10.0,
                "total_pl_pct": 10.0,
            },
            "totals_simulated": {
                "total_purchase": 100.0,
                "total_current": 110.0,
                "total_pl": 10.0,
                "total_pl_pct": 10.0,
            },
            "alerts_map": {1: ["Spread acima do limite"]},
            "segments": {
                "carteira": [opp],
                "alavancagem": [
                    {**opp, "ticker": "PETRA998", "Status_Moneyness": "ATM"}
                ],
                "aposta": [{**opp, "ticker": "PETRA997", "Status_Moneyness": "OTM"}],
            },
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
    assert "Top Apostas Racionais" in html
    assert "Top Loterias" in html
    assert "Watchlist (sem book" in html
    assert "Oportunidades recorrentes" in html
    assert "Segmentos por perfil" in html
    assert "Posições abertas real" in html
    assert "Posições abertas fictício" in html
    assert "Spread acima do limite" in html


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
    assert (
        "Carregando filtros aplicados, ranking histórico e tabela Fundamentus..."
        in html
    )


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
                        {
                            "status": "approved",
                            "reason_label": "Aprovada em todos os filtros.",
                            "reason": "approved",
                            "failed_step": None,
                        },
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
            "sector_breakdown": [
                {"label": "Energia", "count": 1, "pct": 100.0, "color": "#4e79a7"}
            ],
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


def test_fundamentus_partial_explains_empty_approved_list(monkeypatch) -> None:
    monkeypatch.setattr(
        "opcoes.web.get_fundamentus_context",
        lambda _args: {
            "message": "Snapshot e filtros carregados a partir do banco.",
            "snapshot_date": "2026-07-21",
            "rows": [],
            "total_rows": 282,
            "filtered_rows_count": 0,
            "signals_available": True,
            "approved_count": 0,
            "rejected_count": 282,
            "status_filter": "approved",
            "status_label": "Aprovadas",
            "limit": None,
            "ranking_window_days": 30,
            "changes_reference_date": None,
            "entered_opportunities": [],
            "exited_opportunities": [],
            "ranking_total": [],
            "ranking_window": [],
        },
    )
    app = create_app()
    app.testing = True
    client = app.test_client()

    response = client.get("/fundamentus/partial/dashboard")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Nenhuma ação foi aprovada pelos filtros deste snapshot." in html
    assert "Em construcao. Esta aba vai concentrar" not in html
