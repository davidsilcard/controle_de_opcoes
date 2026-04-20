from __future__ import annotations

from opcoes.strategies.covered_call import get_covered_call_context
from opcoes.web import create_app


class FakeMarketClient:
    def __init__(self, payload: dict[str, dict]) -> None:
        self.payload = payload

    def fetch_quotes(self, _symbols) -> dict[str, dict]:
        return dict(self.payload)


def test_covered_call_context_prefers_live_market_data(monkeypatch) -> None:
    monkeypatch.setattr(
        "opcoes.strategies.covered_call.list_positions",
        lambda include_closed=False: [
            {
                "id": 1,
                "ticker": "PETRD999",
                "underlying": "PETR4",
                "trade_date": "2026-04-14",
                "qty": 100,
                "open_qty": 100,
                "entry_price": 0.2,
                "last_price": 0.05,
                "underlying_price": 47.0,
                "status": "open",
                "side": "short",
                "trade_type": "swing",
                "strategy_tag": "covered_call",
                "is_simulated": 0,
                "fees": 1.0,
                "realized_pl": None,
                "dias_uteis": 3,
                "vencimento": "17/04/2026",
                "strike": 49.0,
                "pct_2x": None,
                "extrinsic_pct_spot": None,
            },
            {
                "id": 2,
                "ticker": "PETR4",
                "underlying": "PETR4",
                "trade_date": "2026-04-01",
                "qty": 100,
                "open_qty": 100,
                "entry_price": 45.0,
                "status": "open",
                "side": "long",
                "trade_type": "stock",
                "strategy_tag": "estoque",
                "is_simulated": 0,
                "fees": 0.0,
                "realized_pl": None,
                "last_price": 47.0,
            },
        ],
    )
    monkeypatch.setattr(
        "opcoes.strategies.covered_call.list_holding_snapshots",
        lambda **_kwargs: [],
    )
    monkeypatch.setattr(
        "opcoes.strategies.covered_call.fetch_latest_underlying_options",
        lambda underlying: [
            {
                "ticker": "PETRD999",
                "underlying": underlying,
                "option_type": "CALL",
                "vencimento": "17/04/2026",
                "dias_uteis": 3,
                "strike": 49.0,
                "underlying_price": 47.0,
                "dist_perc_strike": 4.25,
                "ultimo": 0.09,
                "best_bid": 0.08,
                "pct_2x": 5.0,
                "score_total": 1.2,
                "extrinsic_pct_spot": 0.1,
            }
        ],
    )
    monkeypatch.setattr(
        "opcoes.strategies.covered_call.fetch_latest_underlying_quote",
        lambda underlying: {"underlying": underlying, "price": 47.0, "price_date": "2026-04-14"},
    )
    monkeypatch.setattr(
        "opcoes.strategies.covered_call.get_covered_call_settings",
        lambda: type(
            "Settings",
            (),
            {
                "underlying": "PETR4",
                "min_extrinsic": 0.0,
                "min_days": 1,
                "max_days": 30,
                "min_dist_strike": 0.0,
                "buyback_target_pct": 70.0,
                "only_target_hits": False,
            },
        )(),
    )
    monkeypatch.setattr(
        "opcoes.strategies.covered_call.finance.get_monthly_premiums",
        lambda **_kwargs: [],
    )
    monkeypatch.setattr(
        "opcoes.strategies.covered_call.update_covered_call_settings",
        lambda **_kwargs: None,
    )

    client = FakeMarketClient(
        {
            "PETR4": {
                "symbol": "PETR4",
                "ok": True,
                "last": 48.9,
                "time_utc": "2026-04-14T13:00:00Z",
                "market_status": "live",
                "stale_seconds": 1,
            },
            "PETRD999": {
                "symbol": "PETRD999",
                "ok": True,
                "bid": 0.1,
                "ask": 0.12,
                "last": 0.11,
                "time_utc": "2026-04-14T13:00:00Z",
                "market_status": "live",
                "stale_seconds": 1,
            },
        }
    )

    ctx = get_covered_call_context({"underlying": "PETR4"}, market_data_client=client)

    assert ctx["underlying_quote"]["price"] == 48.9
    assert ctx["underlying_quote"]["market_status_label"] == "Ao vivo"
    assert ctx["covered_real"][0]["last_price"] == 0.12
    assert ctx["covered_real"][0]["market_price_source"] == "ask"
    assert ctx["covered_real"][0]["market_source_label"] == "Ask"
    assert ctx["covered_real"][0]["underlying_price"] == 48.9
    assert ctx["suggestions"][0]["premium_ref"] == 0.1
    assert ctx["suggestions"][0]["market_status_label"] == "Ao vivo"
    assert ctx["underlying_quote"]["market_time_display"] == "14/04 10:00:00"


