from tradingagents.sector_fund.mock_data import build_mock_sector_fund_context
from tradingagents.sector_fund.report import render_sector_fund_report
from tradingagents.sector_fund.scoring import apply_data_quality_gate, score_sector_fund_context


def test_report_contains_reading_guide_and_manual_checklist():
    context = build_mock_sector_fund_context(analysis_date="2026-06-28")
    context.data_quality = {"real_coverage_rate": 0.0, "data_quality_level": "较低"}
    score = apply_data_quality_gate(score_sector_fund_context(context), 0.0, 0.4)

    report = render_sector_fund_report(context, score)

    assert "【如何阅读本报告】" in report
    assert "先看数据可信度" in report
    assert "【人工复核清单】" in report
    assert "东方财富板块资金流" in report
    assert "同花顺行业资金流" in report
    assert "重大公告遗漏" in report
