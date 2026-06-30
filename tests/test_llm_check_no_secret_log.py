def test_llm_check_does_not_write_full_secret_to_log(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-abcdefghijklmnopqrstuvwxyz")
    from tradingagents.sector_fund.logging_utils import get_sector_logger, setup_sector_fund_logging

    ctx = setup_sector_fund_logging("llm_check", run_id="secret", quiet=True)
    get_sector_logger("llm").warning("⚠️ [LLMCheck] DeepSeek key 无效 | DEEPSEEK_API_KEY=sk-abcdefghijklmnopqrstuvwxyz")

    text = (tmp_path / ctx["log_path"]).read_text(encoding="utf-8")
    assert "abcdefghijklmnopqrstuvwxyz" not in text
    assert "DEEPSEEK_API_KEY=sk-****wxyz" in text