def test_covered_call_context_marks_snapshot_fallbacks(monkeypatch) -> None:
    monkeypatch.setattr(
        "opcoes.strategies.covered_call.list_positions",
        lambda include_closed=False: [
            {
                "id": 1,
                "ticker": "GGBRD221",
                "underlying": "GGBR4",
                "trade_date": "2026-04-08",
                "qty": 800,
                "open_qty": 800,
                "entry_price": 0.05,
                "last_price": 0.1,
                "underlying_price": 21.6,
                "last_snapshot_date": "2026-04-15",
                "status": "open",
                "side": "short",
                "trade_type": "swing",
                "strategy_tag": "covered_call",
                "is_simulated": 0,
                "fees": 0.04,
                "realized_pl": None,
                "dias_uteis": 2,
                "vencimento": "17/04/2026",
                "strike": 22.03,
                "pct_2x": 1.0,
                "extrinsic_pct_spot": 0.46,
            }
        ],
    )
    monkeypatch.setattr(
        "opcoes.strategies.covered_call.list_holding_snapshots",
        lambda **_kwargs: [],
    )
    monkeypatch.setattr(
        "opcoes.strategies.covered_call.fetch_latest_underlying_options",
        lambda underlying: [
            {
                "snapshot_date": "2026-04-15",
                "ticker": "GGBRD261",
                "underlying": underlying,
                "option_type": "CALL",
                "vencimento": "17/04/2026",
                "dias_uteis": 2,
                "strike": 26.03,
                "underlying_price": 21.6,
                "underlying_price_date": "2026-04-15",
                "dist_perc_strike": 20.51,
                "ultimo": 0.15,
                "best_bid": 0.14,
                "pct_2x": 1.0,
                "score_total": 1.2,
                "extrinsic_pct_spot": 0.69,
            }
        ],
    )
    monkeypatch.setattr(
        "opcoes.strategies.covered_call.fetch_latest_underlying_quote",
        lambda underlying: {
            "snapshot_date": "2026-04-15",
            "underlying": underlying,
            "price": 21.6,
            "price_date": "2026-04-15",
        },
    )
    monkeypatch.setattr(
        "opcoes.strategies.covered_call.get_covered_call_settings",
        lambda: type(
            "Settings",
            (),
            {
                "underlying": "GGBR4",
                "min_extrinsic": 0.0,
                "min_days": 1,
                "max_days": 30,
                "min_dist_strike": 0.0,
                "buyback_target_pct": 50.0,
                "only_target_hits": False,
            },
        )(),
    )
    monkeypatch.setattr(
        "opcoes.strategies.covered_call.finance.get_monthly_premiums",
        lambda **_kwargs: [],
    )
    monkeypatch.setattr(
        "opcoes.strategies.covered_call.update_covered_call_settings",
        lambda **_kwargs: None,
    )

    ctx = get_covered_call_context({"underlying": "GGBR4"}, market_data_client=FakeMarketClient({}))

    assert ctx["underlying_quote"]["market_status_label"] == "Snapshot"
    assert ctx["underlying_quote"]["market_source_label"] == "Snapshot"
    assert ctx["covered_real"][0]["market_status_label"] == "Snapshot"
    assert ctx["covered_real"][0]["underlying_market_status_label"] == "Snapshot"
    assert ctx["covered_real"][0]["underlying_market_time_display"] == "15/04/2026"


