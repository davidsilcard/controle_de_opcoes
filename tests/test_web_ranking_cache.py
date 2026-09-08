import pytest

from opcoes import web
from opcoes.ranking_page_cache import invalidate_namespace

pytestmark = pytest.mark.requires_postgres


def test_index_uses_ranking_cache(monkeypatch) -> None:
    invalidate_namespace("global")
    monkeypatch.setenv("OPCOES_RANKING_CACHE_SECONDS", "60")

    calls = {"count": 0}

    def _fake_ctx(*, args):
        calls["count"] += 1
        return {"value": calls["count"]}

    monkeypatch.setattr(web, "_build_ranking_shell_page_context", _fake_ctx)
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

    def _fake_ctx(*, args):
        calls["count"] += 1
        return {"value": calls["count"]}

    monkeypatch.setattr(web, "_build_ranking_shell_page_context", _fake_ctx)
    monkeypatch.setattr(web, "render_template", lambda _tpl, **ctx: f"v={ctx['value']}")

    app = web.create_app()
    app.testing = True
    client = app.test_client()

    first = client.get("/")
    assert first.get_data(as_text=True) == "v=1"
    assert calls["count"] == 1

    # Endpoint de escrita; deve invalidar o cache da home para o usuário atual.
    resp = client.post("/finance/delete/999")
    assert resp.status_code in {302, 303}

    refreshed = client.get("/")
    assert refreshed.get_data(as_text=True) == "v=2"
    assert calls["count"] == 2


def test_index_cache_is_isolated_by_user(monkeypatch) -> None:
    invalidate_namespace("user:alice")
    invalidate_namespace("user:bob")
    monkeypatch.setenv("OPCOES_RANKING_CACHE_SECONDS", "60")

    calls = {"count": 0}

    def _fake_ctx(*, args):
        calls["count"] += 1
        return {"value": calls["count"]}

    monkeypatch.setattr(web, "_build_ranking_shell_page_context", _fake_ctx)
    monkeypatch.setattr(web, "render_template", lambda _tpl, **ctx: f"v={ctx['value']}")

    app = web.create_app()
    app.testing = True
    client = app.test_client()

    with client.session_transaction() as sess:
        sess["username"] = "alice"
    alice_first = client.get("/")
    assert alice_first.get_data(as_text=True) == "v=1"

    with client.session_transaction() as sess:
        sess["username"] = "bob"
    bob = client.get("/")
    assert bob.get_data(as_text=True) == "v=2"

    with client.session_transaction() as sess:
        sess["username"] = "alice"
    alice_again = client.get("/")
    assert alice_again.get_data(as_text=True) == "v=1"

    # alice = 1 chamada, bob = 1 chamada, alice novamente usa cache.
    assert calls["count"] == 2


def test_ranking_partial_refreshes_data_without_reusing_shell_cache(
    monkeypatch,
) -> None:
    invalidate_namespace("global")
    monkeypatch.setenv("OPCOES_RANKING_CACHE_SECONDS", "60")
    calls = {"shell": 0, "data": 0}

    def _fake_shell(*, args):
        calls["shell"] += 1
        return {"value": "shell"}

    def _fake_data(args):
        calls["data"] += 1
        return {"value": f"{args.get('underlying')}:{calls['data']}"}

    monkeypatch.setattr(web, "_build_ranking_shell_page_context", _fake_shell)
    monkeypatch.setattr(web, "get_ranking_context", _fake_data)
    monkeypatch.setattr(
        web, "render_template", lambda tpl, **ctx: f"{tpl}:{ctx['value']}"
    )
    app = web.create_app()
    app.testing = True
    client = app.test_client()

    shell = client.get("/?underlying=PETR4")
    first = client.get("/partial/ranking?underlying=PETR4")
    second = client.get("/partial/ranking?underlying=PETR4")
    cached_shell = client.get("/?underlying=PETR4")

    assert all(
        response.status_code == 200 for response in (shell, first, second, cached_shell)
    )
    assert shell.get_data(as_text=True) == "index.html:shell"
    assert first.get_data(as_text=True) == "partials/ranking_dashboard.html:PETR4:1"
    assert second.get_data(as_text=True) == "partials/ranking_dashboard.html:PETR4:2"
    assert cached_shell.get_data(as_text=True) == "index.html:shell"
    assert calls == {"shell": 1, "data": 2}


def test_index_uses_persisted_ranking_cache_across_app_instances(monkeypatch) -> None:
    invalidate_namespace("global")
    monkeypatch.setenv("OPCOES_RANKING_CACHE_SECONDS", "60")

    calls = {"count": 0}

    def _fake_ctx(*, args):
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
