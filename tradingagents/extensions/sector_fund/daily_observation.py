"""Deterministic daily observation checklist for fund 020671.

This module deliberately reports observable conditions rather than predictions
or trading instructions.  It does not alter the sector-fund scores.
"""
from __future__ import annotations

from typing import Any


def _status(value: bool | None, passed: str, failed: str) -> str:
    if value is None:
        return "UNAVAILABLE"
    return passed if value else failed


def build_daily_observation(metrics: dict[str, Any]) -> dict[str, Any]:
    """Build the user's recurring ETF/sector watch list from scored inputs."""
    etf = metrics["etf"]
    sector = metrics["sector"]
    close, sma20 = etf.get("close"), etf.get("sma20")
    macd_hist = etf.get("macd_histogram")
    rsi14 = etf.get("rsi14")
    advance, decline = sector.get("advancers"), sector.get("decliners")
    weighted_return = sector.get("index_weighted_return_pct")
    amount_ratio = sector.get("amount_vs_5d_avg")
    return {
        "status": "DETERMINISTIC_CURRENT_SNAPSHOT",
        "analysis_date": metrics.get("requested_analysis_date"),
        "market_date": metrics.get("market_date"),
        "items": [
            {
                "key": "etf_above_sma20",
                "label": "目标ETF是否站回20日均线",
                "status": _status(
                    None if close is None or sma20 is None else close >= sma20,
                    "ABOVE_SMA20",
                    "BELOW_SMA20",
                ),
                "value": {"close": close, "sma20": sma20},
            },
            {
                "key": "macd_histogram",
                "label": "MACD柱状图当前状态",
                "status": _status(
                    None if macd_hist is None else macd_hist >= 0,
                    "NON_NEGATIVE",
                    "NEGATIVE",
                ),
                "value": {
                    "histogram": macd_hist,
                    "daily_change": etf.get("macd_histogram_change"),
                },
                "limitation": "当前快照不能单独证明柱状图已由负转正。",
            },
            {
                "key": "rsi14_above_50",
                "label": "RSI是否站上50",
                "status": _status(
                    None if rsi14 is None else rsi14 >= 50,
                    "ABOVE_OR_EQUAL_50",
                    "BELOW_50",
                ),
                "value": {"rsi14": rsi14},
            },
            {
                "key": "etf_returns",
                "label": "ETF 5日和20日收益",
                "status": "CURRENT_VALUES_ONLY",
                "value": {
                    "return_5d_pct": etf.get("return_5d_pct"),
                    "return_20d_pct": etf.get("return_20d_pct"),
                },
                "limitation": "是否停止持续恶化需与下一次同步结果比较。",
            },
            {
                "key": "constituent_breadth",
                "label": "芯片板块权重股与成分股同步状态",
                "status": _status(
                    None
                    if advance is None or decline is None or weighted_return is None
                    else advance > decline and weighted_return >= 0,
                    "BREADTH_AND_WEIGHTED_RETURN_POSITIVE",
                    "NO_CONFIRMED_SYNCHRONOUS_STABILISATION",
                ),
                "value": {
                    "advancers": advance,
                    "decliners": decline,
                    "weighted_return_pct": weighted_return,
                    "amount_vs_5d_avg": amount_ratio,
                },
                "limitation": "该项是当日广度确认，不等同于个别权重股的趋势反转。",
            },
        ],
        "disclaimer": "观察项用于跟踪已发生数据，不构成收益预测或个性化投资建议。",
    }
