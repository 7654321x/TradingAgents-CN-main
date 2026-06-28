from tradingagents.sector_fund.mock_data import build_mock_sector_fund_context
from tradingagents.sector_fund.report import render_sector_fund_report
from tradingagents.sector_fund.scoring import apply_data_quality_gate, score_sector_fund_context


def _mock_report(analysis_date="2026-06-28"):
    context = build_mock_sector_fund_context(analysis_date=analysis_date)
    context.source_mode = "mock"
    context.report_date = analysis_date
    context.data_date = None
    context.data_quality = {"real_coverage_rate": 0.0, "data_quality_level": "较低"}
    score = apply_data_quality_gate(score_sector_fund_context(context), 0.0, 0.4)
    return render_sector_fund_report(context, score)


def test_mock_report_has_top_simulation_warning():
    report = _mock_report()

    assert "当前为模拟/兜底报告，真实解析字段较低，仅用于流程验证，不代表真实市场。" in report


def test_mock_fields_are_labeled_and_announcements_are_simulated():
    report = _mock_report()

    assert "半导体评分：" in report
    assert "（mock，仅流程验证）" in report
    assert "半导体主力净流入：42.50亿元（mock）" in report
    assert "未获取到真实公告，本节为mock示例。" in report
    assert "【模拟】" in report


def test_mock_ma_does_not_claim_negative_break_or_real_pullback():
    report = _mock_report()

    assert "跌破MA5=否" not in report
    assert "跌破MA10=否" not in report
    assert "回踩MA5=是" not in report
    assert "回踩MA5=mock示例，不作为操作依据" in report


def test_recent_coverage_format_and_insufficient_history_message():
    context = build_mock_sector_fund_context(analysis_date="2026-06-28")
    context.source_mode = "mock"
    context.data_quality = {"real_coverage_rate": 0.0, "data_quality_level": "较低"}
    context.history_summary = {"recent_real_coverage_rates": [2.01, 0.0]}
    score = apply_data_quality_gate(score_sector_fund_context(context), 0.0, 0.4)

    report = render_sector_fund_report(context, score)

    assert "最近3次真实覆盖率：历史记录不足3次" in report
    assert "2.01%" in report
    assert "0.00%" in report


def test_non_trading_day_warning_is_rendered():
    report = _mock_report("2026-06-28")

    assert "非交易日，应使用最近交易日数据" in report
