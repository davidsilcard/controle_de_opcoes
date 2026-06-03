from __future__ import annotations

from types import SimpleNamespace

from opcoes.tax import TaxSummary
from opcoes.web import create_app


def _disable_strategy_caches(monkeypatch) -> None:
    monkeypatch.setattr("opcoes.web.get_persisted_page_cache", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("opcoes.web.set_persisted_page_cache", lambda *_args, **_kwargs: None)


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


def _sample_positions_context() -> dict[str, object]:
    position = {
        "id": 7,
        "ticker": "PETRE500",
        "underlying": "PETR4",
        "status": "open",
        "trade_type": "swing",
        "side": "short",
        "strategy_tag": "covered_call",
        "parent_position_id": "",
        "is_simulated": False,
        "trade_date": "2026-04-14",
        "vencimento": "15/05/2026",
        "dias_uteis": 16,
        "qty": 100,
        "entry_price": 1.06,
        "last_price": 1.01,
        "pl": 4.86,
        "pl_pct": 4.58,
        "breakeven_price": 47.0,
        "score_total": 1.2,
        "trend_flag": "1",
        "realized_pl": None,
        "partial_qty": 0,
        "partial_price": None,
        "partial_date": None,
        "exit_reason": None,
        "fees": 0.14,
        "open_qty": 100,
        "notes": "",
        "irrf": None,
        "is_option": True,
        "premium_recorded": True,
        "market_status_label": "Snapshot",
        "market_source_label": "Snapshot",
        "market_time_display": "22/04/2026",
        "exit_date": None,
        "exit_price": None,
        "strike": 50.0,
    }
    return {
        "filter_ticker": "",
        "filter_underlying": "",
        "filter_status": "all",
        "filter_strategy_tag": "",
        "filter_trade_type": "",
        "filter_is_simulated": "",
        "inventory_summary": [
            {
                "ticker": "PETR4",
                "is_simulated": False,
                "shares_total": 100,
                "shares_reserved": 100,
                "shares_free": 0,
                "avg_price": 31.90,
                "coverage_status": "ok",
                "price_status": "ok",
            }
        ],
        "realized_summary": {
            "available_years": [2026],
            "available_months": [4],
            "selected_year": 2026,
            "selected_month": 4,
            "overall_totals": {
                "count": 1,
                "total_gross": 10.0,
                "total_fees": 1.0,
                "total_net": 9.0,
                "total_profit": 9.0,
                "total_loss": 0.0,
                "profit_count": 1,
                "loss_count": 0,
                "breakeven_count": 0,
            },
            "period_totals": {
                "count": 1,
                "total_gross": 10.0,
                "total_fees": 1.0,
                "total_net": 9.0,
                "total_profit": 9.0,
                "total_loss": 0.0,
                "profit_count": 1,
                "loss_count": 0,
                "breakeven_count": 0,
            },
            "by_year": [
                {
                    "year": 2026,
                    "count": 1,
                    "total_gross": 10.0,
                    "total_fees": 1.0,
                    "total_net": 9.0,
                }
            ],
            "by_month": [
                {
                    "year": 2026,
                    "month": 4,
                    "month_label": "2026-04",
                    "count": 1,
                    "total_gross": 10.0,
                    "total_fees": 1.0,
                    "total_net": 9.0,
                }
            ],
            "period_positions": [
                {
                    "exit_date": "2026-04-20",
                    "ticker": "PETRD521",
                    "underlying": "PETR4",
                    "strategy_tag": "covered_call",
                    "exit_reason": "alvo",
                    "qty": 100,
                    "gross_result": 10.0,
                    "fees": 1.0,
                    "net_result": 9.0,
                }
            ],
        },
        "auth_enabled": False,
        "current_username": None,
        "positions": [position],
    }


def test_strategy_contract_ranking_preserves_core_blocks(monkeypatch) -> None:
    _disable_strategy_caches(monkeypatch)
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
                {
                    "id": 1,
                    "ticker": "PETRA999",
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
            ],
            "positions_simulated": [],
            "totals_real": {
                "total_purchase": 100.0,
                "total_current": 110.0,
                "total_pl": 10.0,
                "total_pl_pct": 10.0,
            },
            "totals_simulated": {
                "total_purchase": 0.0,
                "total_current": 0.0,
                "total_pl": 0.0,
                "total_pl_pct": None,
            },
            "alerts_map": {1: ["Spread acima do limite"]},
            "segments": {
                "carteira": [opp],
                "alavancagem": [{**opp, "ticker": "PETRA998", "Status_Moneyness": "ATM"}],
                "aposta": [{**opp, "ticker": "PETRA997", "Status_Moneyness": "OTM"}],
            },
            "ranking_options_pnl": {
                "has_rows": True,
                "closed_count": 1,
                "open_count": 1,
                "open_cost": 233.0,
                "closed_entry_cost": 195.0,
                "realized": 1003.4,
                "profit": 1003.4,
                "loss": 0.0,
                "win_rate_pct": 100.0,
                "by_type": {
                    "CALL": {
                        "closed_count": 1,
                        "open_count": 1,
                        "open_cost": 233.0,
                        "realized": 1003.4,
                        "profit": 1003.4,
                        "loss": 0.0,
                    },
                    "PUT": {
                        "closed_count": 0,
                        "open_count": 0,
                        "open_cost": 0.0,
                        "realized": 0.0,
                        "profit": 0.0,
                        "loss": 0.0,
                    },
                },
                "closed_rows": [
                    {
                        "id": 6,
                        "ticker": "PETRA456",
                        "underlying": "PETR4",
                        "option_type": "CALL",
                        "trade_date": "2025-11-19",
                        "qty": 100,
                        "entry_price": 1.95,
                        "entry_cost": 195.0,
                        "status": "closed",
                        "exit_date": "2026-03-30",
                        "exit_price": 12.0,
                        "exit_reason": "venda_encerramento",
                        "realized": 1003.4,
                        "result_class": "profit",
                    }
                ],
                "open_rows": [
                    {
                        "id": 5,
                        "ticker": "ITUBE542",
                        "underlying": "ITUB4",
                        "option_type": "CALL",
                        "trade_date": "2025-11-19",
                        "qty": 100,
                        "entry_price": 2.33,
                        "entry_cost": 233.0,
                        "status": "open",
                        "exit_date": "",
                        "exit_price": None,
                        "exit_reason": "",
                        "realized": 0.0,
                        "result_class": "flat",
                    }
                ],
            },
        },
    )
    app = create_app()
    app.testing = True
    client = app.test_client()

    shell = client.get("/")
    assert shell.status_code == 200
    shell_html = shell.get_data(as_text=True)
    assert 'id="ranking-dashboard"' in shell_html
    assert 'hx-get="/partial/ranking?' in shell_html

    response = client.get("/partial/ranking")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Top oportunidades" in html
    assert "Lucros e prejuízos - opções compradas" in html
    assert "PETRA456" in html
    assert "Top Apostas Racionais" in html
    assert "Top Loterias" in html
    assert "Watchlist (sem book" in html
    assert "Oportunidades recorrentes" in html
    assert "Segmentos por perfil" in html
    assert "Posições abertas real" in html
    assert "Spread acima do limite" in html


