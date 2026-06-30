def test_fund_agent_report_logging_start_and_report(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from tradingagents.sector_fund.logging_utils import get_sector_logger, setup_sector_fund_logging

    ctx = setup_sector_fund_logging("fund_agent_report", run_id="agent", quiet=True)
    get_sector_logger("llm").info("🤖 [FundAgentReport] 开始生成基金Agent报告 | decision_time=1445")
    get_sector_logger("report").info("🧾 [FundAgentReport] 报告已生成 | path=reports/fund_intraday/report.md")

    text = (tmp_path / ctx["log_path"]).read_text(encoding="utf-8")
    assert "sector_fund.llm" in text
    assert "🤖 [FundAgentReport] 开始生成基金Agent报告" in text
    assert "sector_fund.report" in text
    assert "🧾 [FundAgentReport] 报告已生成" in text
