from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from tradingagents.analysis.stock_evidence import (
    StockEvidenceEngine,
    _ma_structure,
    _max_drawdown,
    build_adjusted_ohlc,
    classify_trend,
    return_metric,
    slope_metric,
    wilder_adx,
)


def frame(rows=260, *, rising=True):
    index = pd.bdate_range("2025-01-02", periods=rows)
    close = np.linspace(100, 180 if rising else 60, rows)
    return pd.DataFrame(
        {
            "Open": close - 1,
            "High": close + 2,
            "Low": close - 2,
            "Close": close,
            "Adj Close": close,
            "Volume": np.arange(rows) + 1000.0,
        },
        index=index,
    )


def calculate(data):
    return StockEvidenceEngine().calculate(
        data,
        symbol="001309.SZ",
        name="德明利",
        analysis_date=data.index[-1].date().isoformat(),
        source="database",
        provider_calls=0,
    )


def test_adjusted_ohlc_uses_consistent_factor():
    data = frame(30)
    data["Adj Close"] = data["Close"] * 0.5
    result = build_adjusted_ohlc(data)
    assert result.frame.iloc[-1]["Open"] == pytest.approx(data.iloc[-1]["Open"] * 0.5)
    assert result.frame.iloc[-1]["High"] == pytest.approx(data.iloc[-1]["High"] * 0.5)
    assert result.frame.iloc[-1]["Low"] == pytest.approx(data.iloc[-1]["Low"] * 0.5)


def test_split_does_not_create_false_return():
    data = frame(30)
    data.loc[data.index[:15], "Close"] *= 2
    data.loc[data.index[:15], ["Open", "High", "Low"]] *= 2
    adjusted = build_adjusted_ohlc(data)
    assert adjusted.frame["Close"].pct_change().abs().max() < 0.05
    assert adjusted.audit["price_adjustment_status"] == "ADJUSTED"


def test_atr_uses_adjusted_ohlc():
    data = frame(50)
    data["Adj Close"] = data["Close"] * 0.25
    adjusted = build_adjusted_ohlc(data).frame
    actual = wilder_adx(adjusted)["atr14"].iloc[-1]
    raw = wilder_adx(data.rename(columns={"Adj Close": "ignored"}))["atr14"].iloc[-1]
    assert actual == pytest.approx(raw * 0.25)


def test_raw_close_is_only_used_for_display():
    data = frame(260)
    data["Adj Close"] = data["Close"] * 0.5
    result = calculate(data)
    assert result.market_input["latest_raw_close"] == pytest.approx(data["Close"].iloc[-1])
    assert result.market_input["latest_adjusted_close"] == pytest.approx(data["Adj Close"].iloc[-1])
    assert result.market_input["ma20"] < result.market_input["latest_raw_close"]


def test_missing_adjusted_close_is_explicit():
    data = frame(40)
    data["Adj Close"] = np.nan
    result = build_adjusted_ohlc(data)
    assert result.audit["price_adjustment_status"] == "RAW_FALLBACK"
    assert result.audit["warnings"]


@pytest.mark.parametrize("period", [5, 10, 20, 40, 60])
def test_return_uses_trading_rows(period):
    close = pd.Series(np.arange(1, 101, dtype=float), index=pd.bdate_range("2025-01-01", periods=100))
    metric = return_metric(close, period)
    assert metric["value_pct"] == pytest.approx((100 / (100 - period) - 1) * 100)
    assert metric["required_rows"] == period + 1


def test_120d_insufficient_history():
    metric = return_metric(pd.Series(range(100), dtype=float), 120)
    assert metric["value_pct"] is None
    assert metric["status"] == "INSUFFICIENT_HISTORY"


def test_return_does_not_use_future_data():
    data = frame(80)
    cutoff = data.iloc[:61]
    result = calculate(cutoff)
    assert result.market_input["return_60d_pct"] == pytest.approx((cutoff["Adj Close"].iloc[-1] / cutoff["Adj Close"].iloc[0] - 1) * 100)


