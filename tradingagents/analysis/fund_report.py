from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session
from stockstats import wrap

from tradingagents.storage.data_service import MarketDataService, SUCCESS
from tradingagents.storage.models import (
    FundHoldingPosition,
    FundHoldingReport,
    FundInstrumentRelation,
    Instrument,
)


SCHEMA_VERSION = "1.0"
FUND_NOT_FOUND = "FUND_NOT_FOUND"
HOLDING_REPORT_NOT_FOUND = "HOLDING_REPORT_NOT_FOUND"
MARKET_DATA_UNAVAILABLE = "MARKET_DATA_UNAVAILABLE"
INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"
REPORT_ALREADY_EXISTS = "REPORT_ALREADY_EXISTS"
REPORT_RENDER_ERROR = "REPORT_RENDER_ERROR"


class FundReportError(RuntimeError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


@dataclass
class WeightedMetric:
    value: float | None
    valid_holding_count: int
    valid_weight_pct: float
    missing_weight_pct: float


@dataclass
class FundHoldingAnalysis:
    symbol: str
    name: str
    rank: int
    weight_pct: float
    daily_row_count: int = 0
    first_market_date: str | None = None
    latest_market_date: str | None = None
    latest_close: float | None = None
    return_5d_pct: float | None = None
    return_20d_pct: float | None = None
    return_60d_pct: float | None = None
    sma20: float | None = None
    sma50: float | None = None
    sma200: float | None = None
    ema10: float | None = None
    rsi14: float | None = None
    macd: float | None = None
    macd_signal: float | None = None
    macd_histogram: float | None = None
    atr14: float | None = None
    atr_pct: float | None = None
    boll_upper: float | None = None
    boll_middle: float | None = None
    boll_lower: float | None = None
    price_vs_sma20_pct: float | None = None
    price_vs_sma50_pct: float | None = None
    price_vs_sma200_pct: float | None = None
    trend_status: str = "UNKNOWN"
    momentum_status: str = "UNKNOWN"
    volatility_status: str = "UNKNOWN"
    data_status: str = MARKET_DATA_UNAVAILABLE
    error_message: str | None = None
    holding_return_contribution_proxy: float | None = None
    source: str | None = None
    provider_call_count: int = 0


@dataclass
class ProxyAnalysis:
    relationship_type: str
    symbol: str
    name: str
    weight_pct: float
    technical_metrics: FundHoldingAnalysis
    technical_status: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "relationship_type": self.relationship_type,
            "symbol": self.symbol,
            "name": self.name,
            "weight_pct": self.weight_pct,
            "technical_metrics": asdict(self.technical_metrics),
            "technical_status": self.technical_status,
        }


