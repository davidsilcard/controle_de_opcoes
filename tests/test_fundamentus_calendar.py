import datetime as dt
from pathlib import Path

import pytest
from flask import Flask, render_template

from opcoes import market_calendar as calendar
from opcoes.strategies import fundamentus as strategy
from opcoes.settings import FundamentusSettings


@pytest.mark.parametrize(
    "instant, expected",
    [
        ("2026-10-05T10:00:00-03:00", "2026-10-16"),
        ("2026-10-16T15:44:59-03:00", "2026-10-16"),
        ("2026-10-16T15:45:00-03:00", "2026-11-19"),
        ("2026-10-17T10:00:00-03:00", "2026-11-19"),
        ("2026-11-01T10:00:00-03:00", "2026-11-19"),
        ("2026-11-19T15:45:00-03:00", "2026-12-18"),
        ("2026-12-18T15:45:00-03:00", "2027-01-15"),
        ("2026-10-16T18:44:59+00:00", "2026-10-16"),
        ("2026-10-16T18:45:00+00:00", "2026-11-19"),
        ("2027-12-17T15:45:00-03:00", None),
        ("2028-01-01T10:00:00-03:00", None),
        ("2026-03-01T10:00:00-03:00", None),
    ],
)
def test_next_monthly_expiry(instant, expected):
    result = calendar.next_monthly_expiry(dt.datetime.fromisoformat(instant))
    assert result == (dt.date.fromisoformat(expected) if expected else None)


def test_calendar_is_ordered_complete_and_does_not_guess():
    dates = calendar.MONTHLY_EXPIRIES
    assert tuple(sorted(set(dates))) == dates
    assert len({(date.year, date.month) for date in dates}) == len(dates) == 21
    assert dt.date(2026, 11, 20) not in dates
    with pytest.raises(ValueError, match="fuso"):
        calendar.next_monthly_expiry(dt.datetime(2026, 10, 5))


@pytest.fixture
def context_factory(monkeypatch):
    """Conexões e fontes externas substituídas; nenhuma gravação financeira."""
    monkeypatch.setattr(strategy, "latest_snapshot_date", lambda: "2026-09-01")

    def stock_rows(**kwargs):
        row = dict.fromkeys(
            "pl pvp psr div_yield p_ativo p_cap_giro p_ebit p_ativo_circ_liq "
            "ev_ebit ev_ebitda margem_ebit margem_liquida liquidez_corrente "
            "roic roe liquidez_2m patrimonio_liq div_bruta_patrim cresc_rec_5a".split()
        )
        row.update(papel="PETR4", cotacao=37.0)
        return [row]

    monkeypatch.setattr(strategy, "fetch_snapshot", stock_rows)
    monkeypatch.setattr(strategy, "fetch_signals", lambda **kwargs: [])
    monkeypatch.setattr(strategy, "fetch_filter_run", lambda **kwargs: None)
    monkeypatch.setattr(strategy, "get_snapshot_integrity", lambda **kwargs: None)
    monkeypatch.setattr(strategy, "_fetch_option_underlyings", lambda: {"PETR4"})
    monkeypatch.setattr(strategy, "_attach_sector_info", lambda rows: None)
    monkeypatch.setattr(
        strategy, "_fetch_underlying_prices", lambda *args: {"PETR4": 37.0}
    )
    monkeypatch.setattr(strategy, "get_fundamentus_settings", FundamentusSettings)
    monkeypatch.setattr(
        strategy,
        "fetch_approved_ranking",
        lambda **kwargs: {"rows": [], "start_date": None, "end_date": None},
    )

    def build(
        *,
        instant="2026-10-05T10:00:00-03:00",
        expiry="16/10/2026",
        premium="1,00",
        snapshot="2026-09-01",
    ):
        monkeypatch.setattr(
            strategy, "market_now", lambda: dt.datetime.fromisoformat(instant)
        )
        monkeypatch.setattr(strategy, "_latest_option_snapshot_date", lambda: snapshot)
        monkeypatch.setattr(
            strategy,
            "_fetch_put_rows",
            lambda *args: [
                {
                    "underlying": "PETR4",
                    "ticker": "PETRV36",
                    "vencimento": expiry,
                    "strike": "36,00",
                    "ultimo": premium,
                    "best_bid": premium,
                },
                {
                    "underlying": "PETR4",
                    "ticker": "SEMANAL",
                    "vencimento": "09/10/2026",
                    "strike": "36,00",
                    "ultimo": "2,00",
                    "best_bid": "2,00",
                },
            ],
        )
        return strategy.get_fundamentus_context({"status": "all"})

    return build


def _render(context):
    app = Flask(
        __name__,
        template_folder=str(Path(__file__).resolve().parents[1] / "opcoes/templates"),
    )
    with app.test_request_context():
        return render_template("partials/fundamentus_dashboard.html", **context)


def test_stale_snapshot_never_selects_month_and_weeklies_are_excluded(context_factory):
    context = context_factory()
    assert context["put_target_vencimento"] == "16/10/2026"
    assert context["put_contract_count"] == 1
    assert [row["contrato"] for row in context["put_opportunities"]] == ["PETRV36"]
    assert context["put_opportunities"][0]["dias_ate_vencimento"] == 11
    html = _render(context)
    assert "Oportunidades de PUTs" in html
    assert "34 dia(s) de defasagem" in html
    assert "15h45" in html


@pytest.mark.parametrize(
    "kwargs, message",
    [
        (
            {"expiry": "20/11/2026"},
            "Dados indisponíveis para o vencimento mensal 16/10/2026",
        ),
        ({"premium": "0,00"}, "Nenhuma oportunidade de PUT passou nos filtros"),
        ({"snapshot": None}, "nenhum snapshot disponível"),
        (
            {"instant": "2028-01-01T10:00:00-03:00"},
            "Calendário de vencimentos mensais indisponível",
        ),
    ],
)
def test_empty_states_are_distinct(context_factory, kwargs, message):
    assert message in _render(context_factory(**kwargs))


def test_november_holiday_is_used_in_real_context(context_factory):
    context = context_factory(instant="2026-10-17T10:00:00-03:00", expiry="19/11/2026")
    assert context["put_target_vencimento"] == "19/11/2026"
    assert context["put_contract_count"] == 1
    assert context["put_opportunities"]


def test_empty_stock_selection_still_explains_target(context_factory, monkeypatch):
    monkeypatch.setattr(strategy, "fetch_snapshot", lambda **kwargs: [])
    context = context_factory()
    assert "Nenhuma ação selecionada" in _render(context)
    assert "16/10/2026" in _render(context)


def test_missing_calendar_with_no_stocks_still_warns(context_factory, monkeypatch):
    monkeypatch.setattr(strategy, "fetch_snapshot", lambda **kwargs: [])
    context = context_factory(instant="2028-01-01T10:00:00-03:00")
    assert "Calendário de vencimentos mensais indisponível" in _render(context)
