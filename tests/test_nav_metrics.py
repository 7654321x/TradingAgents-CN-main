from __future__ import annotations

from tradingagents.extensions.sector_fund.efunds_provider import EFundsNavObservation
from tradingagents.extensions.sector_fund.nav_metrics import calculate_fund_nav_metrics


def _rows(count=25):
    return tuple(
        EFundsNavObservation(
            fund_code="020671",
            nav_date=f"2026-06-{index + 1:02d}",
            unit_nav=float(index + 1),
            cumulative_nav=float(index + 1),
            daily_change_pct=1.0,
            source_url="https://www.efunds.com.cn/fund/020671.shtml",
            fetched_at="2026-07-22T12:00:00+00:00",
        )
        for index in range(count)
    )


def test_nav_returns_use_trading_rows_and_respect_analysis_date():
    result = calculate_fund_nav_metrics(_rows(), "2026-06-25")
    assert result.latest_nav_date == "2026-06-25"
    assert result.nav_age_days == 0
    assert result.return_1d_pct == (25 / 24 - 1) * 100
    assert result.return_3d_pct == (25 / 22 - 1) * 100
    assert result.return_5d_pct == (25 / 20 - 1) * 100
    assert result.return_10d_pct == (25 / 15 - 1) * 100
    assert result.drawdown_20d_pct == 0.0


def test_nav_metrics_rejects_future_only_observations():
    try:
        calculate_fund_nav_metrics(_rows(2), "2026-05-01")
    except ValueError as exc:
        assert "at or before" in str(exc)
    else:
        raise AssertionError("expected missing point-in-time NAV to fail")
