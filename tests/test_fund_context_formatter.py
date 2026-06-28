from tradingagents.sector_fund.fund_context_formatter import format_fund_intraday_context, quality_prompt
from tradingagents.sector_fund.intraday_snapshot import build_intraday_snapshot


def test_fund_context_formatter_includes_constraints_and_quality_prompt(tmp_path):
    snapshot = build_intraday_snapshot(
        "config/personal_fund_portfolio.yaml",
        decision_time="1445",
        db_path=tmp_path / "fund.sqlite3",
        refresh_data=False,
    )

    text = format_fund_intraday_context(snapshot)

    assert "【场外基金盘中分析上下文】" in text
    assert "15:00 前交易按当天净值" in text
    assert "当前核心数据覆盖率" in text
    assert "【组合约束】" in text
    assert "【持仓基金】" in text


def test_quality_prompt_thresholds():
    assert "人工核对" in quality_prompt(39.99)
    assert "谨慎判断" in quality_prompt(40)
    assert "相对完整分析" in quality_prompt(70)
