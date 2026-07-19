from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd
from stockstats import wrap


EVIDENCE_SCHEMA_VERSION = "stock_evidence_v2"
MA_ENTANGLED_SPREAD_PCT = 2.0
TREND_THRESHOLDS = {
    "strong_bullish": 0.60,
    "bullish": 0.20,
    "bearish": -0.20,
    "strong_bearish": -0.60,
}
RETURN_WEIGHTS = {5: 0.15, 10: 0.10, 20: 0.25, 40: 0.20, 60: 0.30}


def finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def clip(value: float, lower: float = -1.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, float(value)))


def classify_trend(score: float) -> str:
    if score >= TREND_THRESHOLDS["strong_bullish"]:
        return "STRONG_BULLISH"
    if score >= TREND_THRESHOLDS["bullish"]:
        return "BULLISH"
    if score <= TREND_THRESHOLDS["strong_bearish"]:
        return "STRONG_BEARISH"
    if score <= TREND_THRESHOLDS["bearish"]:
        return "BEARISH"
    return "SIDEWAYS"


@dataclass
class AdjustedPriceResult:
    frame: pd.DataFrame
    audit: dict[str, Any]


def build_adjusted_ohlc(raw: pd.DataFrame) -> AdjustedPriceResult:
    data = raw.sort_index().copy()
    for column in ("Open", "High", "Low", "Close", "Adj Close", "Volume"):
        if column in data:
            data[column] = pd.to_numeric(data[column], errors="coerce")
    raw_close = data.get("Close", pd.Series(index=data.index, dtype=float))
    adjusted_close = data.get("Adj Close", pd.Series(index=data.index, dtype=float))
    valid = (
        raw_close.notna()
        & adjusted_close.notna()
        & np.isfinite(raw_close)
        & np.isfinite(adjusted_close)
        & (raw_close > 0)
        & (adjusted_close > 0)
    )
    coverage = float(valid.mean()) if len(data) else 0.0
    factor = pd.Series(np.nan, index=data.index, dtype=float)
    factor.loc[valid] = adjusted_close.loc[valid] / raw_close.loc[valid]
    factor = factor.where(np.isfinite(factor) & (factor > 0))
    warnings: list[str] = []
    if len(data) < 2:
        status = "INSUFFICIENT_DATA"
        basis = "raw"
    elif coverage >= 0.95:
        status = "ADJUSTED"
        basis = "adjusted"
    else:
        status = "RAW_FALLBACK"
        basis = "raw"
        warnings.append(f"复权收盘价有效覆盖率仅为 {coverage:.2%}，技术指标回退原始价格")

    output = pd.DataFrame(index=data.index)
    if basis == "adjusted":
        for source, target in (("Open", "Open"), ("High", "High"), ("Low", "Low")):
            output[target] = data[source] * factor if source in data else np.nan
        output["Close"] = adjusted_close
    else:
        for column in ("Open", "High", "Low", "Close"):
            output[column] = data.get(column)
    output["Volume"] = data.get("Volume")

    adjusted_returns = output["Close"].pct_change(fill_method=None)
    suspicious_dates = [
        idx.date().isoformat()
        for idx, value in adjusted_returns.items()
        if finite(value) is not None and abs(float(value)) > 0.50
    ]
    if suspicious_dates:
        status = "SUSPICIOUS"
        warnings.append("连续技术价格存在单日绝对涨跌超过50%的断点")
    factor_changes = factor.pct_change(fill_method=None).abs()
    abrupt_factor_dates = [
        idx.date().isoformat()
        for idx, value in factor_changes.items()
        if finite(value) is not None and float(value) > 0.50
    ]
    if abrupt_factor_dates:
        warnings.append("复权因子存在超过50%的阶跃，已按复权连续价格计算并保留审计日期")

    audit = {
        "display_price_basis": "raw",
        "technical_price_basis": basis,
        "price_adjustment_status": status,
        "adjusted_close_coverage": coverage,
        "valid_adjustment_factor_rows": int(factor.notna().sum()),
        "total_rows": len(data),
        "latest_adjustment_factor": finite(factor.iloc[-1]) if len(factor) else None,
        "minimum_adjustment_factor": finite(factor.min()),
        "maximum_adjustment_factor": finite(factor.max()),
        "abrupt_factor_dates": abrupt_factor_dates,
        "suspicious_price_gap_dates": suspicious_dates,
        "warnings": warnings,
        "formula": "adjustment_factor=adjusted_close/raw_close; adjusted_OHL=raw_OHL*adjustment_factor",
    }
    return AdjustedPriceResult(output.dropna(subset=["Close"]), audit)


