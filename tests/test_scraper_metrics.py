from __future__ import annotations

from opcoes.scraper.run import _history_store_target, _recalculate_snapshot_metrics


def _ptbr_to_float(value: str) -> float:
    return float(value.replace(".", "").replace(",", "."))


class _FakeIVStore:
    def __init__(self) -> None:
        self.saved: dict[tuple[str, str, str], float] = {}

    def record_many(self, entries):
        for underlying, vencimento, snapshot_date, iv_value in entries:
            self.saved[(underlying, vencimento, snapshot_date)] = float(iv_value)

    def rank_for(self, underlying: str, vencimento: str, _snapshot_date: str, _current: float):
        base = [
            iv_value
            for (u, venc, _d), iv_value in self.saved.items()
            if u == underlying and venc == vencimento
        ]
        if len(base) < 1:
            return None
        return 50.0


class _FakeFlowStore:
    def __init__(self) -> None:
        self.saved: dict[tuple[str, str], tuple[float | None, float | None]] = {}

    def averages(self, ticker: str, _snapshot_date: str):
        if ticker == "PETRA123":
            return 1000.0, 10.0
        return None, None

    def record_many(self, entries):
        for ticker, snapshot_date, vol, num in entries:
            self.saved[(ticker, snapshot_date)] = (vol, num)


def test_history_store_target_returns_none_in_postgres_mode() -> None:
    assert _history_store_target("iv_history.local") is None
    assert _history_store_target("flow_history.local") is None


def test_recalculate_snapshot_metrics_applies_flow_and_iv() -> None:
    iv_store = _FakeIVStore()
    flow_store = _FakeFlowStore()
    rows = [
        {
            "ticker": "PETRA123",
            "underlying": "PETR4",
            "vencimento": "20/02/2026",
            "vol_impl_perc": "25,0",
            "vol_financeiro": "1500,00",
            "num_neg": "15",
            "moneyness_score": "2,00",
            "prob_itm_pct": "55,0",
            "prob_itm_delta_pct": "45,0",
            "extrinsic_pct_spot": "2,00",
            "liquidez_score": "2,00",
            "theta_score": "1,00",
            "em2x_score": "2",
            "dobro_score": "2",
            "Status_Remoto": "",
            "score_total": "0,00",
        }
    ]

    _recalculate_snapshot_metrics(
        rows,
        snapshot_date="2026-02-05",
        iv_store=iv_store,
        flow_store=flow_store,
    )

    row = rows[0]
    assert row["iv_rank_180d"] != ""
    assert row["iv_score"] != ""
    assert row["vol_fluxo_5d"] != ""
    assert row["num_fluxo_5d"] != ""
    assert _ptbr_to_float(row["score_total"]) > 0.0
