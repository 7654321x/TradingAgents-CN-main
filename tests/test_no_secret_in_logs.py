def test_no_secret_in_unified_logs(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from tradingagents.sector_fund.logging_utils import get_sector_logger, setup_sector_fund_logging

    ctx = setup_sector_fund_logging("data_probe", run_id="nosecret", quiet=True)
    get_sector_logger("firecrawl").info(
        "📥 [Firecrawl] 请求 | url=https://api.example.com/scrape?api_key=secret-token&code=512480 Authorization=Bearer sk-abcdefghijklmnopqrstuvwxyz"
    )

    text = (tmp_path / ctx["log_path"]).read_text(encoding="utf-8")
    assert "secret-token" not in text
    assert "abcdefghijklmnopqrstuvwxyz" not in text
    assert "code=512480" in text
