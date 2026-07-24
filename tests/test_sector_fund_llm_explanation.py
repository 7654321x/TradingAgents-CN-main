from __future__ import annotations

from types import SimpleNamespace

from tradingagents.extensions.sector_fund.daily_observation import build_daily_observation
from tradingagents.extensions.sector_fund.llm_explanation import _payload, generate_llm_explanation


def _metrics():
    return {
        "fund_code": "020671",
        "requested_analysis_date": "2026-07-22",
        "market_date": "2026-07-22",
        "weight_snapshot_date": "2026-06-30",
        "etf": {
            "close": 1.0, "sma20": 0.9, "rsi14": 55.0,
            "macd_histogram": 0.01, "macd_histogram_change": 0.002,
            "return_5d_pct": 1.0, "return_20d_pct": -2.0,
        },
        "sector": {
            "expected_count": 50, "price_available_count": 50, "amount_available_count": 50,
            "advancers": 30, "decliners": 18, "unchanged": 2,
            "index_weighted_return_pct": 0.5, "amount_vs_5d_avg": 1.1,
        },
    }


def _report():
    metrics = _metrics()
    return SimpleNamespace(
        metrics=metrics,
        core_trend=SimpleNamespace(score=60.0, label="SLIGHTLY_STRONG"),
        short_term=SimpleNamespace(score=55.0, label="NEUTRAL"),
        data_confidence=SimpleNamespace(confidence_pct=90.0),
        fund_context={"load_mode": "DATABASE_ONLY", "network_call_count": 0},
        daily_observation=build_daily_observation(metrics),
    )


def test_daily_observation_reports_current_values_without_prediction():
    result = build_daily_observation(_metrics())
    by_key = {item["key"]: item for item in result["items"]}
    assert by_key["etf_above_sma20"]["status"] == "ABOVE_SMA20"
    assert by_key["rsi14_above_50"]["status"] == "ABOVE_OR_EQUAL_50"
    assert by_key["etf_returns"]["status"] == "CURRENT_VALUES_ONLY"
    assert "下一次同步" in by_key["etf_returns"]["limitation"]


def test_llm_explanation_uses_existing_factory_and_excludes_backtest():
    prompts = []

    class _Client:
        def get_llm(self):
            return SimpleNamespace(invoke=lambda prompt: prompts.append(prompt) or SimpleNamespace(content="数据解读"))

    result = generate_llm_explanation(
        _report(), provider="deepseek", model="deepseek-v4-flash", llm_factory=lambda **_: _Client()
    )
    assert result["status"] == "SUCCESS"
    assert result["network_call_count"] == 1
    assert result["content"] == "数据解读"
    assert "历史回测不参与本次报告" in prompts[0]
    assert "不得输出买入" in prompts[0]
    assert "historical_backtest" in prompts[0]


def test_llm_payload_excludes_hybrid_market_metrics_when_close_audit_blocks_them():
    report = _report()
    report.fund_context = {
        "official_nav": {"nav_date": "2026-07-22"},
        "extended_observations": {
            "market_data_audit": [{
                "value": {"status": "CLOSE_UNCONFIRMED_DO_NOT_SCORE_AS_CLOSE"},
            }],
            "news_lead": [{"value": {"title": "媒体线索"}}],
        },
    }

    payload = _payload(report)

    assert payload["current_day_analysis_status"] == "DATA_GUARD_BLOCKED"
    assert payload["etf"] == "EXCLUDED_CURRENT_DAY_CLOSE_UNCONFIRMED"
    assert payload["sector"] == "EXCLUDED_CURRENT_DAY_CLOSE_UNCONFIRMED"
    assert payload["news_leads"] == [{"value": {"title": "媒体线索"}}]


def test_llm_failure_returns_deterministic_fallback():
    result = generate_llm_explanation(
        _report(), llm_factory=lambda **_: (_ for _ in ()).throw(ConnectionError("offline"))
    )
    assert result["status"] == "FAILED_FALLBACK_DETERMINISTIC"
    assert result["content"] is None
    assert "ConnectionError" in result["reason"]
