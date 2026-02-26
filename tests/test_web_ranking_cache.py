from opcoes import web


def test_index_uses_ranking_cache(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("OPCOES_DB_PATH", str(tmp_path / "app.db"))
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


def test_index_cache_is_invalidated_after_write_post(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("OPCOES_DB_PATH", str(tmp_path / "app.db"))
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


def test_index_cache_is_isolated_by_user(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("OPCOES_DB_PATH", str(tmp_path / "app.db"))
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