def return_metric(close: pd.Series, periods: int, price_basis: str = "adjusted") -> dict[str, Any]:
    values = pd.to_numeric(close, errors="coerce").dropna()
    required = periods + 1
    if len(values) < required:
        return {
            "value_pct": None,
            "required_rows": required,
            "available_rows": len(values),
            "status": "INSUFFICIENT_HISTORY",
            "price_basis": price_basis,
        }
    value = (float(values.iloc[-1]) / float(values.iloc[-periods - 1]) - 1.0) * 100
    return {
        "value_pct": value,
        "required_rows": required,
        "available_rows": len(values),
        "status": "SUCCESS",
        "price_basis": price_basis,
    }


def moving_average(close: pd.Series, window: int) -> pd.Series:
    return pd.to_numeric(close, errors="coerce").rolling(window, min_periods=window).mean()


def slope_metric(series: pd.Series, periods: int) -> float | None:
    values = pd.to_numeric(series, errors="coerce").dropna()
    if len(values) < periods + 1 or float(values.iloc[-periods - 1]) == 0:
        return None
    return (float(values.iloc[-1]) / float(values.iloc[-periods - 1]) - 1.0) * 100


def wilder_adx(frame: pd.DataFrame, window: int = 14) -> pd.DataFrame:
    high = pd.to_numeric(frame["High"], errors="coerce")
    low = pd.to_numeric(frame["Low"], errors="coerce")
    close = pd.to_numeric(frame["Close"], errors="coerce")
    up = high.diff()
    down = -low.diff()
    plus_dm = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=frame.index)
    minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=frame.index)
    true_range = pd.concat(
        [(high - low).abs(), (high - close.shift()).abs(), (low - close.shift()).abs()],
        axis=1,
    ).max(axis=1)
    atr = true_range.ewm(alpha=1 / window, adjust=False, min_periods=window).mean()
    plus = 100 * plus_dm.ewm(alpha=1 / window, adjust=False, min_periods=window).mean() / atr
    minus = 100 * minus_dm.ewm(alpha=1 / window, adjust=False, min_periods=window).mean() / atr
    denominator = (plus + minus).replace(0, np.nan)
    dx = 100 * (plus - minus).abs() / denominator
    adx = dx.ewm(alpha=1 / window, adjust=False, min_periods=window).mean()
    return pd.DataFrame({"atr14": atr, "plus_di14": plus, "minus_di14": minus, "adx14": adx})


def _ma_structure(close: float, ma: dict[int, float | None], slopes: dict[str, float | None]) -> tuple[str, float, float | None]:
    m5, m10, m20 = ma[5], ma[10], ma[20]
    if None in (m5, m10, m20):
        return "INSUFFICIENT_DATA", 0.0, None
    spread = (max(m5, m10, m20) / min(m5, m10, m20) - 1) * 100 if min(m5, m10, m20) > 0 else None
    positive = all((slopes[key] or 0) > 0 for key in ("ma5_slope_3d", "ma10_slope_5d", "ma20_slope_5d"))
    negative = all((slopes[key] or 0) < 0 for key in ("ma5_slope_3d", "ma10_slope_5d", "ma20_slope_5d"))
    if close > m5 > m10 > m20 and positive:
        return "STRONG_BULLISH_ALIGNMENT", 1.0, spread
    if close < m5 < m10 < m20 and negative:
        return "STRONG_BEARISH_ALIGNMENT", -1.0, spread
    if spread is not None and spread <= MA_ENTANGLED_SPREAD_PCT:
        return "ENTANGLED", 0.0, spread
    if m5 > m10 > m20:
        return "BULLISH_ALIGNMENT", 0.65, spread
    if close < max(m5, m10) and close > m20 and (slopes["ma20_slope_5d"] or 0) > 0:
        return "BULLISH_PULLBACK", 0.35, spread
    if close > m5 and m5 < m10 < m20:
        return "BEARISH_REBOUND", -0.35, spread
    if close < m5 < m10 < m20:
        return "BEARISH_ALIGNMENT", -0.65, spread
    return "ENTANGLED", 0.0, spread