def test_strong_bullish_ma_alignment():
    status, score, _ = _ma_structure(110, {5: 105, 10: 103, 20: 100}, {"ma5_slope_3d": 1, "ma10_slope_5d": 1, "ma20_slope_5d": 1})
    assert (status, score) == ("STRONG_BULLISH_ALIGNMENT", 1.0)


def test_bullish_pullback():
    status, score, _ = _ma_structure(103, {5: 105, 10: 104, 20: 100}, {"ma5_slope_3d": -1, "ma10_slope_5d": 1, "ma20_slope_5d": 1})
    assert status in {"BULLISH_ALIGNMENT", "BULLISH_PULLBACK"}
    assert score > 0


def test_entangled_ma_structure():
    status, _, _ = _ma_structure(100, {5: 100.5, 10: 100, 20: 99.5}, {"ma5_slope_3d": 0, "ma10_slope_5d": 0, "ma20_slope_5d": 0})
    assert status == "ENTANGLED"


def test_strong_bearish_ma_alignment():
    status, score, _ = _ma_structure(90, {5: 95, 10: 97, 20: 100}, {"ma5_slope_3d": -1, "ma10_slope_5d": -1, "ma20_slope_5d": -1})
    assert (status, score) == ("STRONG_BEARISH_ALIGNMENT", -1.0)


def test_ma_slope_uses_trading_rows():
    series = pd.Series(np.arange(1, 21, dtype=float), index=pd.bdate_range("2025-01-01", periods=20))
    assert slope_metric(series, 5) == pytest.approx((20 / 15 - 1) * 100)


def test_adx_does_not_define_direction():
    up = calculate(frame(260, rising=True))
    down = calculate(frame(260, rising=False))
    assert up.market_input["adx14"] > 25 and down.market_input["adx14"] > 25
    assert up.trend_result["deterministic_trend"] != down.trend_result["deterministic_trend"]


def test_plus_di_minus_di_direction():
    up = calculate(frame(100, rising=True)).market_input
    down = calculate(frame(100, rising=False)).market_input
    assert up["plus_di14"] > up["minus_di14"]
    assert down["minus_di14"] > down["plus_di14"]


def test_volume_ratio_excludes_current_row():
    data = frame(260)
    data.iloc[-1, data.columns.get_loc("Volume")] = 10_000
    result = calculate(data).market_input
    expected = 10_000 / data["Volume"].iloc[-21:-1].mean()
    assert result["volume_ratio_20d"] == pytest.approx(expected)


def test_up_day_ratio():
    data = frame(260)
    result = calculate(data).market_input
    assert result["up_day_ratio_20d"] == 1.0


def test_annualized_volatility():
    data = frame(260)
    result = calculate(data).market_input
    expected = data["Adj Close"].pct_change().dropna().tail(20).std(ddof=1) * math.sqrt(252) * 100
    assert result["volatility_20d_pct"] == pytest.approx(expected)


def test_true_max_drawdown():
    close = pd.Series([100, 120, 80, 110, 90], dtype=float)
    assert _max_drawdown(close, 5) == pytest.approx((80 / 120 - 1) * 100)


def test_return_score_is_primary_component():
    result = calculate(frame(260)).trend_result
    assert result["scoring_rule"].startswith("0.45*return")


def test_missing_return_period_reweights_score():
    result = calculate(frame(45)).trend_result
    assert result["return_trend"]["period_scores"][60] is None
    assert -1 <= result["return_score"] <= 1


def test_risk_does_not_reverse_direction_score():
    result = calculate(frame(260)).trend_result
    assert classify_trend(result["technical_score"]) == result["deterministic_trend"]
    assert "risk=" in result["scoring_rule"]


def test_long_term_trend_requires_long_history():
    result = calculate(frame(150)).trend_result
    assert result["long_term_trend"] == "INSUFFICIENT_DATA"


def test_trend_and_risk_score_ranges():
    result = calculate(frame(260)).trend_result
    assert -1 <= result["technical_score"] <= 1
    assert 0 <= result["technical_risk_score"] <= 1
