from __future__ import annotations

from opcoes.finance import TransactionType
from opcoes.web import create_app


def _option(
    position_id: int,
    ticker: str,
    *,
    strategy: str,
    strike: float | None,
    expiry: str | None,
    capital: float | None,
    exit_reason: str = "Expiracao",
    shared_fee_note_ref: str | None = None,
) -> dict:
    return {
        "id": position_id,
        "ticker": ticker,
        "underlying": "BBAS3" if strategy == "cash_put" else "PETR4",
        "strategy_tag": strategy,
        "side": "short",
        "status": "closed",
        "trade_date": "2026-03-23",
        "exit_date": "2026-04-17",
        "exit_reason": exit_reason,
        "qty": 100,
        "contract_strike": strike,
        "contract_expiry": expiry,
        "capital_committed": capital,
        "shared_fee_pending": bool(shared_fee_note_ref),
        "shared_fee_note_ref": shared_fee_note_ref,
        "is_simulated": False,
    }


def test_performance_view_renders_independent_action_queues(monkeypatch) -> None:
    positions = [
        _option(
            1,
            "BBASP226",
            strategy="cash_put",
            strike=22.61,
            expiry="2026-04-17",
            capital=None,
            shared_fee_note_ref="Nota BTG #1",
        ),
        _option(
            2,
            "PETRD521",
            strategy="covered_call",
            strike=52.15,
            expiry="2026-04-17",
            capital=None,
        ),
        _option(
            3,
            "PETRE500",
            strategy="covered_call",
            strike=None,
            expiry="2026-05-15",
            capital=3190.0,
        ),
        _option(
            4,
            "PETRG405",
            strategy="covered_call",
            strike=39.36,
            expiry="2026-07-17",
            capital=3190.0,
            exit_reason="Exercicio",
        ),
    ]
    monkeypatch.setattr("opcoes.web.list_positions", lambda **_kwargs: positions)
    monkeypatch.setattr(
        "opcoes.web.finance.get_ledger_sums_by_position",
        lambda **_kwargs: {
            position["id"]: {
                TransactionType.PREMIUM.value: 50.0,
                TransactionType.REALIZED.value: 50.0,
            }
            for position in positions
        },
    )
    monkeypatch.setattr("opcoes.web.list_wheel_cycles", lambda **_kwargs: [])

    app = create_app()
    app.testing = True
    response = app.test_client().get("/performance?mode=real")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Contratos aguardando confirmação documental" in html
    assert "Garantias históricas a declarar" in html
    assert "Vínculos de ações exercidas" in html
    assert "Custos compartilhados sem rateio — informativo (1 referências)" in html
    assert "não verifica a contabilização da despesa no caixa" in html
    assert "Completude cadastral do histórico" in html
    assert "não representam o lucro líquido final" in html
    assert "Aguardando rateio da corretora" not in html
    assert "#1 BBASP226" in html
    assert "R$ 2261.00" in html
    assert "automático" in html
    assert 'action="/performance/contract/2"' in html
    assert 'action="/performance/contract/3"' in html
    assert 'action="/performance/contract/4"' in html


def test_performance_view_shows_audited_contract_adjustment(monkeypatch) -> None:
    position = _option(
        53, "PETRE500", strategy="covered_call", strike=50.0,
        expiry="2026-05-15", capital=None,
    )
    position.update(contract_adjusted_strike=49.46, contract_adjustment_date="2026-04-23")
    monkeypatch.setattr("opcoes.web.list_positions", lambda **_kwargs: [position])
    monkeypatch.setattr(
        "opcoes.web.finance.get_ledger_sums_by_position",
        lambda **_kwargs: {53: {TransactionType.PREMIUM.value: 106.0, TransactionType.REALIZED.value: 106.0}},
    )
    monkeypatch.setattr("opcoes.web.list_wheel_cycles", lambda **_kwargs: [])

    app = create_app()
    app.testing = True
    html = app.test_client().get("/performance?mode=real").get_data(as_text=True)

    assert "Strike ajustado: R$ 49.46 em 2026-04-23" in html


def test_shared_fee_groups_do_not_merge_unknown_references(monkeypatch) -> None:
    positions = [
        _option(
            position_id, "BBASP226", strategy="cash_put", strike=22.61,
            expiry="2026-04-17", capital=None,
            shared_fee_note_ref="Nota BTG #1" if position_id < 3 else None,
        )
        for position_id in range(1, 5)
    ]
    for position in positions:
        position["shared_fee_pending"] = True
    monkeypatch.setattr("opcoes.web.list_positions", lambda **_kwargs: positions)
    monkeypatch.setattr("opcoes.web.finance.get_ledger_sums_by_position", lambda **_kwargs: {})
    monkeypatch.setattr("opcoes.web.list_wheel_cycles", lambda **_kwargs: [])
    captured = {}

    def render(_template, **context):
        captured.update(context)
        return "ok"

    monkeypatch.setattr("opcoes.web.render_template", render)
    app = create_app()
    app.testing = True
    assert app.test_client().get("/performance").status_code == 200

    groups = captured["performance"]["shared_fee_groups"]
    assert sorted(len(group["cycles"]) for group in groups) == [1, 1, 2]
    assert len({group["note_ref"] for group in groups}) == 3
    assert captured["performance"]["evidence_pending_cycles"] == []
    assert captured["performance"]["guarantee_pending_cycles"] == []