def _return_bucket(value: float | None) -> float | None:
    if value is None:
        return None
    if value >= 20:
        return 1.0
    if value >= 10:
        return 0.7
    if value >= 3:
        return 0.3
    if value > -3:
        return 0.0
    if value > -10:
        return -0.3
    if value > -20:
        return -0.7
    return -1.0


def _weighted(values: dict[int, float | None], weights: dict[int, float]) -> float:
    valid = [(values[key], weight) for key, weight in weights.items() if values.get(key) is not None]
    denominator = sum(weight for _, weight in valid)
    return sum(float(value) * weight for value, weight in valid) / denominator if denominator else 0.0


def _max_drawdown(close: pd.Series, rows: int) -> float | None:
    values = pd.to_numeric(close, errors="coerce").dropna().tail(rows)
    if len(values) < rows:
        return None
    drawdown = values / values.cummax() - 1.0
    return float(drawdown.min()) * 100


def _window_metric(close: pd.Series, rows: int, mode: str) -> float | None:
    values = pd.to_numeric(close, errors="coerce").dropna().tail(rows)
    if len(values) < rows:
        return None
    latest = float(values.iloc[-1])
    target = float(values.max() if mode == "high" else values.min())
    return (latest / target - 1.0) * 100 if target else None


def _record(value: Any, unit: str, cutoff: str, *, basis: str = "adjusted", status: str | None = None) -> dict[str, Any]:
    return {
        "value": value,
        "unit": unit,
        "status": status or ("SUCCESS" if value is not None else "INSUFFICIENT_HISTORY"),
        "source": "database",
        "price_basis": basis,
        "data_cutoff": cutoff,
    }


@dataclass
class EvidenceEngineResult:
    market_input: dict[str, Any]
    adjusted_price_audit: dict[str, Any]
    trend_result: dict[str, Any]
    evidence_package: dict[str, Any]