def test_covered_call_route_renders_htmx_live_block(monkeypatch) -> None:
    monkeypatch.setattr(
        "opcoes.web._build_covered_call_page_context",
        lambda **_kwargs: {
            "underlying": "PETR4",
            "filters": {
                "min_extrinsic": "0.0",
                "min_days": "1",
                "max_days": "30",
                "min_dist_strike": "0.0",
                "target_upside_pct": "0.0",
                "only_target_hits": False,
            },
            "holding_notice": "",
            "holding_error": "",
            "stock_real": {
                "shares_total": 100,
                "shares_covered": 100,
                "shares_free": 0,
                "free_avg_price": 45.0,
                "free_min_price": 45.0,
                "free_max_price": 45.0,
            },
            "stock_sim": {
                "shares_total": 0,
                "shares_covered": 0,
                "shares_free": 0,
                "free_avg_price": None,
                "free_min_price": None,
                "free_max_price": None,
            },
            "inventory_summary": [],
            "underlying_quote": {"price": 48.9, "price_date": "2026-04-14", "market_status_label": "Ao vivo", "market_price_source": "last"},
            "covered_real": [
                {
                    "id": 1,
                    "ticker": "PETRD999",
                    "vencimento": "17/04/2026",
                    "dias_uteis": 2,
                    "open_qty": 100,
                    "last_price": 0.1,
                    "market_status_label": "Snapshot",
                    "market_source_label": "Snapshot",
                    "market_time_display": "15/04/2026",
                    "buyback_profit_per_share": -0.05,
                    "buyback_profit_pct": -100.0,
                    "buyback_target_hit": False,
                    "underlying_price": 48.9,
                    "underlying_market_status_label": "Snapshot",
                    "underlying_market_time_display": "15/04/2026",
                    "extrinsic_pct_spot": 0.46,
                    "pct_2x": 1.0,
                    "pl": -40.04,
                    "pl_pct": -100.10,
                    "strike": 49.0,
                }
            ],
            "covered_sim": [],
            "suggestions": [],
            "buyback_target_pct": 70.0,
            "lots_real": [],
            "lots_sim": [],
            "call_summary_real": [],
            "call_summary_sim": [],
            "monthly_premiums": [],
            "monthly_operational_result": [],
            "simulated_monthly_premiums": [],
            "simulated_monthly_operational_result": [],
            "buyback_candidates_real": [],
            "buyback_candidates_simulated": [],
            "sell_target": {"base_price": None, "target_price": None},
            "underlying_quick_filter": [],
        },
    )

    app = create_app()
    app.testing = True
    client = app.test_client()

    response = client.get("/covered-call?underlying=PETR4")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'id="covered-call-live"' in html
    assert 'hx-get="/covered-call/partial/live?' in html
    assert "Cadastro do estoque consolidado" in html
    assert 'action="/holdings/upsert"' in html
    assert "Auditoria e detalhes operacionais" in html
    assert html.count("Painel ao vivo de covered call") == 1
    assert html.count("Calls de PETR4 em aberto (real)") == 2
    assert html.count("Sugestões de novas calls para PETR4") == 1
    assert "Recompra" in html
    assert "Atenção operacional" in html
    assert "<details class=\"card border-0 shadow-sm cc-audit-details\" open>" in html
    assert "15/04/2026" in html


