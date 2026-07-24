"""Deterministic returns and drawdown from official fund NAV observations."""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class FundNavMetrics:
    fund_code: str
    analysis_date: str
    latest_nav_date: str
    unit_nav: float
    cumulative_nav: float
    daily_change_pct: float | None
    nav_age_days: int
    return_1d_pct: float | None
    return_3d_pct: float | None
    return_5d_pct: float | None
    return_10d_pct: float | None
    return_20d_pct: float | None
    drawdown_20d_pct: float | None
    source: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def calculate_fund_nav_metrics(observations: Iterable[Any], analysis_date: str) -> FundNavMetrics:
    rows = sorted(
        [row for row in observations if str(row.nav_date) <= str(analysis_date)],
        key=lambda row: row.nav_date,
    )
    if not rows:
        raise ValueError("no official NAV observation at or before analysis date")
    latest = rows[-1]
    values = pd.Series(
        [float(row.unit_nav) for row in rows],
        index=pd.DatetimeIndex([row.nav_date for row in rows]),
        dtype=float,
    )

    def nav_return(period: int) -> float | None:
        if len(values) <= period or values.iloc[-period - 1] == 0:
            return None
        return float((values.iloc[-1] / values.iloc[-period - 1] - 1) * 100)

    trailing = values.iloc[-20:]
    drawdown = (
        float((trailing.iloc[-1] / trailing.max() - 1) * 100)
        if len(trailing) == 20 and trailing.max() != 0
        else None
    )
    age = (pd.Timestamp(analysis_date) - pd.Timestamp(latest.nav_date)).days
    return FundNavMetrics(
        fund_code=latest.fund_code,
        analysis_date=analysis_date,
        latest_nav_date=latest.nav_date,
        unit_nav=float(latest.unit_nav),
        cumulative_nav=float(latest.cumulative_nav),
        daily_change_pct=latest.daily_change_pct,
        nav_age_days=age,
        return_1d_pct=nav_return(1),
        return_3d_pct=nav_return(3),
        return_5d_pct=nav_return(5),
        return_10d_pct=nav_return(10),
        return_20d_pct=nav_return(20),
        drawdown_20d_pct=drawdown,
        source=latest.source,
    )
