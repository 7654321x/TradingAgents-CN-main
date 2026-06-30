import sqlite3
from pathlib import Path

from tradingagents.sector_fund.db import initialize_database
from tradingagents.sector_fund.fund_agent_report import run_fund_agent_report


def test_fund_agent_report_can_run_without_llm(tmp_path):
    db_path = tmp_path / "fund.sqlite3"
    config_path = tmp_path / "portfolio.yaml"
    config_path.write_text(f"database:\n  path: {db_path.as_posix()}\n", encoding="utf-8")
    initialize_database(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO portfolio (id, name, total_position_pct, target_position_pct, max_position_pct) VALUES (1, 'test', 20, 30, 35)"
        )
        conn.execute(
            """
            INSERT INTO fund_config
            (portfolio_id, fund_code, fund_name, fund_type, role, position_pct)
            VALUES (1, '020671', '易方达科创芯片ETF联接C', 'etf_feeder', 'base', 12)
            """
        )
        conn.execute(
            """
            INSERT INTO fund_intraday_estimate
            (fund_code, trade_date, decision_time, estimate_nav, estimate_change_pct, estimate_source, source_status)
            VALUES ('020671', '2026-06-29', '1445', 1.23, -0.8, 'tiantianfund', 'success')
            """
        )

    result = run_fund_agent_report(str(config_path), output_dir=tmp_path, decision_time="1445", use_llm=False)
    report = Path(result["report_path"]).read_text(encoding="utf-8")

    assert result["llm_status"]["status"] == "skipped"
    assert "操作倾向" in report
    assert "LLM 分析失败，未生成操作倾向" in report
    assert Path(result["context_path"]).exists()