@dataclass
class FundAnalysisResult:
    fund_code: str
    fund_name: str
    report_period_end: str
    published_date: str
    analysis_date: str
    market_data_end_date: str | None
    holding_count: int
    successful_count: int
    partial_count: int
    failed_count: int
    insufficient_history_count: int
    top10_weight_pct: float
    analyzed_weight_pct: float
    missing_weight_pct: float
    weighted_return_5d_pct: WeightedMetric
    weighted_return_20d_pct: WeightedMetric
    weighted_return_60d_pct: WeightedMetric
    weighted_rsi14: WeightedMetric
    weighted_macd_histogram: WeightedMetric
    weighted_atr_pct: WeightedMetric
    weight_above_sma20_pct: WeightedMetric
    weight_above_sma50_pct: WeightedMetric
    weight_above_sma200_pct: WeightedMetric
    bullish_weight_pct: WeightedMetric
    neutral_weight_pct: WeightedMetric
    bearish_weight_pct: WeightedMetric
    top3_concentration_pct: float
    top5_concentration_pct: float
    herfindahl_index: float
    concentration_status: str
    data_quality_status: str
    overall_technical_status: str
    data_mode: str
    data_source: str
    provider_call_count: int
    generated_at: str
    warnings: list[str] = field(default_factory=list)
    holdings: list[FundHoldingAnalysis] = field(default_factory=list)
    fund_type: str = "active_equity"
    proxy_analysis: ProxyAnalysis | None = None

    def to_dict(self) -> dict[str, Any]:
        aggregates = {
            name: asdict(getattr(self, name))
            for name in (
                "weighted_return_5d_pct",
                "weighted_return_20d_pct",
                "weighted_return_60d_pct",
                "weighted_rsi14",
                "weighted_macd_histogram",
                "weighted_atr_pct",
                "weight_above_sma20_pct",
                "weight_above_sma50_pct",
                "weight_above_sma200_pct",
                "bullish_weight_pct",
                "neutral_weight_pct",
                "bearish_weight_pct",
            )
        }
        result = {
            "schema_version": SCHEMA_VERSION,
            "fund_type": self.fund_type,
            "fund": {"fund_code": self.fund_code, "fund_name": self.fund_name},
            "report_metadata": {
                "report_period_end": self.report_period_end,
                "published_date": self.published_date,
                "analysis_date": self.analysis_date,
                "market_data_end_date": self.market_data_end_date,
                "data_mode": self.data_mode,
                "data_source": self.data_source,
                "provider_call_count": self.provider_call_count,
                "generated_at": self.generated_at,
            },
            "data_quality": {
                "holding_count": self.holding_count,
                "successful_count": self.successful_count,
                "partial_count": self.partial_count,
                "failed_count": self.failed_count,
                "insufficient_history_count": self.insufficient_history_count,
                "top10_weight_pct": self.top10_weight_pct,
                "analyzed_weight_pct": self.analyzed_weight_pct,
                "missing_weight_pct": self.missing_weight_pct,
                "status": self.data_quality_status,
            },
            "aggregate_metrics": {
                **aggregates,
                "overall_technical_status": self.overall_technical_status,
            },
            "concentration": {
                "top3_concentration_pct": self.top3_concentration_pct,
                "top5_concentration_pct": self.top5_concentration_pct,
                "top10_weight_pct": self.top10_weight_pct,
                "herfindahl_index": self.herfindahl_index,
                "normalization": "weights normalized within disclosed top ten",
                "status": self.concentration_status,
            },
            "holdings": [asdict(item) for item in self.holdings],
            "warnings": list(self.warnings),
        }
        if self.fund_type == "etf_feeder" and self.proxy_analysis is not None:
            result["proxy_analysis"] = self.proxy_analysis.to_dict()
            result["direct_holdings_analysis"] = {
                "holding_count": self.holding_count,
                "successful_count": self.successful_count,
                "failed_count": self.failed_count,
                "total_weight_pct": self.top10_weight_pct,
                "data_quality_status": self.data_quality_status,
                "aggregate_metrics": aggregates,
                "concentration": {
                    "top3_concentration_pct": self.top3_concentration_pct,
                    "top5_concentration_pct": self.top5_concentration_pct,
                    "herfindahl_index": self.herfindahl_index,
                    "status": self.concentration_status,
                },
                "holdings": [asdict(item) for item in self.holdings],
                "scope": "direct_disclosed_stocks_only",
            }
        return result


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def calculate_trading_return(close: pd.Series, periods: int) -> float | None:
    values = pd.to_numeric(close, errors="coerce").dropna()
    if len(values) < periods + 1:
        return None
    return (float(values.iloc[-1]) / float(values.iloc[-periods - 1]) - 1.0) * 100.0


def classify_trend(latest: float | None, sma20: float | None, sma50: float | None, sma200: float | None) -> str:
    if None in (latest, sma20, sma50):
        return "UNKNOWN"
    if sma200 is not None and latest > sma20 > sma50 > sma200:
        return "STRONG_UPTREND"
    if sma200 is not None and latest < sma20 < sma50 < sma200:
        return "STRONG_DOWNTREND"
    if latest > sma20 and sma20 > sma50:
        return "UPTREND"
    if latest < sma20 and sma20 < sma50:
        return "DOWNTREND"
    return "NEUTRAL"


def classify_momentum(rsi14: float | None, macd_histogram: float | None) -> str:
    if rsi14 is None or macd_histogram is None:
        return "UNKNOWN"
    if rsi14 >= 70:
        return "OVERBOUGHT"
    if rsi14 <= 30:
        return "OVERSOLD"
    if rsi14 >= 55 and macd_histogram > 0:
        return "BULLISH"
    if rsi14 <= 45 and macd_histogram < 0:
        return "BEARISH"
    return "NEUTRAL"


