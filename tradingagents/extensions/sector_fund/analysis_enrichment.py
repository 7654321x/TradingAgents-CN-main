"""Derived structure, breadth, top-weight and intraday analysis facts."""
from __future__ import annotations

from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd


def daily_price_structure(frame: pd.DataFrame) -> dict[str, Any]:
    data = frame.copy().sort_index()
    close = pd.to_numeric(data["Close"], errors="coerce").dropna()
    if len(close) < 2:
        return {"status": "INSUFFICIENT_HISTORY"}
    sma20 = close.rolling(20, min_periods=20).mean()
    last = data.iloc[-1]
    high, low, open_, close_ = (float(last[key]) for key in ("High", "Low", "Open", "Close"))
    span = high - low
    body_high, body_low = max(open_, close_), min(open_, close_)
    previous = data.iloc[-2]
    previous_body_high, previous_body_low = max(float(previous["Open"]), float(previous["Close"])), min(float(previous["Open"]), float(previous["Close"]))
    return {
        "status": "SUCCESS", "market_date": data.index[-1].date().isoformat(), "close": close_, "sma20_slope_5d_pct": ((sma20.iloc[-1] / sma20.iloc[-6] - 1) * 100 if len(sma20.dropna()) >= 6 and sma20.iloc[-6] else None),
        "support_20d": float(pd.to_numeric(data["Low"], errors="coerce").tail(20).min()) if len(data) >= 20 else None,
        "resistance_20d": float(pd.to_numeric(data["High"], errors="coerce").tail(20).max()) if len(data) >= 20 else None,
        "drawdown_20d_pct": ((close_ / close.tail(20).max() - 1) * 100 if len(close) >= 20 else None),
        "drawdown_60d_pct": ((close_ / close.tail(60).max() - 1) * 100 if len(close) >= 60 else None),
        "close_position_pct": ((close_ - low) / span * 100 if span else None),
        "upper_shadow_pct": ((high - body_high) / span * 100 if span else None),
        "lower_shadow_pct": ((body_low - low) / span * 100 if span else None),
        "gap_pct": ((open_ / float(previous["Close"]) - 1) * 100 if float(previous["Close"]) else None),
        "bullish_engulfing": bool(close_ > open_ and float(previous["Close"]) < float(previous["Open"]) and body_high >= previous_body_high and body_low <= previous_body_low),
        "bearish_engulfing": bool(close_ < open_ and float(previous["Close"]) > float(previous["Open"]) and body_high >= previous_body_high and body_low <= previous_body_low),
    }


def breadth_extensions(frames: dict[str, pd.DataFrame], constituents: list[dict[str, Any]], analysis_date: str, index_return_pct: float | None) -> dict[str, Any]:
    returns, high20, low20, upper, lower, latest_dates, stale_symbols = [], 0, 0, 0, 0, [], []
    expected_date = pd.Timestamp(analysis_date).normalize()
    for item in constituents:
        frame = frames.get(item["symbol"], pd.DataFrame())
        if frame.empty or "Close" not in frame:
            continue
        close = pd.to_numeric(frame.loc[:analysis_date, "Close"], errors="coerce").dropna()
        if len(close) < 2:
            continue
        if close.index[-1].normalize() != expected_date:
            stale_symbols.append(item["symbol"])
            continue
        latest_dates.append(close.index[-1].date().isoformat())
        ret = (close.iloc[-1] / close.iloc[-2] - 1) * 100
        returns.append(float(ret))
        if len(close) >= 20:
            high20 += int(close.iloc[-1] >= close.tail(20).max())
            low20 += int(close.iloc[-1] <= close.tail(20).min())
        upper += int(ret >= 9.8)
        lower += int(ret <= -9.8)
    return {
        "status": "COMPLETE" if len(returns) == len(constituents) else "INSUFFICIENT_COVERAGE",
        "return_median_pct": float(np.median(returns)) if returns else None,
        "outperform_index_count": sum(ret > index_return_pct for ret in returns) if index_return_pct is not None else None,
        "outperform_index_pct": (sum(ret > index_return_pct for ret in returns) / len(returns) * 100 if returns and index_return_pct is not None else None),
        "new_high_20d_count": high20, "new_low_20d_count": low20, "limit_up_count": upper, "limit_down_count": lower, "available_count": len(returns),
        "latest_market_dates": sorted(set(latest_dates)),
        "stale_symbols": stale_symbols,
        "expected_count": len(constituents),
    }


