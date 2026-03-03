from __future__ import annotations

from opcoes.tax import compute_tax


def test_compute_tax_filters_real_and_simulated(monkeypatch) -> None:
    rows = [
        {
            "trade_type": "swing",
            "trade_date": "2026-01-05",
            "qty": 10,
            "entry_price": 10.0,
            "fees": 0.0,
            "partial_date": None,
            "partial_price": None,
            "partial_qty": 0,
            "exit_date": "2026-01-20",
            "exit_price": 12.0,
            "irrf": 0.0,
            "side": "long",
            "is_simulated": False,
        },
        {
            "trade_type": "swing",
            "trade_date": "2026-01-05",
            "qty": 10,
            "entry_price": 10.0,
            "fees": 0.0,
            "partial_date": None,
            "partial_price": None,
            "partial_qty": 0,
            "exit_date": "2026-01-20",
            "exit_price": 13.0,
            "irrf": 0.0,
            "side": "long",
            "is_simulated": True,
        },
    ]

    def _fake_list_positions(*, include_closed: bool, is_simulated=None, **_kwargs):
        assert include_closed is True
        if is_simulated is None:
            return rows
        return [r for r in rows if bool(r.get("is_simulated")) is bool(is_simulated)]

    monkeypatch.setattr("opcoes.tax.list_positions", _fake_list_positions)

    real = compute_tax(month=1, year=2026, is_simulated=False)
    simulated = compute_tax(month=1, year=2026, is_simulated=True)
    all_modes = compute_tax(month=1, year=2026, is_simulated=None)

    assert real.swing_net == 20.0
    assert real.swing_ir == 3.0
    assert simulated.swing_net == 30.0
    assert simulated.swing_ir == 4.5
    assert all_modes.swing_net == 50.0
    assert all_modes.swing_ir == 7.5
