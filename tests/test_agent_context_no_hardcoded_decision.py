from tradingagents.sector_fund.fund_context_formatter import format_fund_intraday_context
from tradingagents.sector_fund.intraday_snapshot import build_intraday_snapshot


def test_agent_context_contains_questions_not_final_hardcoded_decisions(tmp_path):
    snapshot = build_intraday_snapshot(
        "config/personal_fund_portfolio.yaml",
        decision_time="1445",
        db_path=tmp_path / "fund.sqlite3",
        refresh_data=False,
    )

    text = format_fund_intraday_context(snapshot)

    assert "需要原分析师Agent重点判断的问题" in text
    assert "不是数据层生成的最终投资结论" in text
    forbidden = ["必须买入", "必须卖出", "稳赚", "满仓", "自动交易", "代码建议买入", "代码建议卖出"]
    assert not any(phrase in text for phrase in forbidden)
