from __future__ import annotations

from dataclasses import dataclass
from typing import Any


MARKET_REQUIRED_REFS = (
    "market.returns.return_5d_pct",
    "market.returns.return_10d_pct",
    "market.returns.return_20d_pct",
    "market.returns.return_40d_pct",
    "market.returns.return_60d_pct",
    "market.moving_averages.short_structure",
    "market.trend_strength.adx14",
    "market.trend_strength.plus_di14",
    "market.trend_strength.minus_di14",
    "market.volume.volume_ratio_20d",
    "market.path_risk.volatility_20d_pct",
    "market.path_risk.max_drawdown_60d_pct",
    "market.classification.technical_score",
    "market.classification.technical_risk_score",
)


def claim(reason: str, *refs: str) -> dict[str, Any]:
    return {"reason": reason, "evidence_refs": list(refs)}


@dataclass(frozen=True)
class DecisionPolicyResult:
    directional_bias: str
    confirmation_status: str
    risk_level: str
    position_scenarios: dict[str, dict[str, Any]]
    market_evidence_coverage: float
    fundamentals_evidence_coverage: float
    news_evidence_coverage: float
    cross_domain_evidence_coverage: float
    missing_confirmations: list[str]
    primary_long_term_conflict: bool
    confidence_ceiling: float

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


