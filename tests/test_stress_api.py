from __future__ import annotations

from opcoes.stress_api import StressResult, build_summary, percentile


def test_percentile_interpolates_sorted_values() -> None:
    values = [10.0, 20.0, 30.0, 40.0]

    assert percentile(values, 0.50) == 25.0
    assert percentile(values, 0.95) == 38.5


def test_build_summary_reports_success_latency_and_statuses() -> None:
    results = [
        StressResult(latency_ms=10.0, status_code=200, ok=True),
        StressResult(latency_ms=20.0, status_code=200, ok=True),
        StressResult(latency_ms=50.0, status_code=502, ok=False, error="bad_gateway"),
    ]

    summary = build_summary(results, elapsed_seconds=2.0)

    assert summary["requests_total"] == 3
    assert summary["ok_count"] == 2
    assert summary["error_count"] == 1
    assert round(summary["success_rate_pct"], 2) == 66.67
    assert round(summary["requests_per_second"], 2) == 1.5
    assert summary["status_codes"] == {200: 2, 502: 1}
    assert summary["top_errors"][0]["error"] == "bad_gateway"
