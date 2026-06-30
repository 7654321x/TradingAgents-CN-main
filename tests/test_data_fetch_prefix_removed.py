def test_data_fetch_prefix_removed_from_unified_logger(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from tradingagents.sector_fund.fetch_logger import DataFetchLogger
    from tradingagents.sector_fund.logging_utils import setup_sector_fund_logging

    ctx = setup_sector_fund_logging("data_probe", run_id="prefix_removed", quiet=True)
    DataFetchLogger().fetch_result("akshare_fund_holdings_025500", "https://example.com/?token=secret", "success/success", 128, ["a", "b"])

    text = (tmp_path / ctx["log_path"]).read_text(encoding="utf-8")
    assert "[data-fetch]" not in text
    assert "sector_fund.akshare" in text
    assert "✅ [AKShare]" in text
    assert "secret" not in text