class DecisionPolicyEngine:
    """Deterministically separates direction, confirmation, risk, and scenarios."""

    @staticmethod
    def coverage(evidence_package: dict[str, Any], analysts: dict[str, Any]) -> dict[str, float]:
        index = evidence_package.get("evidence_index", {})
        valid_market = sum(
            1
            for ref in MARKET_REQUIRED_REFS
            if index.get(ref, {}).get("status") == "SUCCESS"
            and index.get(ref, {}).get("value") is not None
        )
        market = valid_market / len(MARKET_REQUIRED_REFS)
        fundamentals = 1.0 if analysts["fundamentals_analysis"].get("score") is not None else 0.0
        news = 1.0 if analysts["news_analysis"].get("score") is not None else 0.0
        return {
            "market_evidence_coverage": market,
            "fundamentals_evidence_coverage": fundamentals,
            "news_evidence_coverage": news,
            "cross_domain_evidence_coverage": 0.55 * market + 0.30 * fundamentals + 0.15 * news,
        }

    @staticmethod
    def _direction(score: float, trend: str, market_coverage: float) -> str:
        if market_coverage < 0.90:
            return "INSUFFICIENT_DATA"
        if score <= -0.20:
            return "SELL_BIAS"
        if score >= 0.20:
            return "BUY_BIAS"
        return "NEUTRAL"

    @staticmethod
    def _confirmation(coverage: dict[str, float], *, conflict: bool) -> str:
        if coverage["market_evidence_coverage"] < 0.90:
            return "INSUFFICIENT_DATA"
        if conflict and coverage["fundamentals_evidence_coverage"] > 0:
            return "CONFLICTING"
        if coverage["fundamentals_evidence_coverage"] == 0 and coverage["news_evidence_coverage"] == 0:
            return "TECHNICAL_ONLY"
        if coverage["fundamentals_evidence_coverage"] == 1 and coverage["news_evidence_coverage"] == 1:
            return "FULLY_CONFIRMED"
        return "PARTIALLY_CONFIRMED"

    @staticmethod
    def _risk_level(score: float) -> str:
        if score >= 0.80:
            return "VERY_HIGH"
        if score >= 0.65:
            return "HIGH"
        if score >= 0.40:
            return "MEDIUM"
        return "LOW"

    @staticmethod
    def _scenarios(direction: str, risk_level: str) -> dict[str, dict[str, Any]]:
        negative_refs = (
            "market.classification.technical_score",
            "market.classification.technical_risk_score",
            "market.moving_averages.short_structure",
        )
        positive_refs = (
            "market.classification.technical_score",
            "market.classification.technical_risk_score",
            "market.returns.return_20d_pct",
        )
        if direction == "SELL_BIAS":
            return {
                "no_position": claim("主要周期方向偏弱，暂不增加新的多头暴露", *negative_refs),
                "existing_long": claim("主要周期偏弱且路径风险较高，应优先评估风险收缩", *negative_refs),
                "watchlist": claim("等待收益、均线和动量出现客观反转确认", "market.returns.return_20d_pct", "market.moving_averages.ma20", "market.momentum.macd_histogram"),
                "_actions": {
                    "no_position": "AVOID_NEW_ENTRY",
                    "existing_long": "REDUCE_RISK_BIAS",
                    "watchlist": "WAIT_FOR_REVERSAL_CONFIRMATION",
                },
            }
        if direction == "BUY_BIAS":
            high = risk_level in {"HIGH", "VERY_HIGH"}
            return {
                "no_position": claim("方向偏正但风险较高时等待更有利的确认", *positive_refs),
                "existing_long": claim("方向偏正且已有暴露时保持观察并管理风险", *positive_refs),
                "watchlist": claim("等待回调或延续信号确认", "market.returns.return_20d_pct", "market.moving_averages.short_structure"),
                "_actions": {
                    "no_position": "WAIT" if high else "CONSIDER_ENTRY_BIAS",
                    "existing_long": "HOLD_BIAS",
                    "watchlist": "WAIT_FOR_PULLBACK" if high else "WATCH_CONTINUATION",
                },
            }
        if direction == "NEUTRAL":
            return {
                "no_position": claim("主要周期方向接近中性，等待方向形成", "market.classification.technical_score"),
                "existing_long": claim("方向接近中性，保持观察并复核风险", "market.classification.technical_score", "market.classification.technical_risk_score"),
                "watchlist": claim("等待趋势延续或反转条件形成", "market.classification.technical_score"),
                "_actions": {"no_position": "WAIT", "existing_long": "HOLD_BIAS", "watchlist": "WATCH_CONTINUATION"},
            }
        return {
            "no_position": claim("市场证据不足，无法形成研究动作", "market.classification.technical_score"),
            "existing_long": claim("市场证据不足，无法形成研究动作", "market.classification.technical_score"),
            "watchlist": claim("市场证据不足，无法形成研究动作", "market.classification.technical_score"),
            "_actions": {"no_position": "INSUFFICIENT_DATA", "existing_long": "INSUFFICIENT_DATA", "watchlist": "INSUFFICIENT_DATA"},
        }

    def evaluate(self, trend: dict[str, Any], evidence_package: dict[str, Any], analysts: dict[str, Any]) -> DecisionPolicyResult:
        coverage = self.coverage(evidence_package, analysts)
        direction = self._direction(
            float(trend["technical_score"]),
            str(trend["deterministic_trend"]),
            coverage["market_evidence_coverage"],
        )
        primary_negative = trend["medium_term_trend"] in {"BEARISH", "STRONG_BEARISH"}
        primary_positive = trend["medium_term_trend"] in {"BULLISH", "STRONG_BULLISH"}
        long_negative = trend["long_term_trend"] in {"BEARISH", "STRONG_BEARISH"}
        long_positive = trend["long_term_trend"] in {"BULLISH", "STRONG_BULLISH"}
        conflict = (primary_negative and long_positive) or (primary_positive and long_negative)
        confirmation = self._confirmation(coverage, conflict=conflict)
        risk_level = self._risk_level(float(trend["technical_risk_score"]))
        missing = []
        if coverage["fundamentals_evidence_coverage"] == 0:
            missing.append("fundamentals")
        if coverage["news_evidence_coverage"] == 0:
            missing.append("news")
        confidence_ceiling = 0.75
        confidence_ceiling -= 0.10 * len(missing)
        if conflict:
            confidence_ceiling -= 0.05
        if risk_level == "VERY_HIGH":
            confidence_ceiling -= 0.05
        raw_scenarios = self._scenarios(direction, risk_level)
        actions = raw_scenarios.pop("_actions")
        scenarios = {
            key: {"action": actions[key], **raw_scenarios[key]}
            for key in ("no_position", "existing_long", "watchlist")
        }
        return DecisionPolicyResult(
            directional_bias=direction,
            confirmation_status=confirmation,
            risk_level=risk_level,
            position_scenarios=scenarios,
            missing_confirmations=missing,
            primary_long_term_conflict=conflict,
            confidence_ceiling=max(0.0, confidence_ceiling),
            **coverage,
        )
