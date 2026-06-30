def test_holding_stock_logging_uses_unified_format(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from tradingagents.sector_fund.fetch_logger import DataFetchLogger
    from tradingagents.sector_fund.logging_utils import get_sector_logger, setup_sector_fund_logging

    ctx = setup_sector_fund_logging("fund_agent_report", run_id="holding", quiet=True)
    get_sector_logger("holding").info("📥 [HoldingStock] 开始刷新持仓股行情 | fund=025500 top_n=10")
    DataFetchLogger().quote_summary(
        "holding_stock_quote(eastmoney/akshare)",
        {"603986": {"source_status": "success", "latest_price": 840.0, "change_pct": 9.09}},
    )

    text = (tmp_path / ctx["log_path"]).read_text(encoding="utf-8")
    assert "sector_fund.holding" in text
    assert "📥 [HoldingStock] 开始刷新持仓股行情" in text
    assert "✅ [HoldingStock] 字段读取结果" in text
    assert "[data-fetch]" not in text
