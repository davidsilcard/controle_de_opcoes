from __future__ import annotations

from pathlib import Path


def test_live_market_controller_preserves_status_after_htmx_swap() -> None:
    source = Path("opcoes/static/live_market.js").read_text(encoding="utf-8")

    assert "this.connectionKind" in source
    assert "this.connectionText" in source
    assert "applyStatus()" in source
    assert "this.applyStatus();" in source


def test_live_market_controller_keeps_live_heartbeat() -> None:
    source = Path("opcoes/static/live_market.js").read_text(encoding="utf-8")

    assert "startLiveHeartbeat()" in source
    assert "this.subscribe();" in source
    assert "this.scheduleRefresh();" in source
    assert "window.setInterval" in source
