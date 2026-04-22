import pytest

from opcoes import web
from opcoes.ranking_page_cache import invalidate_namespace

pytestmark = pytest.mark.requires_postgres


def test_covered_call_route_uses_persisted_cache_across_app_instances(monkeypatch) -> None:
    invalidate_namespace("global")
    monkeypatch.setenv("OPCOES_STRATEGY_PAGE_CACHE_SECONDS", "60")

    calls = {"count": 0}

    def _fake_ctx(**_kwargs):
        calls["count"] += 1
        return {"value": calls["count"]}

    monkeypatch.setattr(web, "_build_covered_call_shell_page_context", _fake_ctx)
    monkeypatch.setattr(web, "render_template", lambda _tpl, **ctx: f"v={ctx['value']}")

    app_one = web.create_app()
    app_one.testing = True
    client_one = app_one.test_client()

    first = client_one.get("/covered-call")
    assert first.status_code == 200
    assert first.data.decode() == "v=1"
    assert calls["count"] == 1

    app_two = web.create_app()
    app_two.testing = True
    client_two = app_two.test_client()

    second = client_two.get("/covered-call")
    assert second.status_code == 200
    assert second.data.decode() == "v=1"
    assert calls["count"] == 1


def test_covered_call_route_bypasses_cache_when_notice_is_present(monkeypatch) -> None:
    invalidate_namespace("global")
    monkeypatch.setenv("OPCOES_STRATEGY_PAGE_CACHE_SECONDS", "60")

    calls = {"count": 0}

    def _fake_ctx(**_kwargs):
        calls["count"] += 1
        return {"value": calls["count"]}

    monkeypatch.setattr(web, "_build_covered_call_shell_page_context", _fake_ctx)
    monkeypatch.setattr(web, "render_template", lambda _tpl, **ctx: f"v={ctx['value']}")

    app = web.create_app()
    app.testing = True
    client = app.test_client()

    first = client.get("/covered-call")
    second = client.get("/covered-call?holding_notice=ok")

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.data.decode() == "v=1"
    assert second.data.decode() == "v=2"
    assert calls["count"] == 2


def test_cash_put_route_uses_persisted_cache_across_app_instances(monkeypatch) -> None:
    invalidate_namespace("global")
    monkeypatch.setenv("OPCOES_STRATEGY_PAGE_CACHE_SECONDS", "60")

    calls = {"count": 0}

    def _fake_ctx(_args):
        calls["count"] += 1
        return {"value": calls["count"]}

    monkeypatch.setattr(web, "get_cash_covered_put_context", _fake_ctx)
    monkeypatch.setattr(web, "render_template", lambda _tpl, **ctx: f"v={ctx['value']}")

    app_one = web.create_app()
    app_one.testing = True
    client_one = app_one.test_client()

    first = client_one.get("/cash-covered-put")
    assert first.status_code == 200
    assert first.data.decode() == "v=1"
    assert calls["count"] == 1

    app_two = web.create_app()
    app_two.testing = True
    client_two = app_two.test_client()

    second = client_two.get("/cash-covered-put")
    assert second.status_code == 200
    assert second.data.decode() == "v=1"
    assert calls["count"] == 1


def test_positions_route_uses_persisted_cache_across_app_instances(monkeypatch) -> None:
    invalidate_namespace("global")
    monkeypatch.setenv("OPCOES_STRATEGY_PAGE_CACHE_SECONDS", "60")

    calls = {"count": 0}

    def _fake_ctx(**_kwargs):
        calls["count"] += 1
        return {"value": calls["count"]}

    monkeypatch.setattr(web, "_build_positions_page_context", _fake_ctx)
    monkeypatch.setattr(web, "render_template", lambda _tpl, **ctx: f"v={ctx['value']}")

    app_one = web.create_app()
    app_one.testing = True
    client_one = app_one.test_client()

    first = client_one.get("/positions")
    assert first.status_code == 200
    assert first.data.decode() == "v=1"
    assert calls["count"] == 1

    app_two = web.create_app()
    app_two.testing = True
    client_two = app_two.test_client()

    second = client_two.get("/positions")
    assert second.status_code == 200
    assert second.data.decode() == "v=1"
    assert calls["count"] == 1


