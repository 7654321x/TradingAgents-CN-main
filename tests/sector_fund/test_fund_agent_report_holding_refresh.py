import sqlite3
from pathlib import Path

from tradingagents.sector_fund.db import initialize_database
from tradingagents.sector_fund.fund_agent_report import build_agent_prompt, render_agent_report, run_fund_agent_report
from tradingagents.sector_fund.fund_context_report import build_fund_context
from tradingagents.sector_fund.fund_sql_list import list_sql_fields


def test_fund_agent_report_refresh_holding_quotes(monkeypatch, tmp_path):
    db_path = tmp_path / "fund.sqlite3"
    config_path = tmp_path / "portfolio.yaml"
    config_path.write_text(f"database:\n  path: {db_path.as_posix()}\n", encoding="utf-8")
    initialize_database(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO fund_config (portfolio_id, fund_code, fund_name, fund_type) VALUES (1, '025500', '东方阿尔法科技智选混合C', 'active_equity')"
        )

    called = {}

    def fake_refresh(**kwargs):
        called.update(kwargs)
        return {"stock_count": 1, "write_result": {"security_quote_snapshot_rows": 1, "field_source_rows": 17, "data_source_run_rows": 2}}

    monkeypatch.setattr("tradingagents.sector_fund.fund_agent_report.refresh_holding_stock_data", fake_refresh)
    result = run_fund_agent_report(str(config_path), output_dir=tmp_path, use_llm=False, refresh_holding_quotes=True, analyze_holdings=True, top_n=5)

    assert called["top_n"] == 5
    assert result["holding_refresh"]["stock_count"] == 1
    assert Path(result["report_path"]).exists()


def test_fund_agent_prompt_contains_holding_quotes(tmp_path):
    db_path = tmp_path / "fund.sqlite3"
    config_path = tmp_path / "portfolio.yaml"
    config_path.write_text(f"database:\n  path: {db_path.as_posix()}\n", encoding="utf-8")
    initialize_database(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO security_quote_snapshot
            (entity_type, code, name, trade_date, snapshot_time, latest_price, change_pct, ma20, trend_status, source, source_status, final_source)
            VALUES ('stock', '603986', '兆易创新', '2026-06-29', '14:45:00', 88.5, -1.2, 82.3, 'above_ma20', 'eastmoney_push2', 'success', 'eastmoney_push2')
            """
        )
    fields = list_sql_fields(db_path)
    context = build_fund_context(fields)
    prompt = build_agent_prompt(context, fields, str(config_path), str(db_path), "1445", holdings_analysis={"holdings": [{"stock_code": "603986", "latest_price": 88.5, "trend_status": "above_ma20"}]})

    assert "603986" in prompt
    assert "latest_price" in prompt
    assert "trend_status" in prompt
    assert "质量门控" in prompt


def test_llm_invalid_key_fallback_does_not_output_action():
    report = render_agent_report(
        context={"funds": {"025500": {"fields": {"fund_name": "测试基金"}}}},
        fields=[],
        prompt="",
        llm_result={"status": "invalid_api_key", "error_reason": "invalid_api_key"},
        config_path="config.yaml",
        db_path="db.sqlite3",
        decision_time="1445",
        holdings_analysis={"holdings": []},
    )

    assert "LLM 分析失败，未生成操作倾向" in report
    assert "谨慎加仓" not in report
    assert "必须买入" not in report