class StockEvidenceEngine:
    def calculate(self, raw: pd.DataFrame, *, symbol: str, name: str, analysis_date: str, source: str, provider_calls: int) -> EvidenceEngineResult:
        adjusted = build_adjusted_ohlc(raw)
        frame = adjusted.frame
        close = frame["Close"]
        cutoff = frame.index[-1].date().isoformat()
        raw_close = finite(pd.to_numeric(raw["Close"], errors="coerce").dropna().iloc[-1])
        adjusted_close = finite(close.iloc[-1])
        returns = {period: return_metric(close, period, adjusted.audit["technical_price_basis"]) for period in (5, 10, 20, 40, 60, 120, 200)}
        mas = {window: moving_average(close, window) for window in (5, 10, 20, 50, 200)}
        ma_values = {window: finite(series.iloc[-1]) for window, series in mas.items()}
        slopes = {
            "ma5_slope_3d": slope_metric(mas[5], 3),
            "ma10_slope_5d": slope_metric(mas[10], 5),
            "ma20_slope_5d": slope_metric(mas[20], 5),
            "ma50_slope_10d": slope_metric(mas[50], 10),
            "ma200_slope_20d": slope_metric(mas[200], 20),
        }
        distances = {
            f"close_vs_ma{window}_pct": (adjusted_close / value - 1) * 100 if adjusted_close is not None and value else None
            for window, value in ma_values.items()
        }
        short_structure, short_ma_score, ma_spread = _ma_structure(adjusted_close, ma_values, slopes)
        stock = wrap(frame.reset_index().rename(columns={"index": "Date"}))
        for indicator in ("rsi_14", "macd", "macds", "macdh", "boll_ub", "boll", "boll_lb"):
            stock[indicator]
        adx = wilder_adx(frame)
        rsi = finite(stock["rsi_14"].iloc[-1])
        macd = finite(stock["macd"].iloc[-1])
        macds = finite(stock["macds"].iloc[-1])
        macdh = finite(stock["macdh"].iloc[-1])
        old_hist = finite(stock["macdh"].iloc[-6]) if len(stock) >= 6 else None
        macdh_change = macdh - old_hist if None not in (macdh, old_hist) else None
        adx14 = finite(adx["adx14"].iloc[-1])
        plus_di = finite(adx["plus_di14"].iloc[-1])
        minus_di = finite(adx["minus_di14"].iloc[-1])
        di_spread = plus_di - minus_di if None not in (plus_di, minus_di) else None
        atr14 = finite(adx["atr14"].iloc[-1])
        atr_pct = atr14 / adjusted_close * 100 if atr14 is not None and adjusted_close else None

        volume = pd.to_numeric(frame["Volume"], errors="coerce")
        latest_volume = finite(volume.iloc[-1])
        volume_5_avg = finite(volume.iloc[-6:-1].mean()) if len(volume) >= 6 else None
        volume_20_avg = finite(volume.iloc[-21:-1].mean()) if len(volume) >= 21 else None
        volume_ratio_5 = latest_volume / volume_5_avg if latest_volume is not None and volume_5_avg and volume_5_avg > 0 else None
        volume_ratio_20 = latest_volume / volume_20_avg if latest_volume is not None and volume_20_avg and volume_20_avg > 0 else None
        daily_return = close.pct_change(fill_method=None)
        up_ratios = {}
        volatility = {}
        for rows in (20, 60):
            valid_returns = daily_return.dropna().tail(rows)
            up_ratios[rows] = float((valid_returns > 0).sum() / len(valid_returns)) if len(valid_returns) == rows else None
            volatility[rows] = float(valid_returns.std(ddof=1) * math.sqrt(252) * 100) if len(valid_returns) == rows else None
        max_dd = {rows: _max_drawdown(close, rows) for rows in (20, 60, 120)}
        distances_path = {
            "distance_from_20d_high_pct": _window_metric(close, 20, "high"),
            "distance_from_60d_high_pct": _window_metric(close, 60, "high"),
            "distance_from_20d_low_pct": _window_metric(close, 20, "low"),
            "distance_from_60d_low_pct": _window_metric(close, 60, "low"),
        }

        bucket_scores = {period: _return_bucket(metric["value_pct"]) for period, metric in returns.items()}
        return_score = clip(_weighted(bucket_scores, RETURN_WEIGHTS))
        medium_parts = [
            1 if (distances["close_vs_ma20_pct"] or 0) > 0 else -1,
            1 if (distances["close_vs_ma50_pct"] or 0) > 0 else -1,
            1 if (slopes["ma20_slope_5d"] or 0) > 0 else -1,
            1 if (slopes["ma50_slope_10d"] or 0) > 0 else -1,
            _weighted(bucket_scores, {20: 0.35, 40: 0.30, 60: 0.35}),
        ]
        medium_ma_score = clip(sum(medium_parts) / len(medium_parts))
        macd_score = 1.0 if (macdh or 0) > 0 and (macdh_change or 0) > 0 else 0.4 if (macdh or 0) > 0 else -0.4 if (macdh_change or 0) > 0 else -1.0
        rsi_score = 0.6 if rsi is not None and 50 <= rsi <= 70 else -0.5 if rsi is not None and 30 <= rsi < 50 else 0.2 if rsi is not None and rsi > 70 else -0.7 if rsi is not None else 0.0
        di_score = 1.0 if (di_spread or 0) > 0 else -1.0 if (di_spread or 0) < 0 else 0.0
        momentum_score = clip(0.45 * macd_score + 0.25 * rsi_score + 0.30 * di_score)
        direction_20 = np.sign(returns[20]["value_pct"] or 0)
        volume_confirmation_score = clip((1 if direction_20 > 0 else -1 if direction_20 < 0 else 0) * max(0, min((volume_ratio_20 or 1) - 1, 1)))
        technical_score = clip(0.45 * return_score + 0.25 * short_ma_score + 0.10 * medium_ma_score + 0.10 * momentum_score + 0.10 * volume_confirmation_score)

        volatility_risk = clip(((volatility[20] or 0) - 20) / 60, 0, 1)
        worst_dd = max(abs(min(value or 0, 0)) for value in max_dd.values())
        drawdown_risk = clip(worst_dd / 40, 0, 1)
        overextension_risk = clip(max(abs(distances["close_vs_ma20_pct"] or 0), abs(distances["close_vs_ma50_pct"] or 0)) / 40, 0, 1)
        data_quality_risk = 0.0 if adjusted.audit["price_adjustment_status"] == "ADJUSTED" else 0.5 if adjusted.audit["price_adjustment_status"] == "RAW_FALLBACK" else 1.0
        technical_risk_score = clip(0.35 * volatility_risk + 0.35 * drawdown_risk + 0.15 * overextension_risk + 0.15 * data_quality_risk, 0, 1)

        if adx14 is None or adx14 < 20:
            adx_status = "WEAK_TREND"
        elif adx14 < 25:
            adx_status = "DEVELOPING_TREND"
        elif adx14 < 40:
            adx_status = "ESTABLISHED_TREND"
        else:
            adx_status = "STRONG_TREND"
        slope_strength = np.mean([abs(x or 0) for x in slopes.values()])
        agreement = abs(np.mean([np.sign(returns[p]["value_pct"] or 0) for p in (5, 10, 20, 40, 60)]))
        trend_strength = "STRONG" if (adx14 or 0) >= 40 and agreement >= 0.6 else "MODERATE" if (adx14 or 0) >= 20 or slope_strength >= 1 else "WEAK"
        if technical_risk_score >= 0.75:
            path_quality = "HIGHLY_UNSTABLE"
        elif drawdown_risk >= 0.6:
            path_quality = "DRAWDOWN"
        elif volatility_risk >= 0.5:
            path_quality = "VOLATILE"
        else:
            path_quality = "STABLE"
        short_score = clip(0.55 * _weighted(bucket_scores, {5: 0.25, 10: 0.30, 20: 0.45}) + 0.45 * short_ma_score)
        medium_score = clip(0.65 * _weighted(bucket_scores, {20: 0.35, 40: 0.30, 60: 0.35}) + 0.35 * medium_ma_score)
        long_values = {120: bucket_scores[120], 200: bucket_scores[200]}
        long_term = "INSUFFICIENT_DATA" if any(value is None for value in long_values.values()) else classify_trend(_weighted(long_values, {120: 0.45, 200: 0.55}))

        market_input = {
            "symbol": symbol,
            "name": name,
            "analysis_date": analysis_date,
            "data_cutoff": cutoff,
            "daily_row_count": len(frame),
            "first_market_date": frame.index[0].date().isoformat(),
            "latest_market_date": cutoff,
            "latest_raw_close": raw_close,
            "latest_adjusted_close": adjusted_close,
            "latest_close": raw_close,
            "display_price_basis": "raw",
            "technical_price_basis": adjusted.audit["technical_price_basis"],
            "price_adjustment_status": adjusted.audit["price_adjustment_status"],
            "returns": {f"return_{period}d_pct": metric for period, metric in returns.items()},
            **{f"return_{period}d_pct": metric["value_pct"] for period, metric in returns.items()},
            **{f"ma{window}": value for window, value in ma_values.items()},
            "sma20": ma_values[20], "sma50": ma_values[50], "sma200": ma_values[200],
            **slopes,
            "sma20_slope": slopes["ma20_slope_5d"], "sma50_slope": slopes["ma50_slope_10d"], "sma200_slope": slopes["ma200_slope_20d"],
            **distances,
            "distance_to_sma20_pct": distances["close_vs_ma20_pct"], "distance_to_sma50_pct": distances["close_vs_ma50_pct"], "distance_to_sma200_pct": distances["close_vs_ma200_pct"],
            "short_ma_structure": short_structure,
            "max_ma_spread_pct": ma_spread,
            "ma_entangled_threshold_pct": MA_ENTANGLED_SPREAD_PCT,
            "rsi14": rsi, "macd": macd, "macd_signal": macds, "macd_histogram": macdh, "macd_histogram_change_5d": macdh_change,
            "adx14": adx14, "plus_di14": plus_di, "minus_di14": minus_di, "di_spread": di_spread,
            "atr14": atr14, "atr_pct": atr_pct,
            "boll_upper": finite(stock["boll_ub"].iloc[-1]), "boll_middle": finite(stock["boll"].iloc[-1]), "boll_lower": finite(stock["boll_lb"].iloc[-1]),
            "volume_latest": latest_volume, "volume_5d_average": volume_5_avg, "volume_20d_average": volume_20_avg,
            "volume_ratio_5d": volume_ratio_5, "volume_ratio_20d": volume_ratio_20, "volume_ratio": volume_ratio_20,
            "up_day_ratio_20d": up_ratios[20], "up_day_ratio_60d": up_ratios[60],
            "volatility_20d_pct": volatility[20], "volatility_60d_pct": volatility[60],
            "max_drawdown_20d_pct": max_dd[20], "max_drawdown_60d_pct": max_dd[60], "max_drawdown_120d_pct": max_dd[120],
            "drawdown_20d_pct": max_dd[20], "drawdown_60d_pct": max_dd[60],
            **distances_path,
            "market_data_mode": "database_only", "market_data_source": source, "market_provider_call_count": provider_calls,
        }
        trend_result = {
            "return_trend": {"score": return_score, "period_scores": bucket_scores, "weights": RETURN_WEIGHTS, "missing_periods_reweighted": True},
            "short_ma_structure": {"classification": short_structure, "score": short_ma_score, "entangled_threshold_pct": MA_ENTANGLED_SPREAD_PCT},
            "medium_ma_structure": {"score": medium_ma_score},
            "momentum_status": {"score": momentum_score, "rsi_extremes_are_risk_not_direction_reversal": True},
            "trend_strength_status": {"classification": trend_strength, "adx_classification": adx_status, "adx_is_strength_not_direction": True},
            "volume_confirmation": {"score": volume_confirmation_score},
            "path_quality": {"classification": path_quality},
            "price_structure_score": short_ma_score,
            "moving_average_score": medium_ma_score,
            "momentum_score": momentum_score,
            "return_score": return_score,
            "volume_score": volume_confirmation_score,
            "volatility_penalty": volatility_risk,
            "drawdown_penalty": drawdown_risk,
            "overextension_risk": overextension_risk,
            "data_quality_risk": data_quality_risk,
            "technical_score": technical_score,
            "technical_risk_score": technical_risk_score,
            "short_term_trend": classify_trend(short_score),
            "medium_term_trend": classify_trend(medium_score),
            "long_term_trend": long_term,
            "deterministic_trend": classify_trend(technical_score),
            "scoring_rule": "0.45*return+0.25*short_ma+0.10*medium_ma+0.10*momentum+0.10*volume; risk=0.35*volatility+0.35*drawdown+0.15*overextension+0.15*data_quality",
            "trend_thresholds": TREND_THRESHOLDS,
            "calibration_status": "ENGINEERING_RULE_NOT_BACKTEST_CALIBRATED",
            "positive_evidence": [], "negative_evidence": [], "invalidation_candidates": [], "risk_candidates": [], "follow_up_candidates": [],
        }
        evidence_index: dict[str, dict[str, Any]] = {}
        for period, metric in returns.items():
            evidence_index[f"market.returns.return_{period}d_pct"] = _record(metric["value_pct"], "percent", cutoff, status=metric["status"])
        evidence_index.update({
            "market.price.latest_raw_close": _record(raw_close, "CNY", cutoff, basis="raw"),
            "market.price.latest_adjusted_close": _record(adjusted_close, "CNY", cutoff),
            "market.moving_averages.short_structure": _record(short_structure, "enum", cutoff),
            **{f"market.moving_averages.ma{window}": _record(value, "CNY", cutoff) for window, value in ma_values.items()},
            **{f"market.moving_averages.{key}": _record(value, "percent", cutoff) for key, value in slopes.items()},
            **{f"market.moving_averages.{key}": _record(value, "percent", cutoff) for key, value in distances.items()},
            "market.momentum.rsi14": _record(rsi, "index", cutoff),
            "market.momentum.macd_histogram": _record(macdh, "CNY", cutoff),
            "market.momentum.macd_histogram_change_5d": _record(macdh_change, "CNY", cutoff),
            "market.trend_strength.adx14": _record(adx14, "index", cutoff),
            "market.trend_strength.plus_di14": _record(plus_di, "index", cutoff),
            "market.trend_strength.minus_di14": _record(minus_di, "index", cutoff),
            "market.trend_strength.di_spread": _record(di_spread, "index", cutoff),
            "market.trend_strength.atr_pct": _record(atr_pct, "percent", cutoff),
            "market.volume.volume_ratio_5d": _record(volume_ratio_5, "ratio", cutoff, basis="not_applicable"),
            "market.volume.volume_ratio_20d": _record(volume_ratio_20, "ratio", cutoff, basis="not_applicable"),
            "market.path_risk.up_day_ratio_20d": _record(up_ratios[20], "ratio", cutoff),
            "market.path_risk.up_day_ratio_60d": _record(up_ratios[60], "ratio", cutoff),
            "market.path_risk.volatility_20d_pct": _record(volatility[20], "percent", cutoff),
            "market.path_risk.volatility_60d_pct": _record(volatility[60], "percent", cutoff),
            "market.path_risk.max_drawdown_20d_pct": _record(max_dd[20], "percent", cutoff),
            "market.path_risk.max_drawdown_60d_pct": _record(max_dd[60], "percent", cutoff),
            "market.path_risk.max_drawdown_120d_pct": _record(max_dd[120], "percent", cutoff),
            **{f"market.path_risk.{key}": _record(value, "percent", cutoff) for key, value in distances_path.items()},
            "market.classification.technical_score": _record(technical_score, "score", cutoff),
            "market.classification.technical_risk_score": _record(technical_risk_score, "score", cutoff),
            "market.classification.deterministic_trend": _record(classify_trend(technical_score), "enum", cutoff),
            "fundamentals.status": _record("FUNDAMENTALS_UNAVAILABLE", "enum", cutoff, basis="not_applicable"),
            "news.status": _record("SUCCESS_NO_DATA", "enum", cutoff, basis="not_applicable"),
        })
        evidence_package = {
            "schema_version": EVIDENCE_SCHEMA_VERSION,
            "symbol": symbol, "name": name, "analysis_date": analysis_date, "data_cutoff": cutoff,
            "price_basis": adjusted.audit,
            "returns": market_input["returns"],
            "moving_averages": {**{f"ma{k}": v for k, v in ma_values.items()}, **slopes, **distances, "short_structure": short_structure, "max_ma_spread_pct": ma_spread},
            "momentum": {"rsi14": rsi, "macd": macd, "macd_signal": macds, "macd_histogram": macdh, "macd_histogram_change_5d": macdh_change},
            "trend_strength": {"adx14": adx14, "plus_di14": plus_di, "minus_di14": minus_di, "di_spread": di_spread, "classification": adx_status},
            "volume": {"latest": latest_volume, "average_5d_previous": volume_5_avg, "average_20d_previous": volume_20_avg, "ratio_5d": volume_ratio_5, "ratio_20d": volume_ratio_20},
            "path_risk": {"up_day_ratio_20d": up_ratios[20], "up_day_ratio_60d": up_ratios[60], "volatility_20d_pct": volatility[20], "volatility_60d_pct": volatility[60], **{f"max_drawdown_{k}d_pct": v for k, v in max_dd.items()}, **distances_path},
            "deterministic_classification": trend_result,
            "fundamentals": {"status": "FUNDAMENTALS_UNAVAILABLE", "signal": "INSUFFICIENT_DATA"},
            "news": {"status": "SUCCESS_NO_DATA", "signal": "INSUFFICIENT_DATA"},
            "data_quality": {"price_adjustment_status": adjusted.audit["price_adjustment_status"], "evidence_coverage": 0.55},
            "warnings": adjusted.audit["warnings"] + ["基本面不可用", "新闻无数据", "工程规则尚未历史校准"],
            "evidence_index": evidence_index,
        }
        return EvidenceEngineResult(market_input, adjusted.audit, trend_result, evidence_package)
