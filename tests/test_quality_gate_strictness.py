from tradingagents.sector_fund.mock_data import build_mock_sector_fund_context
from tradingagents.sector_fund.report import render_sector_fund_report
from tradingagents.sector_fund.scoring import apply_data_quality_gate, score_sector_fund_context


def test_low_coverage_report_does_not_output_add_position_language():
    context = build_mock_sector_fund_context(analysis_date="2026-06-28")
    context.data_quality = {"real_coverage_rate": 10.0, "data_quality_level": "较低"}
    score = apply_data_quality_gate(score_sector_fund_context(context), 10.0, 0.4)

    report = render_sector_fund_report(context, score)

    forbidden = ["小加", "加仓", "提高仓位到30%"]
    assert all(word not in report for word in forbidden)
    assert "暂不依据本报告操作" in report or "不根据本报告扩大仓位" in report


def test_medium_coverage_keeps_only_cautious_language():
    score = apply_data_quality_gate(
        {"suggestion": "已有仓位持有，可等回踩小加。", "risk_level": "中"},
        real_coverage_rate=55.0,
        min_real_coverage=0.4,
    )

    assert "小加" not in score["suggestion"]
    assert "持有观察" in score["suggestion"]
    assert "谨慎小仓" in score["suggestion"]