def test_covered_call_partial_live_renders_quote_and_suggestions(monkeypatch) -> None:
    monkeypatch.setattr(
        "opcoes.web._build_covered_call_page_context",
        lambda **_kwargs: {
            "underlying": "PETR4",
            "filters": {
                "min_extrinsic": "0.0",
                "min_days": "1",
                "max_days": "30",
                "min_dist_strike": "0.0",
                "target_upside_pct": "0.0",
                "only_target_hits": False,
            },
            "holding_notice": "",
            "holding_error": "",
            "stock_real": {
                "shares_total": 100,
                "shares_covered": 100,
                "shares_free": 0,
                "free_avg_price": 45.0,
                "free_min_price": 45.0,
                "free_max_price": 45.0,
            },
            "stock_sim": {
                "shares_total": 0,
                "shares_covered": 0,
                "shares_free": 0,
                "free_avg_price": None,
                "free_min_price": None,
                "free_max_price": None,
            },
            "inventory_summary": [
                {
                    "ticker": "PETR4",
                    "is_simulated": False,
                    "shares_total": 100,
                    "shares_reserved": 100,
                    "shares_free": 0,
                    "avg_price": 45.0,
                    "coverage_status": "ok",
                    "price_status": "ok",
                }
            ],
                "underlying_quote": {
                    "price": 48.9,
                    "price_date": "2026-04-14",
                    "market_status_label": "Ao vivo",
                    "market_source_label": "Ultimo",
                    "market_time_display": "14/04 10:00:00",
                },
            "covered_real": [],
            "covered_sim": [],
            "suggestions": [
                {
                    "ticker": "PETRD999",
                    "vencimento": "17/04/2026",
                    "strike": 49.0,
                    "underlying_price": 48.9,
                    "underlying_market_status_label": "Ao vivo",
                    "dist_perc_strike": 0.2,
                    "extrinsic_pct_spot": 0.1,
                    "premium_ref": 0.12,
                    "market_status_label": "Ao vivo",
                    "market_source_label": "Bid",
                    "target_hit": True,
                    "strike_target_hit": True,
                }
            ],
            "buyback_target_pct": 70.0,
            "lots_real": [],
            "lots_sim": [],
            "call_summary_real": [],
            "call_summary_sim": [],
            "monthly_premiums": [],
            "monthly_operational_result": [],
            "simulated_monthly_premiums": [],
            "simulated_monthly_operational_result": [],
            "buyback_candidates_real": [],
            "buyback_candidates_simulated": [],
            "sell_target": {"base_price": None, "target_price": None},
            "underlying_quick_filter": [],
        },
    )

    app = create_app()
    app.testing = True
    client = app.test_client()

    response = client.get("/covered-call/partial/live?underlying=PETR4")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Painel ao vivo de covered call" in html
    assert "Resumo didático da cobertura atual" in html
    assert "Cotação PETR4" in html
    assert "PETRD999" in html
    assert "Cadastro do estoque consolidado" not in html
    assert "Auditoria e detalhes operacionais" not in html
    assert "Recompra" not in html
    assert "Atualizado em" in html
    assert 'data-local-datetime="2026-04-14"' in html
    assert "14/04 10:00:00" in html
    assert "(America/Sao_Paulo)" in html
    assert "Timestamp bruto do provider" in html
    assert "Ao vivo" in html


def test_covered_call_partial_live_does_not_persist_settings(monkeypatch) -> None:
    update_calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        "opcoes.strategies.covered_call.list_positions",
        lambda include_closed=False: [],
    )
    monkeypatch.setattr(
        "opcoes.strategies.covered_call.list_holding_snapshots",
        lambda **_kwargs: [],
    )
    monkeypatch.setattr(
        "opcoes.strategies.covered_call.fetch_latest_underlying_options",
        lambda underlying: [],
    )
    monkeypatch.setattr(
        "opcoes.strategies.covered_call.fetch_latest_underlying_quote",
        lambda underlying: {"underlying": underlying, "price": 47.0, "price_date": "2026-04-14"},
    )
    monkeypatch.setattr(
        "opcoes.strategies.covered_call.get_covered_call_settings",
        lambda: type(
            "Settings",
            (),
            {
                "underlying": "PETR4",
                "min_extrinsic": 0.0,
                "min_days": 1,
                "max_days": 30,
                "min_dist_strike": 0.0,
                "buyback_target_pct": 70.0,
                "only_target_hits": False,
            },
        )(),
    )
    monkeypatch.setattr(
        "opcoes.strategies.covered_call.finance.get_monthly_premiums",
        lambda **_kwargs: [],
    )
    monkeypatch.setattr(
        "opcoes.strategies.covered_call.update_covered_call_settings",
        lambda **kwargs: update_calls.append(kwargs),
    )
    monkeypatch.setattr("opcoes.web.list_positions", lambda include_closed=False: [])

    app = create_app()
    app.testing = True
    client = app.test_client()

    response = client.get("/covered-call/partial/live?underlying=PETR4&min_days=5")

    assert response.status_code == 200
    assert update_calls == []
