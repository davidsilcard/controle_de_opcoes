from __future__ import annotations

from opcoes.tax import TaxSummary
from opcoes.web import create_app


def test_darf_route_renders_fiscal_context(monkeypatch) -> None:
    monkeypatch.setattr(
        "opcoes.web.darf.get_monthly_darf_provisions",
        lambda **_kwargs: {"2026-03": 15.0},
    )
    monkeypatch.setattr(
        "opcoes.web.darf.list_months",
        lambda **_kwargs: [],
    )
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
    monkeypatch.setattr(
        "opcoes.web.list_tax_events_for_period",
        lambda **_kwargs: [],
    )
    monkeypatch.setattr(
        "opcoes.web.darf.get_month",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        "opcoes.web.darf.list_provision_entries",
        lambda **_kwargs: [],
    )
    monkeypatch.setattr(
        "opcoes.web.darf.last_business_day_next_month",
        lambda _period: "2026-04-30",
    )

    app = create_app()
    app.testing = True
    client = app.test_client()

    response = client.get("/darf?period=2026-03")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "DARF liquida" in html
    assert "Apuracao fiscal - 2026-03" in html
    assert "Provisao no ledger" in html

