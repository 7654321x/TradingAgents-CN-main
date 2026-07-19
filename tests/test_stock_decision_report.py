from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime

import pandas as pd
import pytest
from langchain_core.messages import AIMessage
from sqlalchemy.orm import Session

from tradingagents.analysis.stock_decision_report import (
    INVALID_TRADER_JSON,
    RISK_REVIEW_FAILED,
    DeterministicTrendEngine,
    MarketInput,
    StockDecisionReportError,
    StockDecisionReportService,
    TraderDecision,
)
from tradingagents.reports.stock_decision_report import (
    PROHIBITED_PHRASES,
    audit_stock_decision_report,
    render_stock_decision_report,
    save_stock_decision_report,
)
from tradingagents.storage.db import get_engine, init_db
from tradingagents.storage.models import Instrument, MarketBarObservation


SYMBOL = "001309.SZ"
NAME = "德明利"


def _seed(engine, rows=280, unfinished=True):
    dates = pd.bdate_range("2025-01-02", periods=rows + int(unfinished))
    with Session(engine) as session:
        instrument = Instrument(
            symbol=SYMBOL,
            local_code="001309",
            name=NAME,
            instrument_type="stock",
            exchange="SZ",
            currency="CNY",
            timezone="Asia/Shanghai",
        )
        session.add(instrument)
        session.flush()
        for number, date in enumerate(dates):
            close = 100 + number * 0.18 + 4 * ((number % 17) / 17)
            session.add(
                MarketBarObservation(
                    instrument_id=instrument.id,
                    interval="1d",
                    bar_time=date.to_pydatetime(),
                    market_date=date.date().isoformat(),
                    open=close - 0.8,
                    high=close + 1.2,
                    low=close - 1.5,
                    close=close,
                    adjusted_close=close,
                    volume=1_000_000 + number * 1000,
                    is_final=not (unfinished and number == len(dates) - 1),
                    provider="test",
                    upstream_group="test",
                    available_at=datetime(2025, 1, 2),
                    fetched_at=datetime(2025, 1, 2),
                    payload_hash=f"stock-report-{number}",
                    run_id="test",
                )
            )
        session.commit()
    return dates[-1].date().isoformat(), dates[-2].date().isoformat()


@pytest.fixture
def seeded():
    engine = init_db(get_engine("sqlite://"))
    analysis_date, final_date = _seed(engine)
    return engine, analysis_date, final_date