def weighted_metric(holdings: list[FundHoldingAnalysis], field_name: str, top10_weight_pct: float) -> WeightedMetric:
    valid = [(h.weight_pct, _finite(getattr(h, field_name))) for h in holdings]
    valid = [(weight, value) for weight, value in valid if value is not None]
    valid_weight = sum(weight for weight, _ in valid)
    value = None
    if valid_weight > 0:
        value = sum((weight / 100.0) * value for weight, value in valid) / (valid_weight / 100.0)
    return WeightedMetric(value, len(valid), valid_weight, max(0.0, top10_weight_pct - valid_weight))


def weighted_condition(holdings: list[FundHoldingAnalysis], field_name: str, predicate, top10_weight_pct: float) -> WeightedMetric:
    valid = [(h.weight_pct, _finite(getattr(h, field_name))) for h in holdings]
    valid = [(weight, value) for weight, value in valid if value is not None]
    valid_weight = sum(weight for weight, _ in valid)
    matched_weight = sum(weight for weight, value in valid if predicate(value))
    return WeightedMetric(matched_weight, len(valid), valid_weight, max(0.0, top10_weight_pct - valid_weight))


def weighted_status(holdings: list[FundHoldingAnalysis], statuses: set[str], top10_weight_pct: float) -> WeightedMetric:
    valid_statuses = {"BULLISH", "BEARISH", "NEUTRAL", "OVERBOUGHT", "OVERSOLD"}
    valid = [h for h in holdings if h.momentum_status in valid_statuses]
    valid_weight = sum(h.weight_pct for h in valid)
    value = sum(h.weight_pct for h in valid if h.momentum_status in statuses)
    return WeightedMetric(value, len(valid), valid_weight, max(0.0, top10_weight_pct - valid_weight))


def classify_data_quality(holdings: list[FundHoldingAnalysis], top10_weight_pct: float) -> str:
    usable = [h for h in holdings if h.latest_close is not None]
    analyzed_weight = sum(h.weight_pct for h in usable)
    coverage = analyzed_weight / top10_weight_pct if top10_weight_pct else 0.0
    usable_ratio = len(usable) / len(holdings) if holdings else 0.0
    if coverage < 0.70 or usable_ratio < 0.70:
        return "POOR"
    latest = [pd.Timestamp(h.latest_market_date) for h in usable if h.latest_market_date]
    aligned = True
    if latest:
        business_gap = max(0, len(pd.bdate_range(min(latest), max(latest))) - 1)
        aligned = business_gap <= 1
    all_success = all(h.data_status == "SUCCESS" for h in holdings)
    if all_success and coverage >= 0.95 and aligned:
        return "GOOD"
    return "PARTIAL"


def classify_concentration(hhi: float) -> str:
    # Fixed thresholds for HHI normalized within the disclosed top ten.
    if hhi < 0.12:
        return "LOW"
    if hhi < 0.18:
        return "MEDIUM"
    return "HIGH"


def classify_overall(
    quality: str,
    bullish: WeightedMetric,
    bearish: WeightedMetric,
    above20: WeightedMetric,
    above50: WeightedMetric,
    rsi: WeightedMetric,
    macd_hist: WeightedMetric,
) -> str:
    if quality == "POOR" or any(x.value is None for x in (above20, above50, rsi, macd_hist)):
        return "INSUFFICIENT_DATA"
    bull = bullish.value or 0.0
    bear = bearish.value or 0.0
    if bull >= 60 and above20.value >= 60 and macd_hist.value > 0:
        return "BULLISH"
    if bear >= 60 and above20.value <= 40 and macd_hist.value < 0:
        return "BEARISH"
    score = 0
    score += 2 if bull - bear >= 20 else -2 if bear - bull >= 20 else 0
    score += 1 if above20.value >= 60 else -1 if above20.value <= 40 else 0
    score += 1 if above50.value >= 60 else -1 if above50.value <= 40 else 0
    score += 1 if macd_hist.value > 0 else -1 if macd_hist.value < 0 else 0
    score += 1 if rsi.value >= 55 else -1 if rsi.value <= 45 else 0
    if score >= 4:
        return "BULLISH"
    if score >= 2:
        return "SLIGHTLY_BULLISH"
    if score <= -4:
        return "BEARISH"
    if score <= -2:
        return "SLIGHTLY_BEARISH"
    return "NEUTRAL"


