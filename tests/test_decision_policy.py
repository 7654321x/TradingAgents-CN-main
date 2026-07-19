from __future__ import annotations

import pytest

from tradingagents.analysis.decision_policy import (
    MARKET_REQUIRED_REFS,
    DecisionPolicyEngine,
)


def evidence(missing_market=0):
    index = {
        ref: {
            "value": -0.5 if ref.endswith("technical_score") else 1.0,
            "status": "SUCCESS",
        }
        for ref in MARKET_REQUIRED_REFS
    }
    for ref in MARKET_REQUIRED_REFS[:missing_market]:
        index[ref]["status"] = "INSUFFICIENT_HISTORY"
    return {"evidence_index": index}


def analysts(*, fundamentals=False, news=False):
    return {
        "market_analysis": {"score": -0.7},
        "fundamentals_analysis": {"score": 0.2 if fundamentals else None},
        "news_analysis": {"score": 0.1 if news else None},
    }


def trend(score=-0.7, risk=0.85, medium="BEARISH", long="STRONG_BULLISH"):
    return {
        "technical_score": score,
        "technical_risk_score": risk,
        "deterministic_trend": "STRONG_BEARISH" if score <= -0.6 else "STRONG_BULLISH" if score >= 0.6 else "SIDEWAYS",
        "medium_term_trend": medium,
        "long_term_trend": long,
    }


def test_missing_fundamentals_lowers_confidence_not_direction():
    engine = DecisionPolicyEngine()
    missing = engine.evaluate(trend(), evidence(), analysts(fundamentals=False, news=True))
    full = engine.evaluate(trend(), evidence(), analysts(fundamentals=True, news=True))
    assert missing.directional_bias == full.directional_bias == "SELL_BIAS"
    assert missing.confidence_ceiling < full.confidence_ceiling


def test_missing_news_lowers_confirmation_not_direction():
    result = DecisionPolicyEngine().evaluate(trend(), evidence(), analysts(fundamentals=True, news=False))
    assert result.directional_bias == "SELL_BIAS"
    assert result.confirmation_status in {"PARTIALLY_CONFIRMED", "CONFLICTING"}


def test_market_coverage_separated_from_cross_domain_coverage():
    result = DecisionPolicyEngine().evaluate(trend(), evidence(), analysts())
    assert result.market_evidence_coverage == 1.0
    assert result.fundamentals_evidence_coverage == 0.0
    assert result.news_evidence_coverage == 0.0
    assert result.cross_domain_evidence_coverage == pytest.approx(0.55)


def test_strong_bearish_full_market_data_produces_sell_bias():
    result = DecisionPolicyEngine().evaluate(trend(), evidence(), analysts())
    assert result.directional_bias == "SELL_BIAS"
    assert result.confirmation_status == "TECHNICAL_ONLY"


def test_strong_bullish_full_market_data_produces_buy_bias():
    result = DecisionPolicyEngine().evaluate(
        trend(score=0.7, risk=0.3, medium="BULLISH", long="BULLISH"),
        evidence(),
        analysts(),
    )
    assert result.directional_bias == "BUY_BIAS"


def test_high_risk_does_not_force_neutral_direction():
    result = DecisionPolicyEngine().evaluate(trend(risk=1.0), evidence(), analysts())
    assert result.risk_level == "VERY_HIGH"
    assert result.directional_bias == "SELL_BIAS"


def test_long_term_bullish_conflict_lowers_confidence():
    engine = DecisionPolicyEngine()
    conflict = engine.evaluate(trend(long="STRONG_BULLISH"), evidence(), analysts())
    aligned = engine.evaluate(trend(long="BEARISH"), evidence(), analysts())
    assert conflict.primary_long_term_conflict is True
    assert conflict.confidence_ceiling < aligned.confidence_ceiling


def test_long_term_conflict_does_not_override_primary_horizon():
    result = DecisionPolicyEngine().evaluate(trend(long="STRONG_BULLISH"), evidence(), analysts())
    assert result.directional_bias == "SELL_BIAS"


def test_no_position_action_for_bearish_high_risk():
    result = DecisionPolicyEngine().evaluate(trend(), evidence(), analysts())
    assert result.position_scenarios["no_position"]["action"] == "AVOID_NEW_ENTRY"


def test_existing_long_action_for_bearish_high_risk():
    result = DecisionPolicyEngine().evaluate(trend(), evidence(), analysts())
    assert result.position_scenarios["existing_long"]["action"] == "REDUCE_RISK_BIAS"


def test_watchlist_waits_for_reversal():
    result = DecisionPolicyEngine().evaluate(trend(), evidence(), analysts())
    assert result.position_scenarios["watchlist"]["action"] == "WAIT_FOR_REVERSAL_CONFIRMATION"


def test_market_data_below_threshold_is_insufficient():
    result = DecisionPolicyEngine().evaluate(trend(), evidence(missing_market=2), analysts())
    assert result.market_evidence_coverage < 0.9
    assert result.directional_bias == "INSUFFICIENT_DATA"
