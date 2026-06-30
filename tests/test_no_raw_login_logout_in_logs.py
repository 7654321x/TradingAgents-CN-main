def test_no_raw_login_logout_in_unified_logs(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from tradingagents.sector_fund.logging_utils import get_sector_logger, setup_sector_fund_logging

    ctx = setup_sector_fund_logging("fund_agent_report", run_id="baostock_noise", quiet=True)
    get_sector_logger("baostock").info("✅ [Baostock] 批次登录成功 | symbols=10 purpose=holding_stock_history")
    get_sector_logger("baostock").info("✅ [Baostock] 批次退出成功 | symbols=10 purpose=holding_stock_history")

    text = (tmp_path / ctx["log_path"]).read_text(encoding="utf-8")
    assert "login success!" not in text
    assert "logout success!" not in text
    assert "批次登录成功" in text
    assert "批次退出成功" in text


def test_default_info_file_does_not_write_baostock_native_debug(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from tradingagents.sector_fund.logging_utils import get_sector_logger, setup_sector_fund_logging

    ctx = setup_sector_fund_logging("fund_agent_report", run_id="baostock_debug", quiet=True, log_level="INFO")
    get_sector_logger("baostock").debug("🔧 [Baostock] 原生输出 | stdout=login success! stderr=")
    get_sector_logger("baostock").info("✅ [Baostock] 批次登录成功 | symbols=10 purpose=holding_stock_history")

    text = (tmp_path / ctx["log_path"]).read_text(encoding="utf-8")
    assert "login success!" not in text
    assert "批次登录成功" in text
