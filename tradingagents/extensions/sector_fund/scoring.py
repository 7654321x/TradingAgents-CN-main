"""Versioned deterministic scoring for sector-fund metrics.

The scorer deliberately consumes already-audited facts only.  It does not
fetch data, infer missing values, or ask an LLM to fill a scoring input.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field
from typing import Any

import pandas as pd

from .quant_metrics import COMPLETE, QuantMetricsResult

SCORING_VERSION = "sector_fund_score_v2"
MINIMUM_SCORE_COVERAGE_PCT = 80.0

CORE_LABEL_THRESHOLDS = (
    (90.0, "STRONG_TREND_OVERHEATED"),
    (80.0, "STRONG_TREND"),
    (70.0, "TREND_REPAIR"),
    (60.0, "RANGE_BOUND"),
    (50.0, "SLIGHTLY_WEAK"),
    (0.0, "WEAK_DOWNWARD"),
)
SHORT_LABEL_THRESHOLDS = (
    (90.0, "OVERHEATED"),
    (80.0, "STRONG"),
    (70.0, "SLIGHTLY_STRONG"),
    (60.0, "RANGE_BOUND"),
    (50.0, "SLIGHTLY_WEAK"),
    (0.0, "WEAK"),
)


@dataclass(frozen=True)
class RuleResult:
    rule: str
    raw_value: Any
    points: float | None
    max_points: float
    status: str


@dataclass(frozen=True)
class DimensionResult:
    dimension: str
    score: float | None
    max_score: float
    raw_points: float
    available_max_points: float
    coverage_pct: float
    rules: tuple[RuleResult, ...]


@dataclass(frozen=True)
class ScoreResult:
    score: float | None
    label: str
    scoring_coverage_pct: float
    dimensions: tuple[DimensionResult, ...]


@dataclass(frozen=True)
class ConfidenceResult:
    confidence_pct: float
    scoring_coverage_pct: float
    sector_data_coverage_pct: float
    market_freshness_factor: float
    weight_freshness_factor: float
    formula_version: str = "data_confidence_v2"
    interpretation: str = "数据质量覆盖度，不是收益预测概率或收益保证"


@dataclass(frozen=True)
class SectorFundScoredReport:
    schema_version: str
    scoring_version: str
    input_hash: str
    metrics: dict[str, Any]
    core_trend: ScoreResult
    short_term: ScoreResult
    data_confidence: ConfidenceResult
    conflicts: tuple[str, ...]
    historical_adjustment: dict[str, str]
    probability_output: dict[str, str]
    tool_adaptation: dict[str, dict[str, str]]
    fund_context: dict[str, Any]
    daily_observation: dict[str, Any] = field(default_factory=dict)
    llm_explanation: dict[str, Any] = field(
        default_factory=lambda: {
            "status": "DISABLED",
            "reason": "LLM explanation was not explicitly requested",
            "network_call_count": 0,
        }
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _rule(name: str, value: Any, maximum: float, evaluator: Callable[[Any], float]) -> RuleResult:
    if value is None or (isinstance(value, float) and not pd.notna(value)):
        return RuleResult(name, None, None, maximum, "MISSING")
    points = min(max(float(evaluator(value)), 0.0), maximum)
    return RuleResult(name, value, points, maximum, "AVAILABLE")


def _binary(name: str, value: Any, maximum: float, predicate: Callable[[Any], bool]) -> RuleResult:
    return _rule(name, value, maximum, lambda item: maximum if predicate(item) else 0.0)


def _dimension(name: str, maximum: float, rules: list[RuleResult]) -> DimensionResult:
    available = [rule for rule in rules if rule.points is not None]
    available_max = sum(rule.max_points for rule in available)
    raw = sum(rule.points or 0 for rule in available)
    total_rule_max = sum(rule.max_points for rule in rules)
    return DimensionResult(
        dimension=name,
        score=raw / available_max * maximum if available_max else None,
        max_score=maximum,
        raw_points=raw,
        available_max_points=available_max,
        coverage_pct=available_max / total_rule_max * 100 if total_rule_max else 0.0,
        rules=tuple(rules),
    )


def _label(score: float | None, thresholds: tuple[tuple[float, str], ...]) -> str:
    if score is None:
        return "INSUFFICIENT_DATA"
    return next(label for threshold, label in thresholds if score >= threshold)


def _score(
    dimensions: list[DimensionResult], thresholds: tuple[tuple[float, str], ...]
) -> ScoreResult:
    available = [dimension for dimension in dimensions if dimension.score is not None]
    available_max = sum(dimension.max_score for dimension in available)
    score = (
        sum(dimension.score or 0 for dimension in available) / available_max * 100
        if available_max
        else None
    )
    rule_max = sum(sum(rule.max_points for rule in dimension.rules) for dimension in dimensions)
    rule_available = sum(dimension.available_max_points for dimension in dimensions)
    return ScoreResult(
        score=score,
        label=_label(score, thresholds),
        scoring_coverage_pct=rule_available / rule_max * 100 if rule_max else 0.0,
        dimensions=tuple(dimensions),
    )


def _gated(score: ScoreResult, *, thresholds: tuple[tuple[float, str], ...]) -> ScoreResult:
    """Keep transparent module detail while withholding an unreliable total."""
    if score.score is None or score.scoring_coverage_pct < MINIMUM_SCORE_COVERAGE_PCT:
        return ScoreResult(None, "INSUFFICIENT_DATA", score.scoring_coverage_pct, score.dimensions)
    return ScoreResult(score.score, _label(score.score, thresholds), score.scoring_coverage_pct, score.dimensions)


def _breadth_values(metrics: QuantMetricsResult) -> tuple[float | None, float | None, float | None]:
    sector = metrics.sector
    decided = sector.advancers + sector.decliners + sector.unchanged
    advance_ratio = sector.advancers / decided * 100 if decided else None
    return advance_ratio, sector.equal_weight_return_pct, sector.index_weighted_return_pct


def _top10(metrics: QuantMetricsResult) -> list[Any]:
    return sorted(metrics.sector.constituents, key=lambda item: item.weight_pct, reverse=True)[:10]


def _top10_values(metrics: QuantMetricsResult) -> tuple[float | None, float | None, float | None, float | None]:
    rows = _top10(metrics)
    if not rows:
        return None, None, None, None
    total_weight = sum(row.weight_pct for row in rows)
    contribution = [row.weighted_contribution_pct for row in rows if row.weighted_contribution_pct is not None]
    positive_weight = sum(row.weight_pct for row in rows if row.return_1d_pct is not None and row.return_1d_pct > 0)
    amounts = [row.amount for row in rows if row.amount is not None]
    positive_contribution_weight = (
        sum(row.weight_pct for row in rows if row.weighted_contribution_pct is not None and row.weighted_contribution_pct > 0)
        if contribution
        else None
    )
    return (
        sum(contribution) if contribution else None,
        positive_weight / total_weight * 100 if total_weight and any(row.return_1d_pct is not None for row in rows) else None,
        positive_contribution_weight / total_weight * 100 if total_weight and positive_contribution_weight is not None else None,
        len(amounts) / len(rows) * 100 if rows else None,
    )


def _positive_chain_ratio(metrics: QuantMetricsResult) -> float | None:
    groups = metrics.sector.supply_chain_groups
    active = [group for group in groups if group.equal_weight_return_pct is not None]
    if not active:
        return None
    return sum(group.equal_weight_return_pct > 0 for group in active) / len(active) * 100


def _extended(context: Mapping[str, Any] | None, dataset: str) -> list[Mapping[str, Any]]:
    if not context:
        return []
    value = (context.get("extended_observations") or {}).get(dataset) or []
    return [item for item in value if isinstance(item, Mapping) and item.get("status") == "SUCCESS"]


def _etf_status(context: Mapping[str, Any] | None) -> Mapping[str, Any] | None:
    value = context.get("etf_status") if context else None
    return value if isinstance(value, Mapping) else None


def _fund_flow_coverage(context: Mapping[str, Any] | None) -> float | None:
    rows = _extended(context, "fund_flow")
    if not rows:
        return None
    symbols = {row.get("instrument_symbol") for row in rows if row.get("instrument_symbol")}
    return min(len(symbols) if symbols else len(rows), 10) / 10 * 100


def _financial_coverage(context: Mapping[str, Any] | None) -> float | None:
    rows = _extended(context, "financial")
    if not rows:
        return None
    symbols = {row.get("instrument_symbol") for row in rows if row.get("instrument_symbol")}
    return min(len(symbols) if symbols else len(rows), 10) / 10 * 100


def _confirmed_events(context: Mapping[str, Any] | None) -> list[Mapping[str, Any]] | None:
    if not context or context.get("event_scan_status") != "COMPLETE":
        return None
    events = context.get("recent_events_7d") or []
    return [
        item
        for item in events
        if isinstance(item, Mapping)
        and str(item.get("source_level", "")).upper() in {"A", "B"}
        and str(item.get("confirmation_status", "")).upper()
        not in {"UNAVAILABLE", "UNVERIFIED", "RUMOR"}
    ]


def _event_baseline(context: Mapping[str, Any] | None) -> float | None:
    events = _confirmed_events(context)
    # A neutral five-point baseline is only valid after a completed scan.  An
    # absent context remains missing rather than being silently treated as no news.
    if events is None:
        return None
    return 5.0


def _shares_change(context: Mapping[str, Any] | None) -> float | None:
    status = _etf_status(context)
    if not status or status.get("shares_change_status") != "AVAILABLE":
        return None
    value = status.get("shares_change_pct")
    return float(value) if value is not None else None


def _discount_rate(context: Mapping[str, Any] | None) -> float | None:
    status = _etf_status(context)
    if not status or status.get("discount_rate_pct") is None:
        return None
    return float(status["discount_rate_pct"])


def calculate_core_trend_score(
    metrics: QuantMetricsResult, fund_context: Mapping[str, Any] | None = None
) -> ScoreResult:
    """Calculate the confirmed 25/20/20/15/10/10 core score structure."""
    etf = metrics.etf
    advance_ratio, equal_return, weighted_return = _breadth_values(metrics)
    top10_contribution, top10_advance_weight, top10_positive_contribution, top10_amount_coverage = _top10_values(metrics)
    chain_positive_ratio = _positive_chain_ratio(metrics)
    financial_coverage = _financial_coverage(fund_context)
    # A single top-weight observation cannot stand in for the top-ten
    # fundamental module.  It remains visible in health data but is not an
    # available score input until the declared coverage threshold is met.
    usable_financial_coverage = financial_coverage if financial_coverage is not None and financial_coverage >= 80 else None
    cycle_rows = _extended(fund_context, "industry_cycle")
    event_baseline = _event_baseline(fund_context)
    dimensions = [
        _dimension("price_structure", 25, [
            _binary("close_above_sma5", etf.price_vs_sma5_pct, 3, lambda value: value > 0),
            _binary("close_above_sma10", etf.price_vs_sma10_pct, 4, lambda value: value > 0),
            _binary("close_above_sma20", etf.price_vs_sma20_pct, 6, lambda value: value > 0),
            _binary("sma5_sma10_sma20_bullish", None if None in {etf.sma5, etf.sma10, etf.sma20} else (etf.sma5 > etf.sma10 > etf.sma20), 5, bool),
            _binary("return_5d_positive", etf.return_5d_pct, 3, lambda value: value > 0),
            _binary("return_20d_positive", etf.return_20d_pct, 2, lambda value: value > 0),
            _rule("drawdown_20d_control", etf.drawdown_20d_pct, 2, lambda value: 2 if value >= -5 else 1 if value >= -10 else 0),
        ]),
        _dimension("funds_and_turnover", 20, [
            _binary("etf_amount_vs_5d", etf.amount_vs_5d_avg, 3, lambda value: value >= 1),
            _binary("etf_amount_vs_20d", etf.amount_vs_20d_avg, 3, lambda value: value >= 1),
            _binary("sector_amount_vs_5d", metrics.sector.amount_vs_5d_avg, 3, lambda value: value >= 1),
            _binary("sector_amount_vs_20d", metrics.sector.amount_vs_20d_avg, 3, lambda value: value >= 1),
            _rule("etf_share_change", _shares_change(fund_context), 4, lambda value: 4 if value > 0 else 2 if value == 0 else 0),
            _rule("etf_discount_control", _discount_rate(fund_context), 4, lambda value: 4 if abs(value) <= 1 else 2 if abs(value) <= 3 else 0),
        ]),
        _dimension("industry_chain_breadth", 20, [
            _rule("advance_ratio", advance_ratio, 6, lambda value: 6 if value >= 60 else 4 if value >= 50 else 2 if value >= 40 else 0),
            _binary("equal_weight_return_positive", equal_return, 4, lambda value: value > 0),
            _binary("index_weighted_return_positive", weighted_return, 4, lambda value: value > 0),
            _rule("positive_supply_chain_ratio", chain_positive_ratio, 4, lambda value: 4 if value >= 60 else 2 if value >= 40 else 0),
            _rule("constituent_price_coverage", metrics.sector.count_coverage_pct, 2, lambda value: 2 if value >= 95 else 1 if value >= 80 else 0),
        ]),
        _dimension("core_weight_performance", 15, [
            _binary("top10_weighted_contribution_positive", top10_contribution, 5, lambda value: value > 0),
            _rule("top10_advancing_weight", top10_advance_weight, 4, lambda value: 4 if value >= 60 else 2 if value >= 40 else 0),
            _rule("top10_positive_contribution_weight", top10_positive_contribution, 3, lambda value: 3 if value >= 60 else 1.5 if value >= 40 else 0),
            _rule("top10_amount_coverage", top10_amount_coverage, 3, lambda value: 3 if value >= 90 else 1.5 if value >= 60 else 0),
        ]),
        _dimension("fundamentals_and_cycle", 10, [
            _rule("top10_financial_coverage", usable_financial_coverage, 5, lambda value: 5 if value >= 80 else 0),
            _rule("industry_cycle_indicator_count", len(cycle_rows) if cycle_rows else None, 5, lambda value: 5 if value >= 3 else 3 if value >= 1 else 0),
        ]),
        _dimension("events_and_policy", 10, [
            _rule("confirmed_event_neutral_baseline", event_baseline, 10, lambda value: value),
        ]),
    ]
    return _score(dimensions, CORE_LABEL_THRESHOLDS)


def calculate_short_term_score(
    metrics: QuantMetricsResult, fund_context: Mapping[str, Any] | None = None
) -> ScoreResult:
    """Calculate the confirmed 25/25/20/15/15 short-term score structure."""
    etf = metrics.etf
    advance_ratio, equal_return, weighted_return = _breadth_values(metrics)
    top10_contribution, top10_advance_weight, _, top10_amount_coverage = _top10_values(metrics)
    chain_positive_ratio = _positive_chain_ratio(metrics)
    event_baseline = _event_baseline(fund_context)
    intraday = _extended(fund_context, "intraday")
    flow_coverage = _fund_flow_coverage(fund_context)
    usable_flow_coverage = flow_coverage if flow_coverage is not None and flow_coverage >= 80 else None
    dimensions = [
        _dimension("daily_kline_and_close_position", 25, [
            _binary("return_1d_positive", etf.return_1d_pct, 5, lambda value: value > 0),
            _binary("close_above_sma5", etf.price_vs_sma5_pct, 5, lambda value: value > 0),
            _binary("close_above_sma10", etf.price_vs_sma10_pct, 4, lambda value: value > 0),
            _binary("close_above_sma20", etf.price_vs_sma20_pct, 4, lambda value: value > 0),
            _rule("rsi14_regime", etf.rsi14, 4, lambda value: 4 if 50 <= value <= 70 else 2 if 40 <= value < 50 or 70 < value <= 80 else 0),
            _rule("atr_risk_control", etf.atr_pct, 3, lambda value: 3 if value <= 3 else 2 if value <= 5 else 0),
        ]),
        _dimension("price_volume_and_etf_support", 25, [
            _binary("etf_amount_vs_5d", etf.amount_vs_5d_avg, 6, lambda value: value >= 1),
            _binary("sector_amount_vs_5d", metrics.sector.amount_vs_5d_avg, 6, lambda value: value >= 1),
            _rule("etf_share_change", _shares_change(fund_context), 5, lambda value: 5 if value > 0 else 2.5 if value == 0 else 0),
            _rule("etf_discount_control", _discount_rate(fund_context), 3, lambda value: 3 if abs(value) <= 1 else 1.5 if abs(value) <= 3 else 0),
            _rule("top10_main_flow_coverage", usable_flow_coverage, 5, lambda value: 5 if value >= 80 else 0),
        ]),
        _dimension("core_weight_tail_performance", 20, [
            _binary("top10_weighted_contribution_positive", top10_contribution, 8, lambda value: value > 0),
            _rule("top10_advancing_weight", top10_advance_weight, 5, lambda value: 5 if value >= 60 else 2.5 if value >= 40 else 0),
            _rule("top10_amount_coverage", top10_amount_coverage, 3, lambda value: 3 if value >= 90 else 1.5 if value >= 60 else 0),
            _rule("tail_30m_observation_count", len(intraday) if intraday else None, 4, lambda value: 4 if value >= 10 else 2 if value > 0 else 0),
        ]),
        _dimension("breadth_and_diffusion", 15, [
            _rule("advance_ratio", advance_ratio, 6, lambda value: 6 if value >= 60 else 4 if value >= 50 else 2 if value >= 40 else 0),
            _binary("equal_weight_return_positive", equal_return, 4, lambda value: value > 0),
            _binary("index_weighted_return_positive", weighted_return, 3, lambda value: value > 0),
            _rule("positive_supply_chain_ratio", chain_positive_ratio, 2, lambda value: 2 if value >= 60 else 1 if value >= 40 else 0),
        ]),
        _dimension("external_and_after_market_events", 15, [
            _rule("confirmed_event_neutral_baseline", event_baseline, 15, lambda value: value * 3),
        ]),
    ]
    return _score(dimensions, SHORT_LABEL_THRESHOLDS)


def detect_conflicts(metrics: QuantMetricsResult) -> tuple[str, ...]:
    etf, sector = metrics.etf, metrics.sector
    conflicts: list[str] = []
    if etf.amount_vs_20d_avg is not None and sector.amount_vs_20d_avg is not None:
        if etf.amount_vs_20d_avg >= 1.1 and sector.amount_vs_20d_avg < 0.9:
            conflicts.append("ETF_VOLUME_UP_SECTOR_VOLUME_DOWN")
        if sector.amount_vs_20d_avg >= 1.1 and etf.amount_vs_20d_avg < 0.9:
            conflicts.append("SECTOR_VOLUME_UP_ETF_VOLUME_DOWN")
    if etf.return_1d_pct is not None and sector.index_weighted_return_pct is not None:
        if etf.return_1d_pct > 0 >= sector.index_weighted_return_pct:
            conflicts.append("ETF_UP_SECTOR_NOT_UP")
        if etf.return_1d_pct < 0 <= sector.index_weighted_return_pct:
            conflicts.append("ETF_DOWN_SECTOR_NOT_DOWN")
    decided = sector.advancers + sector.decliners + sector.unchanged
    ratio = sector.advancers / decided * 100 if decided else None
    if etf.return_5d_pct is not None and etf.return_5d_pct > 0 and ratio is not None and ratio < 40:
        conflicts.append("ETF_5D_UP_BREADTH_WEAK")
    if sector.status != COMPLETE:
        conflicts.append("SECTOR_COVERAGE_INSUFFICIENT")
    return tuple(conflicts)


def calculate_data_confidence(metrics: QuantMetricsResult, core: ScoreResult, short: ScoreResult) -> ConfidenceResult:
    scoring_coverage = (core.scoring_coverage_pct + short.scoring_coverage_pct) / 2
    sector_coverage = min(
        metrics.sector.count_coverage_pct,
        metrics.sector.weight_coverage_pct,
        metrics.sector.amount_count_coverage_pct,
        metrics.sector.csi_classification_coverage_pct,
        metrics.sector.supply_chain_classification_coverage_pct,
    )
    market_lag = (pd.Timestamp(metrics.requested_analysis_date) - pd.Timestamp(metrics.market_date)).days
    market_factor = 1.0 if market_lag <= 3 else 0.8 if market_lag <= 7 else 0.5 if market_lag <= 14 else 0.2
    weight_lag = (pd.Timestamp(metrics.requested_analysis_date) - pd.Timestamp(metrics.weight_snapshot_date)).days
    weight_factor = 1.0 if weight_lag <= 45 else 0.8 if weight_lag <= 90 else 0.5
    confidence = scoring_coverage * 0.50 + sector_coverage * 0.30 + market_factor * 10 + weight_factor * 10
    return ConfidenceResult(confidence, scoring_coverage, sector_coverage, market_factor, weight_factor)


def _default_context() -> dict[str, Any]:
    return {
        "load_mode": "DATABASE_ONLY",
        "network_call_count": 0,
        "official_nav": None,
        "product_terms": {
            "fund_purchase_redemption_status": "UNAVAILABLE_FROM_VERIFIED_SOURCE",
            "etf_primary_market_subscription_redemption_status": "UNAVAILABLE_FROM_VERIFIED_SOURCE",
        },
        "etf_status": None,
        "extended_observations": {},
    }


def build_scored_report(
    metrics: QuantMetricsResult,
    fund_context: Mapping[str, Any] | None = None,
    *,
    for_backtest_feature_generation: bool = False,
) -> SectorFundScoredReport:
    """Build a V2 report and gate totals when source data is incomplete.

    Historical feature generation is isolated from user-facing analysis.  It
    may retain partial factor values for later research, but those values are
    never emitted by the on-demand report path as actionable trend scores.
    """
    context = dict(fund_context) if fund_context is not None else _default_context()
    metric_payload = metrics.to_dict()
    canonical = json.dumps(
        {"metrics": metric_payload, "fund_context": context, "scoring_version": SCORING_VERSION},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    if metrics.data_quality_status != COMPLETE or metrics.sector.status != COMPLETE:
        core = ScoreResult(None, "INSUFFICIENT_DATA", 0.0, ())
        short = ScoreResult(None, "INSUFFICIENT_DATA", 0.0, ())
    else:
        raw_core = calculate_core_trend_score(metrics, context)
        raw_short = calculate_short_term_score(metrics, context)
        core = raw_core if for_backtest_feature_generation else _gated(raw_core, thresholds=CORE_LABEL_THRESHOLDS)
        short = raw_short if for_backtest_feature_generation else _gated(raw_short, thresholds=SHORT_LABEL_THRESHOLDS)
    return SectorFundScoredReport(
        schema_version="sector_fund_scored_report_v2",
        scoring_version=SCORING_VERSION,
        input_hash=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        metrics=metric_payload,
        core_trend=core,
        short_term=short,
        data_confidence=calculate_data_confidence(metrics, core, short),
        conflicts=detect_conflicts(metrics),
        historical_adjustment={"status": "NOT_APPLIED", "reason": "用户要求当前报告不纳入历史回测修正"},
        probability_output={"status": "NOT_AVAILABLE", "reason": "用户要求当前报告不输出历史回测概率"},
        tool_adaptation={
            "fund": {"instrument": "场外基金", "use": "用于持有和申赎观察，不支持盘中交易。"},
            "target_etf": {"instrument": "场内ETF", "use": "用于盘中价格、成交额和技术状态观察。"},
            "core_stocks": {"instrument": "指数核心成分股", "use": "用于解释板块贡献和集中度，不替代基金整体结论。"},
        },
        fund_context=context,
    )