def classify_proxy_technical_status(proxy: FundHoldingAnalysis | None) -> str:
    if proxy is None or proxy.latest_close is None:
        return "INSUFFICIENT_DATA"
    if proxy.trend_status in {"STRONG_UPTREND", "UPTREND"}:
        return "BULLISH" if proxy.momentum_status in {"BULLISH", "OVERBOUGHT"} else "SLIGHTLY_BULLISH"
    if proxy.trend_status in {"STRONG_DOWNTREND", "DOWNTREND"}:
        return "BEARISH" if proxy.momentum_status in {"BEARISH", "OVERSOLD"} else "SLIGHTLY_BEARISH"
    if proxy.momentum_status in {"BULLISH", "OVERBOUGHT"}:
        return "SLIGHTLY_BULLISH"
    if proxy.momentum_status in {"BEARISH", "OVERSOLD"}:
        return "SLIGHTLY_BEARISH"
    return "NEUTRAL"


class FundReportService:
    def __init__(self, session: Session, mode: str = "database_only", provider=None):
        self.session = session
        self.mode = mode
        self.provider = provider

    def _load_fund(self, fund_code: str):
        fund = self.session.scalar(
            select(Instrument).where(
                Instrument.local_code == fund_code,
                Instrument.instrument_type == "fund",
            )
        )
        if fund is None:
            raise FundReportError(FUND_NOT_FOUND, fund_code)
        report = self.session.scalar(
            select(FundHoldingReport)
            .where(FundHoldingReport.fund_instrument_id == fund.id)
            .order_by(FundHoldingReport.report_period_end.desc())
        )
        if report is None:
            raise FundReportError(HOLDING_REPORT_NOT_FOUND, fund_code)
        rows = self.session.execute(
            select(FundHoldingPosition, Instrument)
            .join(Instrument, Instrument.id == FundHoldingPosition.stock_instrument_id)
            .where(FundHoldingPosition.report_id == report.id)
            .order_by(FundHoldingPosition.rank)
        ).all()
        return fund, report, rows

    def _load_proxy(self, fund: Instrument, report: FundHoldingReport):
        return self.session.execute(
            select(FundInstrumentRelation, Instrument)
            .join(
                Instrument,
                Instrument.id == FundInstrumentRelation.related_instrument_id,
            )
            .where(
                FundInstrumentRelation.fund_instrument_id == fund.id,
                FundInstrumentRelation.relationship_type == "target_etf",
                FundInstrumentRelation.report_period_end == report.report_period_end,
            )
            .order_by(FundInstrumentRelation.id.desc())
        ).first()

    def _analyze_holding(self, position: FundHoldingPosition, stock: Instrument, analysis_date: str) -> FundHoldingAnalysis:
        item = FundHoldingAnalysis(
            symbol=stock.symbol,
            name=stock.name or stock.symbol,
            rank=position.rank,
            weight_pct=float(position.weight_pct or 0.0),
        )
        try:
            result = MarketDataService(
                self.session,
                mode=self.mode,
                provider=self.provider,
                include_unfinished_daily_bar=False,
                persist_provider_results=self.mode == "database_first",
            ).daily(stock.symbol, "1900-01-01", analysis_date)
            item.source = result.source
            item.provider_call_count = result.provider_call_count
            if result.status != SUCCESS or result.data.empty:
                item.data_status = MARKET_DATA_UNAVAILABLE
                item.error_message = f"{result.status}: {result.message}"
                return item
            bars = result.data.sort_index()
            item.daily_row_count = len(bars)
            item.first_market_date = bars.index[0].date().isoformat()
            item.latest_market_date = bars.index[-1].date().isoformat()
            item.latest_close = _finite(bars["Close"].iloc[-1])
            item.return_5d_pct = calculate_trading_return(bars["Close"], 5)
            item.return_20d_pct = calculate_trading_return(bars["Close"], 20)
            item.return_60d_pct = calculate_trading_return(bars["Close"], 60)

            stock_frame = bars.reset_index().rename(columns={"index": "Date"})
            stats = wrap(stock_frame)
            indicators = {
                "sma20": "close_20_sma",
                "sma50": "close_50_sma",
                "sma200": "close_200_sma",
                "ema10": "close_10_ema",
                "rsi14": "rsi_14",
                "macd": "macd",
                "macd_signal": "macds",
                "macd_histogram": "macdh",
                "atr14": "atr_14",
                "boll_upper": "boll_ub",
                "boll_middle": "boll",
                "boll_lower": "boll_lb",
            }
            for target, indicator in indicators.items():
                try:
                    stats[indicator]
                    setattr(item, target, _finite(stats[indicator].iloc[-1]))
                except Exception:
                    setattr(item, target, None)
            if item.latest_close:
                item.atr_pct = item.atr14 / item.latest_close * 100 if item.atr14 is not None else None
                for target, sma in (
                    ("price_vs_sma20_pct", item.sma20),
                    ("price_vs_sma50_pct", item.sma50),
                    ("price_vs_sma200_pct", item.sma200),
                ):
                    setattr(item, target, (item.latest_close / sma - 1) * 100 if sma else None)
            item.trend_status = classify_trend(item.latest_close, item.sma20, item.sma50, item.sma200)
            item.momentum_status = classify_momentum(item.rsi14, item.macd_histogram)
            item.holding_return_contribution_proxy = (
                item.weight_pct / 100.0 * item.return_20d_pct
                if item.return_20d_pct is not None
                else None
            )
            if len(bars) < 61:
                item.data_status = INSUFFICIENT_HISTORY
                item.error_message = f"required_rows=61, available_rows={len(bars)}"
            elif any(getattr(item, name) is None for name in ("sma20", "sma50", "rsi14", "macd_histogram", "atr14")):
                item.data_status = "PARTIAL"
            elif item.sma200 is None:
                item.data_status = "PARTIAL"
                item.error_message = f"SMA200 unavailable; available_rows={len(bars)}"
            else:
                item.data_status = "SUCCESS"
        except Exception as exc:
            item.data_status = "FAILED"
            item.error_message = f"{type(exc).__name__}: {exc}"
        return item

    def analyze(self, fund_code: str, analysis_date: str) -> FundAnalysisResult:
        analysis_ts = pd.Timestamp(analysis_date)
        fund, report, position_rows = self._load_fund(fund_code)
        holdings = [self._analyze_holding(position, stock, analysis_ts.date().isoformat()) for position, stock in position_rows]
        proxy_row = self._load_proxy(fund, report)
        proxy_analysis = None
        if proxy_row is not None:
            relation, proxy_instrument = proxy_row
            proxy_holding = self._analyze_holding(
                SimpleNamespace(rank=0, weight_pct=relation.weight_pct),
                proxy_instrument,
                analysis_ts.date().isoformat(),
            )
            proxy_analysis = ProxyAnalysis(
                relationship_type=relation.relationship_type,
                symbol=proxy_instrument.symbol,
                name=proxy_instrument.name or proxy_instrument.symbol,
                weight_pct=float(relation.weight_pct or 0.0),
                technical_metrics=proxy_holding,
                technical_status=classify_proxy_technical_status(proxy_holding),
            )
        if not any(item.latest_close is not None for item in holdings):
            raise FundReportError(MARKET_DATA_UNAVAILABLE, "all disclosed holdings failed")

        atr_values = [item.atr_pct for item in holdings if item.atr_pct is not None]
        if len(atr_values) >= 3:
            low, high = pd.Series(atr_values).quantile([0.33, 0.67]).tolist()
            for item in holdings:
                if item.atr_pct is None:
                    item.volatility_status = "UNKNOWN"
                elif item.atr_pct <= low:
                    item.volatility_status = "LOW"
                elif item.atr_pct >= high:
                    item.volatility_status = "HIGH"
                else:
                    item.volatility_status = "MEDIUM"

        top10_weight = sum(item.weight_pct for item in holdings)
        analyzed_weight = sum(item.weight_pct for item in holdings if item.latest_close is not None)
        metric = lambda name: weighted_metric(holdings, name, top10_weight)
        above20 = weighted_condition(holdings, "price_vs_sma20_pct", lambda x: x > 0, top10_weight)
        above50 = weighted_condition(holdings, "price_vs_sma50_pct", lambda x: x > 0, top10_weight)
        above200 = weighted_condition(holdings, "price_vs_sma200_pct", lambda x: x > 0, top10_weight)
        bullish = weighted_status(holdings, {"BULLISH", "OVERBOUGHT"}, top10_weight)
        bearish = weighted_status(holdings, {"BEARISH", "OVERSOLD"}, top10_weight)
        neutral = weighted_status(holdings, {"NEUTRAL"}, top10_weight)
        weighted_rsi = metric("rsi14")
        weighted_hist = metric("macd_histogram")
        quality = classify_data_quality(holdings, top10_weight)
        weights = sorted((item.weight_pct for item in holdings), reverse=True)
        hhi = sum((weight / top10_weight) ** 2 for weight in weights) if top10_weight else 0.0
        fund_type = "etf_feeder" if proxy_analysis is not None else "active_equity"
        overall = (
            proxy_analysis.technical_status
            if proxy_analysis is not None
            else classify_overall(quality, bullish, bearish, above20, above50, weighted_rsi, weighted_hist)
        )

        warnings = ["基金持仓来自定期报告，可能与当前真实持仓存在差异。"]
        age_days = (analysis_ts.normalize() - pd.Timestamp(report.report_period_end)).days
        if age_days > 90:
            warnings.append(f"持仓报告期距分析日已 {age_days} 天，披露持仓可能已经变化。")
        if quality != "GOOD":
            warnings.append(f"数据质量状态为 {quality}，聚合指标需结合有效权重覆盖率解读。")
        if any(item.data_status != "SUCCESS" for item in holdings):
            warnings.append("部分持仓存在指标历史不足或行情失败，缺失值未按零处理。")
        if fund_type == "etf_feeder":
            warnings.append("本基金为 ETF 联接基金，目标 ETF 是主要技术分析代理；直接股票仅作补充分析。")
        all_analysis = holdings + ([proxy_analysis.technical_metrics] if proxy_analysis else [])
        sources = sorted({item.source for item in all_analysis if item.source})
        latest_dates = [item.latest_market_date for item in all_analysis if item.latest_market_date]
        return FundAnalysisResult(
            fund_code=fund_code,
            fund_name=fund.name or fund_code,
            report_period_end=report.report_period_end,
            published_date=report.published_date,
            analysis_date=analysis_ts.date().isoformat(),
            market_data_end_date=max(latest_dates) if latest_dates else None,
            holding_count=len(holdings),
            successful_count=sum(item.data_status == "SUCCESS" for item in holdings),
            partial_count=sum(item.data_status == "PARTIAL" for item in holdings),
            failed_count=sum(item.data_status in {"FAILED", MARKET_DATA_UNAVAILABLE} for item in holdings),
            insufficient_history_count=sum(item.data_status == INSUFFICIENT_HISTORY for item in holdings),
            top10_weight_pct=top10_weight,
            analyzed_weight_pct=analyzed_weight,
            missing_weight_pct=max(0.0, top10_weight - analyzed_weight),
            weighted_return_5d_pct=metric("return_5d_pct"),
            weighted_return_20d_pct=metric("return_20d_pct"),
            weighted_return_60d_pct=metric("return_60d_pct"),
            weighted_rsi14=weighted_rsi,
            weighted_macd_histogram=weighted_hist,
            weighted_atr_pct=metric("atr_pct"),
            weight_above_sma20_pct=above20,
            weight_above_sma50_pct=above50,
            weight_above_sma200_pct=above200,
            bullish_weight_pct=bullish,
            neutral_weight_pct=neutral,
            bearish_weight_pct=bearish,
            top3_concentration_pct=sum(weights[:3]),
            top5_concentration_pct=sum(weights[:5]),
            herfindahl_index=hhi,
            concentration_status=classify_concentration(hhi),
            data_quality_status=quality,
            overall_technical_status=overall,
            data_mode=self.mode,
            data_source=",".join(sources) or "unavailable",
            provider_call_count=sum(item.provider_call_count for item in all_analysis),
            generated_at=datetime.now(timezone.utc).isoformat(),
            warnings=warnings,
            holdings=holdings,
            fund_type=fund_type,
            proxy_analysis=proxy_analysis,
        )
