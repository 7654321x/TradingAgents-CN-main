from tradingagents.sector_fund.mock_data import build_mock_sector_fund_context
from tradingagents.sector_fund.report import render_sector_fund_report
from tradingagents.sector_fund.scoring import apply_data_quality_gate, score_sector_fund_context


def test_low_real_coverage_lowers_suggestion_strength():
    score = {
        "semiconductor_score": 82,
        "storage_score": 84,
        "risk_level": "中",
        "suggestion": "已有仓位持有，可等回踩小加。",
    }

    gated = apply_data_quality_gate(score, real_coverage_rate=35.0, min_real_coverage=40.0)

    assert "可等回踩小加" not in gated["suggestion"]
    assert "真实数据覆盖率较低" in gated["suggestion"]
    assert gated["risk_level"] == "高"


def test_report_uses_conservative_text_when_coverage_is_low():
    context = build_mock_sector_fund_context(analysis_date="2026-06-27")
    context.data_quality = {"real_coverage_rate": 20.0, "data_quality_level": "较低"}
    score = apply_data_quality_gate(score_sector_fund_context(context), real_coverage_rate=20.0, min_real_coverage=40.0)

    report = render_sector_fund_report(context, score)

    assert "真实数据覆盖率较低" in report
    assert "尾盘站稳MA5/MA10再小加" not in report
    assert "建议结合人工核对" in report
