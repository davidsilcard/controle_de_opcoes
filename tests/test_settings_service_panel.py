from __future__ import annotations

import datetime as dt

from opcoes.settings import (
    CashCoveredPutSettings,
    CoveredCallSettings,
    FeeSettings,
    FundamentusSettings,
    StrategySettings,
)
from opcoes.web import create_app


def test_settings_page_shows_service_panel(monkeypatch) -> None:
    monkeypatch.setenv("OPCOES_SECRET_KEY", "teste-seguro")
    monkeypatch.setattr("opcoes.web.get_fee_settings", lambda: FeeSettings())
    monkeypatch.setattr("opcoes.web.get_strategy_settings", lambda: StrategySettings())
    monkeypatch.setattr("opcoes.web.get_fundamentus_settings", lambda: FundamentusSettings())
    monkeypatch.setattr("opcoes.web.get_covered_call_settings", lambda: CoveredCallSettings())
    monkeypatch.setattr("opcoes.web.get_cash_put_settings", lambda: CashCoveredPutSettings())
    monkeypatch.setattr(
        "opcoes.web.get_service_dashboard",
        lambda limit=12: {
            "services": [
                {
                    "key": "scrape_cycle",
                    "label": "Ciclo diario do scraper",
                    "description": "Executa scrape e rotinas diarias.",
                    "schedule_label": "Dias uteis as 03:00 (America/Sao_Paulo)",
                    "next_run_utc": dt.datetime(2026, 4, 2, 6, 0, tzinfo=dt.timezone.utc),
                    "next_run_local": dt.datetime(2026, 4, 2, 3, 0, tzinfo=dt.timezone.utc),
                    "last_run": {
                        "status": "success",
                        "monitor_status": "success",
                        "started_at": dt.datetime(2026, 4, 1, 6, 0, tzinfo=dt.timezone.utc),
                        "finished_at": dt.datetime(2026, 4, 1, 7, 30, tzinfo=dt.timezone.utc),
                        "duration_seconds": 5400,
                        "display_duration_seconds": 5400,
                        "summary": "Ciclo concluido",
                        "error_message": "",
                        "monitor_message": "",
                    },
                }
            ],
            "recent_runs": [
                {
                    "service_key": "scrape_cycle",
                    "status": "success",
                    "monitor_status": "success",
                    "started_at": dt.datetime(2026, 4, 1, 6, 0, tzinfo=dt.timezone.utc),
                    "finished_at": dt.datetime(2026, 4, 1, 7, 30, tzinfo=dt.timezone.utc),
                    "duration_seconds": 5400,
                    "display_duration_seconds": 5400,
                    "summary": "Ciclo concluido",
                    "error_message": "",
                    "monitor_message": "",
                }
            ],
        },
    )

    app = create_app()
    app.testing = True
    client = app.test_client()

    response = client.get("/settings")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Automacao e servicos" in html
    assert "Ciclo diario do scraper" in html
    assert "Execucoes recentes" in html
    assert "Ciclo concluido" in html


def test_settings_page_shows_possible_stall_warning(monkeypatch) -> None:
    monkeypatch.setenv("OPCOES_SECRET_KEY", "teste-seguro")
    monkeypatch.setattr("opcoes.web.get_fee_settings", lambda: FeeSettings())
    monkeypatch.setattr("opcoes.web.get_strategy_settings", lambda: StrategySettings())
    monkeypatch.setattr("opcoes.web.get_fundamentus_settings", lambda: FundamentusSettings())
    monkeypatch.setattr("opcoes.web.get_covered_call_settings", lambda: CoveredCallSettings())
    monkeypatch.setattr("opcoes.web.get_cash_put_settings", lambda: CashCoveredPutSettings())
    monkeypatch.setattr(
        "opcoes.web.get_service_dashboard",
        lambda limit=12: {
            "services": [
                {
                    "key": "scrape_cycle",
                    "label": "Ciclo diario do scraper",
                    "description": "Executa scrape e rotinas diarias.",
                    "schedule_label": "Dias uteis as 03:00 (America/Sao_Paulo)",
                    "next_run_utc": dt.datetime(2026, 4, 2, 6, 0, tzinfo=dt.timezone.utc),
                    "next_run_local": dt.datetime(2026, 4, 2, 3, 0, tzinfo=dt.timezone.utc),
                    "last_run": {
                        "status": "running",
                        "monitor_status": "stalled",
                        "started_at": dt.datetime(2026, 4, 1, 6, 0, tzinfo=dt.timezone.utc),
                        "finished_at": None,
                        "duration_seconds": None,
                        "display_duration_seconds": 18000,
                        "summary": "Ciclo diario iniciado.",
                        "error_message": "",
                        "monitor_message": "Execucao sem finalizacao ha 5h 00m, acima do limite esperado.",
                    },
                }
            ],
            "recent_runs": [
                {
                    "service_key": "scrape_cycle",
                    "status": "running",
                    "monitor_status": "stalled",
                    "started_at": dt.datetime(2026, 4, 1, 6, 0, tzinfo=dt.timezone.utc),
                    "finished_at": None,
                    "duration_seconds": None,
                    "display_duration_seconds": 18000,
                    "summary": "Ciclo diario iniciado.",
                    "error_message": "",
                    "monitor_message": "Execucao sem finalizacao ha 5h 00m, acima do limite esperado.",
                }
            ],
        },
    )

    app = create_app()
    app.testing = True
    client = app.test_client()

    response = client.get("/settings")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Possivel travamento" in html
    assert "Execucao sem finalizacao ha 5h 00m" in html