def test_strategy_contract_covered_call_preserves_core_blocks(monkeypatch) -> None:
    _disable_strategy_caches(monkeypatch)
    monkeypatch.setattr(
        "opcoes.web._build_covered_call_shell_page_context",
        lambda **_kwargs: {
            "underlying": "PETR4",
            "filters": {
                "min_extrinsic": "0.5",
                "min_days": "2",
                "max_days": "90",
                "min_dist_strike": "2.0",
                "target_upside_pct": "12.0",
                "only_target_hits": True,
            },
            "holding_notice": "",
            "holding_error": "",
            "stock_real": {
                "shares_total": 100,
                "shares_covered": 100,
                "shares_free": 0,
                "free_avg_price": 31.90,
            },
            "stock_sim": {
                "shares_total": 0,
                "shares_covered": 0,
                "shares_free": 0,
                "free_avg_price": None,
            },
            "underlying_quick_filter": [
                {"ticker": "PETR4", "qty_total": 100, "has_open_calls": True}
            ],
            "monthly_premiums": [{"month": "2026-04", "total": 523.85}],
            "monthly_operational_result": [{"month": "2026-04", "total": 523.85}],
            "simulated_monthly_premiums": [],
            "simulated_monthly_operational_result": [],
        },
    )
    app = create_app()
    app.testing = True
    client = app.test_client()

    response = client.get("/covered-call?underlying=PETR4")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Cadastro do estoque consolidado" in html
    assert "Prêmios líquidos (Real)" in html
    assert "Resultado líquido (Real)" in html
    assert 'id="covered-call-live"' in html
    assert 'id="covered-call-audit"' in html
    assert "Aberta" in html