class FakeDecisionLLM:
    def __init__(
        self,
        kind: str,
        *,
        invalid_metrics=False,
        invalid_json=False,
        empty_invalidation=False,
        reject_insufficient=False,
    ):
        self.kind = kind
        self.invalid_metrics = invalid_metrics
        self.invalid_json = invalid_json
        self.empty_invalidation = empty_invalidation
        self.reject_insufficient = reject_insufficient
        self.calls = 0
        self.inputs = []

    def invoke(self, messages):
        self.calls += 1
        envelope = json.loads(messages[-1].content)
        payload = envelope["input"]
        self.inputs.append(payload)
        if self.invalid_json:
            return AIMessage(content="not-json")
        if self.kind == "trader":
            package = payload["evidence_package"]
            trend = package["deterministic_classification"]
            policy = payload["decision_policy"]
            score = payload["evidence_score"] + (0.1 if self.invalid_metrics else 0)
            claim = lambda text, *refs: {"text": text, "evidence_refs": list(refs)}
            body = {
                "primary_horizon": "20_TO_60_TRADING_DAYS",
                "trend_direction": trend["medium_term_trend"],
                "short_term_trend": trend["short_term_trend"],
                "medium_term_trend": trend["medium_term_trend"],
                "long_term_trend": trend["long_term_trend"],
                "trend_strength": "MODERATE",
                "directional_bias": policy["directional_bias"],
                "confirmation_status": policy["confirmation_status"],
                "confidence": 0.72,
                "evidence_score": score,
                "technical_score": trend["technical_score"],
                "primary_reasons": [claim("中期收益路径与确定性分类共同支持判断", "market.returns.return_20d_pct", "market.returns.return_60d_pct", "market.classification.technical_score")],
                "positive_factors": [claim("长期收益仍构成相反证据", "market.returns.return_120d_pct")],
                "negative_factors": [claim("短期均线结构偏弱", "market.moving_averages.short_structure")],
                "risk_factors": [claim("波动与回撤风险较高", "market.path_risk.volatility_20d_pct", "market.path_risk.max_drawdown_60d_pct")],
                "invalidation_conditions": [] if self.empty_invalidation else [claim("中期收益路径和短期均线结构发生方向变化时重新评估", "market.returns.return_20d_pct", "market.moving_averages.short_structure")],
                "key_uncertainties": [claim("基本面和新闻证据不可用", "fundamentals.status", "news.status")],
                "data_quality": payload["data_quality"],
                "market_evidence_coverage": payload["market_evidence_coverage"],
                "cross_domain_evidence_coverage": payload["cross_domain_evidence_coverage"],
            }
        else:
            trader = payload["trader_decision"]
            policy = payload["decision_policy"]
            claim = lambda text, *refs: {"text": text, "evidence_refs": list(refs)}
            body = {
                "review_status": "REJECTED_INSUFFICIENT_DATA" if self.reject_insufficient else "DOWNGRADED",
                "risk_level": "UNKNOWN" if self.reject_insufficient else policy["risk_level"],
                "directional_bias": "INSUFFICIENT_DATA" if self.reject_insufficient else policy["directional_bias"],
                "confirmation_status": "INSUFFICIENT_DATA" if self.reject_insufficient else policy["confirmation_status"],
                "adjusted_confidence": 0.0 if self.reject_insufficient else 0.40,
                "overconfidence_detected": True,
                "data_gap_detected": True,
                "trend_conflict_detected": trader["short_term_trend"] != trader["long_term_trend"],
                "adjustment_reasons": [claim("证据覆盖不足并存在周期冲突", "fundamentals.status", "news.status", "market.returns.return_120d_pct")],
                "risk_warnings": [claim("路径波动和回撤风险需要关注", "market.path_risk.volatility_20d_pct", "market.path_risk.max_drawdown_60d_pct")],
                "decision_limitations": [claim("缺失数据不能作为中性证据", "fundamentals.status", "news.status")],
                "required_follow_up": [claim("更新收益和均线结构后重新判断", "market.returns.return_20d_pct", "market.moving_averages.short_structure")],
                "position_scenarios": policy["position_scenarios"],
                "reasoning_summary": "证据覆盖不足且技术风险较高，因此降低倾向强度和模型自评置信度。",
            }
        return AIMessage(
            content=json.dumps(body, ensure_ascii=False),
            response_metadata={"token_usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}},
        )


def _service(session, trader=None, risk=None, provider=None):
    return StockDecisionReportService(
        session,
        mode="database_only",
        provider=provider,
        trader_llm=trader,
        risk_llm=risk,
        llm_provider="fake",
        trader_model="fake-trader",
        risk_model="fake-risk",
    )


def _run(seeded):
    engine, analysis_date, _ = seeded
    trader, risk = FakeDecisionLLM("trader"), FakeDecisionLLM("risk")
    with Session(engine) as session:
        result = _service(session, trader, risk).run(
            SYMBOL, NAME, analysis_date, ["market", "fundamentals", "news"]
        )
    return result, trader, risk


def test_reads_database_market_data(seeded):
    engine, analysis_date, _ = seeded
    with Session(engine) as session:
        prepared = _service(session).prepare(SYMBOL, NAME, analysis_date, ["market"])
    assert prepared["market_input"]["daily_row_count"] == 280
    assert prepared["market_input"]["market_data_source"] == "database"


def test_database_only_does_not_call_yahoo(seeded):
    engine, analysis_date, _ = seeded
    with Session(engine) as session:
        prepared = _service(session, provider=lambda *_: pytest.fail("Yahoo called")).prepare(
            SYMBOL, NAME, analysis_date, ["market"]
        )
    assert prepared["market_input"]["market_provider_call_count"] == 0


def test_respects_analysis_date_and_excludes_unfinished_daily(seeded):
    engine, analysis_date, final_date = seeded
    with Session(engine) as session:
        prepared = _service(session).prepare(SYMBOL, NAME, analysis_date, ["market"])
    assert prepared["market_input"]["latest_market_date"] == final_date
    assert prepared["market_input"]["latest_market_date"] < analysis_date


def test_deterministic_trend_score_range(seeded):
    engine, analysis_date, _ = seeded
    with Session(engine) as session:
        prepared = _service(session).prepare(SYMBOL, NAME, analysis_date, ["market"])
    trend = prepared["trend_result"]
    assert -1 <= trend["technical_score"] <= 1
    assert 0 <= trend["technical_risk_score"] <= 1


@pytest.mark.parametrize(
    ("score", "expected"),
    [(0.61, "STRONG_BULLISH"), (0.25, "BULLISH"), (0.0, "SIDEWAYS"), (-0.25, "BEARISH"), (-0.61, "STRONG_BEARISH")],
)
def test_trend_classification(score, expected):
    assert DeterministicTrendEngine.classify(score) == expected


def test_volatility_does_not_directly_reverse_direction(seeded):
    engine, analysis_date, _ = seeded
    with Session(engine) as session:
        prepared = _service(session).prepare(SYMBOL, NAME, analysis_date, ["market"])
    trend = prepared["trend_result"]
    assert "volatility" not in trend["scoring_rule"].split(";", 1)[0]
    assert "volatility" in trend["scoring_rule"].split(";", 1)[1]


def test_missing_news_is_not_neutral_and_missing_fundamentals_reweights(seeded):
    engine, analysis_date, _ = seeded
    with Session(engine) as session:
        prepared = _service(session).prepare(SYMBOL, NAME, analysis_date, ["market", "fundamentals", "news"])
    assert prepared["analyst_results"]["news_analysis"]["score"] is None
    assert prepared["analyst_results"]["news_analysis"]["signal"] == "INSUFFICIENT_DATA"
    assert prepared["analyst_results"]["fundamentals_analysis"]["score"] is None
    assert prepared["evidence"]["evidence_score"] == pytest.approx(prepared["trend_result"]["technical_score"])
    assert prepared["evidence"]["evidence_coverage"] == pytest.approx(0.55)
    assert prepared["evidence"]["market_evidence_coverage"] == pytest.approx(1.0)
    assert prepared["evidence"]["cross_domain_evidence_coverage"] == pytest.approx(0.55)


def test_trader_receives_deterministic_trend_and_returns_strict_json(seeded):
    result, trader, _ = _run(seeded)
    assert trader.inputs[0]["evidence_package"]["deterministic_classification"]["technical_score"] == result.deterministic_trend["technical_score"]
    assert result.trader_decision["primary_horizon"] == "20_TO_60_TRADING_DAYS"
    assert result.trader_decision["invalidation_conditions"]


def test_trader_requires_horizon():
    with pytest.raises(Exception):
        TraderDecision.model_validate({})


def test_trader_cannot_modify_input_metrics(seeded):
    engine, analysis_date, _ = seeded
    with Session(engine) as session, pytest.raises(StockDecisionReportError) as exc:
        _service(session, FakeDecisionLLM("trader", invalid_metrics=True), FakeDecisionLLM("risk")).run(
            SYMBOL, NAME, analysis_date, ["market", "fundamentals", "news"]
        )
    assert exc.value.code == INVALID_TRADER_JSON


def test_trader_requires_invalidation_conditions(seeded):
    engine, analysis_date, _ = seeded
    with Session(engine) as session, pytest.raises(StockDecisionReportError) as exc:
        _service(
            session,
            FakeDecisionLLM("trader", empty_invalidation=True),
            FakeDecisionLLM("risk"),
        ).run(SYMBOL, NAME, analysis_date, ["market", "fundamentals", "news"])
    assert exc.value.code == INVALID_TRADER_JSON


def test_risk_review_detects_gaps_overconfidence_and_can_downgrade(seeded):
    result, _, risk = _run(seeded)
    assert risk.calls == 1
    assert result.risk_review["overconfidence_detected"] is True
    assert result.risk_review["data_gap_detected"] is True
    assert result.risk_review["directional_bias"] == result.trader_decision["directional_bias"]
    assert result.risk_review["adjusted_confidence"] < result.trader_decision["confidence"]


def test_final_decision_uses_policy_direction_and_risk_adjustment(seeded):
    result, _, _ = _run(seeded)
    assert result.final_decision["directional_bias"] == result.risk_review["directional_bias"]
    assert result.final_decision["source"] == "decision_policy.direction+risk_review.risk_adjustment"


def test_risk_review_cannot_reject_when_market_evidence_is_complete(seeded):
    engine, analysis_date, _ = seeded
    with Session(engine) as session:
        with pytest.raises(StockDecisionReportError) as exc:
            _service(
                session,
                FakeDecisionLLM("trader"),
                FakeDecisionLLM("risk", reject_insufficient=True),
            ).run(SYMBOL, NAME, analysis_date, ["market", "fundamentals", "news"])
    assert exc.value.code == RISK_REVIEW_FAILED


def test_dry_run_does_not_call_llm(seeded):
    engine, analysis_date, _ = seeded
    trader, risk = FakeDecisionLLM("trader"), FakeDecisionLLM("risk")
    with Session(engine) as session:
        prepared = _service(session, trader, risk).run(
            SYMBOL, NAME, analysis_date, ["market", "fundamentals", "news"], dry_run=True
        )
    assert prepared["risk_input_template"]
    assert trader.calls == risk.calls == 0


def test_report_saves_all_audit_files_and_requires_overwrite(seeded, tmp_path):
    result, _, _ = _run(seeded)
    paths = save_stock_decision_report(result, tmp_path)
    assert len(paths) == 10
    assert all(path.exists() for path in paths.values())
    with pytest.raises(StockDecisionReportError) as exc:
        save_stock_decision_report(result, tmp_path)
    assert exc.value.code == "REPORT_ALREADY_EXISTS"
    save_stock_decision_report(result, tmp_path, overwrite=True)


def test_llm_failure_does_not_create_final_report(seeded, tmp_path):
    engine, analysis_date, _ = seeded
    with Session(engine) as session, pytest.raises(StockDecisionReportError):
        result = _service(session, FakeDecisionLLM("trader", invalid_json=True), FakeDecisionLLM("risk")).run(
            SYMBOL, NAME, analysis_date, ["market", "fundamentals", "news"]
        )
        save_stock_decision_report(result, tmp_path)
    assert not (tmp_path / "decision_report.md").exists()


def test_risk_failure_does_not_mark_trader_as_final(seeded, tmp_path):
    engine, analysis_date, _ = seeded
    with Session(engine) as session, pytest.raises(StockDecisionReportError) as exc:
        result = _service(session, FakeDecisionLLM("trader"), FakeDecisionLLM("risk", invalid_json=True)).run(
            SYMBOL, NAME, analysis_date, ["market", "fundamentals", "news"]
        )
        save_stock_decision_report(result, tmp_path)
    assert exc.value.code == RISK_REVIEW_FAILED
    assert not (tmp_path / "decision_report.md").exists()


def test_report_contains_required_decision_risk_and_disclaimer(seeded):
    result, _, _ = _run(seeded)
    text = render_stock_decision_report(result)
    assert result.final_decision["directional_bias"] in text
    assert result.final_decision["risk_level"] in text
    assert result.final_decision["invalidation_conditions"][0]["text"] in text
    assert "模型自评置信度尚未经过历史校准" in text
    assert "不构成投资建议" in text
    assert audit_stock_decision_report(result, text) == []


def test_report_contains_decision_card(seeded):
    result, _, _ = _run(seeded)
    text = render_stock_decision_report(result)
    assert "## 决策卡" in text
    assert text.index("## 决策卡") < text.index("## 一、核心结论")


def test_report_contains_position_scenarios(seeded):
    result, _, _ = _run(seeded)
    text = render_stock_decision_report(result)
    assert "### 无持仓" in text
    assert "### 已有多头" in text
    assert "### 观察名单" in text


def test_report_contains_chinese_action_explanations(seeded):
    result, _, _ = _run(seeded)
    text = render_stock_decision_report(result)
    for scenario in result.final_decision["position_scenarios"].values():
        assert scenario["action"] in text
    assert "方向倾向" in text and "确认程度" in text


def test_report_rejects_target_price_and_immediate_trade_instruction(seeded):
    result, _, _ = _run(seeded)
    text = render_stock_decision_report(result)
    for phrase in PROHIBITED_PHRASES:
        assert phrase not in text
    assert audit_stock_decision_report(result, text + "\n立即买入\n目标价 200")


def test_two_llm_calls_and_token_usage(seeded):
    result, trader, risk = _run(seeded)
    assert trader.calls == risk.calls == 1
    assert result.llm_call_count == 2
    assert result.token_usage == {"input_tokens": 200, "output_tokens": 100, "total_tokens": 300}
