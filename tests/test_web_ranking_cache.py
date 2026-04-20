import pytest

from opcoes import web
from opcoes.ranking_page_cache import invalidate_namespace

pytestmark = pytest.mark.requires_postgres


def test_index_uses_ranking_cache(monkeypatch) -> None:
    invalidate_namespace("global")
    monkeypatch.setenv("OPCOES_RANKING_CACHE_SECONDS", "60")

    calls = {"count": 0}

    def _fake_ctx(_args):
        calls["count"] += 1
        return {"value": calls["count"]}

    monkeypatch.setattr(web, "get_ranking_context", _fake_ctx)
    monkeypatch.setattr(web, "render_template", lambda _tpl, **ctx: f"v={ctx['value']}")

    app = web.create_app()
    app.testing = True
    client = app.test_client()

    first = client.get("/")
    second = client.get("/")

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.data.decode() == "v=1"
    assert second.data.decode() == "v=1"
    assert calls["count"] == 1


def test_index_cache_is_invalidated_after_write_post(monkeypatch) -> None:
    invalidate_namespace("global")
    monkeypatch.setenv("OPCOES_RANKING_CACHE_SECONDS", "60")

    calls = {"count": 0}

    def _fake_ctx(_args):
        calls["count"] += 1
        return {"value": calls["count"]}

    monkeypatch.setattr(web, "get_ranking_context", _fake_ctx)
    monkeypatch.setattr(web, "render_template", lambda _tpl, **ctx: f"v={ctx['value']}")

    app = web.create_app()
    app.testing = True
    client = app.test_client()

    client.get("/")
    assert calls["count"] == 1

    # Endpoint de escrita; deve invalidar o cache da home para o usuário atual.
    resp = client.post("/finance/delete/999")
    assert resp.status_code in {302, 303}

    client.get("/")
    assert calls["count"] == 2


def test_index_cache_is_isolated_by_user(monkeypatch) -> None:
    invalidate_namespace("user:alice")
    invalidate_namespace("user:bob")
    monkeypatch.setenv("OPCOES_RANKING_CACHE_SECONDS", "60")

    calls = {"count": 0}

    def _fake_ctx(_args):
        calls["count"] += 1
        return {"value": calls["count"]}

    monkeypatch.setattr(web, "get_ranking_context", _fake_ctx)
    monkeypatch.setattr(web, "render_template", lambda _tpl, **ctx: f"v={ctx['value']}")

    app = web.create_app()
    app.testing = True
    client = app.test_client()

    with client.session_transaction() as sess:
        sess["username"] = "alice"
    client.get("/")

    with client.session_transaction() as sess:
        sess["username"] = "bob"
    client.get("/")

    with client.session_transaction() as sess:
        sess["username"] = "alice"
    client.get("/")

    # alice = 1 chamada, bob = 1 chamada, alice novamente usa cache.
    assert calls["count"] == 2


def test_index_uses_persisted_ranking_cache_across_app_instances(monkeypatch) -> None:
    invalidate_namespace("global")
    monkeypatch.setenv("OPCOES_RANKING_CACHE_SECONDS", "60")

    calls = {"count": 0}

    def _fake_ctx(_args):
        calls["count"] += 1
        return {"value": calls["count"]}

    monkeypatch.setattr(web, "get_ranking_context", _fake_ctx)
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