def test_fundamentus_route_uses_persisted_cache_across_app_instances(monkeypatch) -> None:
    invalidate_namespace("global")
    monkeypatch.setenv("OPCOES_STRATEGY_PAGE_CACHE_SECONDS", "60")

    calls = {"count": 0}

    def _fake_ctx(**_kwargs):
        calls["count"] += 1
        return {"value": calls["count"]}

    monkeypatch.setattr(web, "_build_fundamentus_shell_page_context", _fake_ctx)
    monkeypatch.setattr(web, "render_template", lambda _tpl, **ctx: f"v={ctx['value']}")

    app_one = web.create_app()
    app_one.testing = True
    client_one = app_one.test_client()

    first = client_one.get("/fundamentus")
    assert first.status_code == 200
    assert first.data.decode() == "v=1"
    assert calls["count"] == 1

    app_two = web.create_app()
    app_two.testing = True
    client_two = app_two.test_client()

    second = client_two.get("/fundamentus")
    assert second.status_code == 200
    assert second.data.decode() == "v=1"
    assert calls["count"] == 1


def test_index_route_uses_shell_cache_across_app_instances(monkeypatch) -> None:
    invalidate_namespace("global")
    monkeypatch.setenv("OPCOES_RANKING_CACHE_SECONDS", "60")

    calls = {"count": 0}

    def _fake_ctx(**_kwargs):
        calls["count"] += 1
        return {"value": calls["count"]}

    monkeypatch.setattr(web, "_build_ranking_shell_page_context", _fake_ctx)
    monkeypatch.setattr(web, "render_template", lambda _tpl, **ctx: f"v={ctx['value']}")

    app_one = web.create_app()
    app_one.testing = True
    client_one = app_one.test_client()

    first = client_one.get("/")
    assert first.status_code == 200
    assert first.data.decode() == "v=1"
    assert calls["count"] == 1

    app_two = web.create_app()
    app_two.testing = True
    client_two = app_two.test_client()

    second = client_two.get("/")
    assert second.status_code == 200
    assert second.data.decode() == "v=1"
    assert calls["count"] == 1


def test_covered_call_cache_is_invalidated_after_holdings_upsert(monkeypatch) -> None:
    invalidate_namespace("global")
    monkeypatch.setenv("OPCOES_STRATEGY_PAGE_CACHE_SECONDS", "60")
    monkeypatch.setenv("OPCOES_SECRET_KEY", "teste-seguro")

    calls = {"count": 0}

    def _fake_ctx(**_kwargs):
        calls["count"] += 1
        return {
            "value": calls["count"],
            "underlying": "PETR4",
            "filters": {
                "min_extrinsic": 0,
                "min_days": 0,
                "max_days": 30,
                "min_dist_strike": 0,
                "target_upside_pct": 12.0,
                "only_target_hits": False,
            },
            "holding_notice": "",
            "holding_error": "",
            "stock_real": {"shares_total": 100, "shares_covered": 0, "shares_free": 100, "free_avg_price": 10.0},
            "stock_sim": {"shares_total": 0, "shares_covered": 0, "shares_free": 0, "free_avg_price": None},
            "underlying_quick_filter": [],
        }

    monkeypatch.setattr(web, "_build_covered_call_shell_page_context", _fake_ctx)
    monkeypatch.setattr(
        web,
        "upsert_holding",
        lambda **_kwargs: {"shares_total": 200, "avg_price": 11.0},
    )
    monkeypatch.setattr(web, "render_template", lambda _tpl, **ctx: f"v={ctx['value']}")

    app = web.create_app()
    app.testing = True
    client = app.test_client()

    first = client.get("/covered-call")
    assert first.status_code == 200
    assert first.data.decode() == "v=1"

    response = client.post(
        "/holdings/upsert",
        data={
            "underlying": "PETR4",
            "quantity": "200",
            "avg_price": "11.0",
            "is_simulated": "0",
        },
    )
    assert response.status_code == 302

    second = client.get("/covered-call")
    assert second.status_code == 200
    assert second.data.decode() == "v=2"
    assert calls["count"] == 2
