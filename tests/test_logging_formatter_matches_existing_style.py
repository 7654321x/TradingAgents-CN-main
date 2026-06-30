import logging
import re


def test_logging_formatter_matches_sector_fund_style(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from tradingagents.sector_fund.logging_utils import get_sector_logger, setup_sector_fund_logging

    ctx = setup_sector_fund_logging("data_probe", run_id="20260629_222300", quiet=True)
    get_sector_logger("data_probe").info("🔍 [DataProbe] 开始数据探针 | config=x")

    text = (tmp_path / ctx["log_path"]).read_text(encoding="utf-8")
    assert re.search(
        r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3} \| sector_fund\.data_probe\s+\| INFO\s+\| 🔍 \[DataProbe\]",
        text,
    )
    assert logging.getLogger("sector_fund").handlers