def test_strategy_contract_cash_put_preserves_core_blocks(monkeypatch) -> None:
    _disable_strategy_caches(monkeypatch)
    monkeypatch.setattr(
        "opcoes.web.get_cash_covered_put_context",
        lambda _args: {
            "underlying": "BBAS3",
            "filters": {
                "min_yield_pct": 1.5,
                "min_buffer_pct": 5.0,
                "min_days": 7,
                "max_days": 90,
                "limit": 50,
                "contract_size": 100,
                "buyback_target_pct": 70.0,
            },
            "cash_mode": "real",
            "latest_assignment_summary": None,
            "finance": {
                "available_cash": 10000.0,
                "total_cash": 12000.0,
                "collateral_locked": 2000.0,
                "max_lots": 2,
            },
            "finance_breakdown": {
                "real": {
                    "available_cash": 10000.0,
                    "total_cash": 12000.0,
                    "collateral_locked": 2000.0,
                },
                "simulated": {
                    "available_cash": 0.0,
                    "total_cash": 0.0,
                    "collateral_locked": 0.0,
                },
            },
            "monthly_premiums": [{"month": "2026-04", "total": 184.22}],
            "simulated_monthly_premiums": [],
            "underlying_quote": {"price": 23.39, "price_date": "2026-04-21"},
            "recent_transactions": [],
            "buyback_candidates_real": ["BBASP226"],
            "buyback_candidates_simulated": [],
            "puts_real": [
                {
                    "id": 1,
                    "ticker": "BBASP226",
                    "vencimento": "15/05/2026",
                    "dias_uteis": 16,
                    "open_qty": 400,
                    "strike": 22.27,
                    "entry_price": 0.20,
                    "collateral_yield_pct": 0.90,
                    "last_price": 0.12,
                    "buyback_profit_per_share": 0.08,
                    "buyback_profit_pct": 40.0,
                    "buyback_target_hit": True,
                    "pl": 32.0,
                    "pl_pct": 40.0,
                    "stock_breakeven": 22.07,
                    "dist_be_pct": 5.6,
                    "projected_outcome": 80.0,
                }
            ],
            "puts_simulated": [],
            "suggestions": [
                {
                    "ticker": "BBASQ237",
                    "vencimento": "15/05/2026",
                    "dias_uteis": 16,
                    "strike": 22.0,
                    "premium_total": 200.0,
                    "yield_pct": 1.8,
                    "buffer_pct": 6.0,
                    "capital_required": 2200.0,
                    "premium_source": "best_bid",
                    "annualized_yield_pct": 18.0,
                    "underlying_price": 23.39,
                    "breakeven_price": 21.60,
                    "breakeven_buffer_pct": 7.6,
                    "best_bid": 0.40,
                    "best_ask": 0.42,
                    "iv_rank_180d": 65.0,
                    "vol_impl_perc": 31.0,
                }
            ],
            "open_put_quick_filter": [
                {"ticker": "BBAS3", "qty_total": 400, "has_open_puts": True}
            ],
        },
    )
    app = create_app()
    app.testing = True
    client = app.test_client()

    response = client.get("/cash-covered-put?underlying=BBAS3")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Caixa Disponível" in html
    assert "Minhas Puts Vendidas (Real)" in html
    assert "Top da lista (Melhor Oportunidade)" in html
    assert "Puts elegíveis" in html
    assert "Filtro rápido" in html
    assert "Aberta" in html