def top_weight_snapshot(frames: dict[str, pd.DataFrame], constituents: list[dict[str, Any]], analysis_date: str, index_return_pct: float | None) -> dict[str, Any]:
    output, latest_dates, stale_symbols = [], [], []
    expected_date = pd.Timestamp(analysis_date).normalize()
    for item in sorted(constituents, key=lambda value: value["weight_pct"], reverse=True)[:10]:
        frame = frames.get(item["symbol"], pd.DataFrame())
        close = pd.to_numeric(frame.loc[:analysis_date, "Close"], errors="coerce").dropna() if not frame.empty and "Close" in frame else pd.Series(dtype=float)
        same_day = len(close) >= 2 and close.index[-1].normalize() == expected_date
        if not same_day:
            stale_symbols.append(item["symbol"])
        ret = (float(close.iloc[-1] / close.iloc[-2] - 1) * 100) if same_day else None
        last = frame.loc[:analysis_date].iloc[-1] if same_day and not frame.empty else {}
        if isinstance(last, pd.Series) and not frame.empty:
            latest_dates.append(frame.loc[:analysis_date].index[-1].date().isoformat())
        output.append({"symbol": item["symbol"], "name": item.get("name"), "weight_pct": item["weight_pct"], "return_1d_pct": ret, "contribution_pct": ret * item["weight_pct"] / 100 if ret is not None else None, "excess_vs_index_pct": ret - index_return_pct if ret is not None and index_return_pct is not None else None, "amount": float(last["Amount"]) if isinstance(last, pd.Series) and pd.notna(last.get("Amount")) else None})
    signs = [np.sign(row["return_1d_pct"]) for row in output if row["return_1d_pct"] is not None]
    return {
        "top10": output,
        "consistent_direction": bool(signs) and len(set(signs)) == 1,
        "latest_market_dates": sorted(set(latest_dates)),
        "stale_symbols": stale_symbols,
        "status": "COMPLETE" if len(signs) == len(output) else "INSUFFICIENT_COVERAGE",
    }


def intraday_tail_metrics(frame: pd.DataFrame, *, as_of: datetime) -> dict[str, Any]:
    cutoff_time = pd.Timestamp(as_of)
    if cutoff_time.tzinfo is not None:
        cutoff_time = cutoff_time.tz_localize(None)
    data = frame.loc[frame.index <= cutoff_time].copy()
    if data.empty:
        return {"status": "INSUFFICIENT_INTRADAY"}
    cutoff = cutoff_time.normalize() + pd.Timedelta(hours=14, minutes=30)
    tail = data.loc[data.index >= cutoff]
    if tail.empty:
        return {"status": "INSUFFICIENT_INTRADAY"}
    first, last = tail.iloc[0], tail.iloc[-1]
    return {"status": "SUCCESS", "tail_30m_return_pct": ((float(last["Close"]) / float(first["Open"]) - 1) * 100 if float(first["Open"]) else None), "tail_30m_amount": float(pd.to_numeric(tail.get("Amount"), errors="coerce").sum()), "tail_high": float(pd.to_numeric(tail["High"], errors="coerce").max()), "tail_close": float(last["Close"]), "pullback_from_tail_high_pct": ((float(last["Close"]) / float(pd.to_numeric(tail["High"], errors="coerce").max()) - 1) * 100)}