def test_strategy_contract_fundamentus_preserves_core_blocks(monkeypatch) -> None:
    _disable_strategy_caches(monkeypatch)
    monkeypatch.setattr(
        "opcoes.web._build_fundamentus_shell_page_context",
        lambda **_kwargs: {
            "snapshot_date": "2026-04-21",
            "limit": 100,
            "status_filter": "approved",
            "ranking_window_days": 30,
        },
    )
    monkeypatch.setattr(
        "opcoes.web.get_fundamentus_context",
        lambda _args: {
            "message": "ok",
            "snapshot_date": "2026-04-21",
            "snapshot_lag_days": 0,
            "put_snapshot_date": "2026-04-21",
            "filter_run": None,
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

    shell = client.get("/fundamentus")
    assert shell.status_code == 200
    shell_html = shell.get_data(as_text=True)
    assert 'id="fundamentus-dashboard"' in shell_html
    assert 'hx-get="/fundamentus/partial/dashboard?' in shell_html

    response = client.get("/fundamentus/partial/dashboard")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Mudancas na lista de aprovadas" in html
    assert "Ranking historico (aprovadas)" in html
    assert "Oportunidades de PUTs" in html
    assert "Divisao por setor" in html
    assert "PETR4" in html


def test_strategy_contract_positions_preserves_core_blocks(monkeypatch) -> None:
    _disable_strategy_caches(monkeypatch)
    monkeypatch.setattr(
        "opcoes.web._build_positions_page_context",
        lambda **_kwargs: _sample_positions_context(),
    )
    app = create_app()
    app.testing = True
    client = app.test_client()

    response = client.get("/positions")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Estoque consolidado por ativo" in html
    assert "Resultados realizados" in html
    assert "Monitor por snapshot das posições" in html
    assert "Tabela editável de posições" in html
    assert 'action="/positions/update/7"' in html


def test_strategy_contract_darf_preserves_core_blocks(monkeypatch) -> None:
    monkeypatch.setattr(
        "opcoes.web.darf.get_monthly_darf_provisions",
        lambda **_kwargs: {"2026-03": 15.0},
    )
    monkeypatch.setattr("opcoes.web.darf.list_months", lambda **_kwargs: [])
    monkeypatch.setattr(
        "opcoes.web.list_monthly_tax_summaries",
        lambda **_kwargs: [
            TaxSummary(
                year=2026,
                month=3,
                swing_net=100.0,
                daytrade_net=0.0,
                swing_ir=15.0,
                daytrade_ir=0.0,
                swing_irrf=0.0,
                daytrade_irrf=0.0,
                swing_taxable=100.0,
                daytrade_taxable=0.0,
                total_ir=15.0,
                total_irrf=0.0,
                net_ir_due=15.0,
            )
        ],
    )
    monkeypatch.setattr(
        "opcoes.web.compute_tax",
        lambda **_kwargs: TaxSummary(
            year=2026,
            month=3,
            swing_net=100.0,
            daytrade_net=0.0,
            swing_ir=15.0,
            daytrade_ir=0.0,
            swing_irrf=0.0,
            daytrade_irrf=0.0,
            swing_taxable=100.0,
            daytrade_taxable=0.0,
            total_ir=15.0,
            total_irrf=0.0,
            net_ir_due=15.0,
        ),
    )
    monkeypatch.setattr("opcoes.web.list_tax_events_for_period", lambda **_kwargs: [])
    monkeypatch.setattr("opcoes.web.darf.get_month", lambda **_kwargs: None)
    monkeypatch.setattr("opcoes.web.darf.list_provision_entries", lambda **_kwargs: [])
    monkeypatch.setattr("opcoes.web.darf.last_business_day_next_month", lambda _period: "2026-04-30")

    app = create_app()
    app.testing = True
    client = app.test_client()

    response = client.get("/darf?period=2026-03")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Competencia" in html
    assert "DARF liquida" in html
    assert "Apuracao fiscal - 2026-03" in html
    assert "DARF gerada - 2026-03" in html
    assert "Provisao no ledger" in html


def test_strategy_contract_audit_preserves_core_blocks(monkeypatch) -> None:
    monkeypatch.setattr(
        "opcoes.web.list_positions",
        lambda **_kwargs: [
            {
                "id": 1,
                "ticker": "PETR4",
                "underlying": "PETR4",
                "side": "long",
                "status": "open",
                "qty": 100,
                "entry_price": 31.90,
                "fees": 0.0,
                "trade_type": "stock",
                "partial_qty": 0,
                "exit_price": None,
                "exit_reason": None,
                "is_simulated": False,
                "parent_position_id": None,
            },
            {
                "id": 2,
                "ticker": "PETRE500",
                "underlying": "PETR4",
                "side": "short",
                "status": "closed",
                "qty": 100,
                "entry_price": 1.06,
                "fees": 0.14,
                "trade_type": "swing",
                "partial_qty": 0,
                "exit_price": 0.0,
                "exit_reason": "vencimento_sem_valor",
                "is_simulated": False,
                "parent_position_id": None,
            },
        ],
    )
    monkeypatch.setattr(
        "opcoes.web._build_inventory_overview_global",
        lambda _positions: [
            {
                "ticker": "PETR4",
                "is_simulated": False,
                "shares_total": 100,
                "shares_reserved": 0,
                "shares_free": 100,
                "avg_price": 31.90,
                "coverage_status": "ok",
                "price_status": "ok",
            }
        ],
    )
    monkeypatch.setattr(
        "opcoes.web.finance.get_ledger_sums_by_position",
        lambda **_kwargs: {
            2: {
                "PREMIUM": 105.86,
                "DARF": -15.88,
                "REALIZED": 89.98,
            }
        },
    )
    monkeypatch.setattr("opcoes.web.list_holding_events", lambda **_kwargs: [])

    app = create_app()
    app.testing = True
    client = app.test_client()

    response = client.get("/audit?mode=real&include_closed=1")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Auditoria Caixa x Posições" in html
    assert "Estoque consolidado por ativo" in html
    assert "Líquido fiscal (Prêmio + DARF)" in html
    assert "Compra de opção (Ranking)" in html
    assert "Venda por exercicio de CALL" in html
    assert "Resultado realizado (nao caixa)" in html
