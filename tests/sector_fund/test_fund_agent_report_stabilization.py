import json
import sqlite3
import subprocess
from pathlib import Path

import main

from tradingagents.sector_fund import fund_enrich
from tradingagents.sector_fund.db import initialize_database
from tradingagents.sector_fund.fund_agent_report import calculate_agent_report_core_coverage, render_agent_report, run_fund_agent_report
from tradingagents.sector_fund.fund_context_report import build_fund_context
from tradingagents.sector_fund.fund_sql_list import list_sql_fields_for_context


def _write_minimal_config(tmp_path, db_path):
    config_path = tmp_path / "portfolio.yaml"
    config_path.write_text(f"database:\n  path: {db_path.as_posix()}\n", encoding="utf-8")
    return config_path


def _seed_basic_report_db(db_path):
    initialize_database(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO portfolio (id, name, total_position_pct, target_position_pct, max_position_pct, cash_position_pct) VALUES (1, 'test', 20, 30, 35, 80)"
        )
        conn.execute(
            "INSERT INTO fund_config (portfolio_id, fund_code, fund_name, fund_type, role, position_pct, max_single_position_pct) VALUES (1, '020671', '测试联接基金', 'etf_feeder', 'base', 12, 15)"
        )
        conn.execute(
            "INSERT INTO fund_intraday_estimate (fund_code, trade_date, decision_time, estimate_nav, estimate_change_pct, estimate_source, source_status) VALUES ('020671', '2026-06-30', '1445', 1.23, -0.8, 'tiantianfund', 'success')"
        )
        conn.execute(
            "INSERT INTO fund_nav_daily (fund_code, trade_date, unit_nav) VALUES ('020671', '2026-06-30', 1.22)"
        )


def test_report_no_sql_debug_by_default(tmp_path):
    db_path = tmp_path / "fund.sqlite3"
    config_path = _write_minimal_config(tmp_path, db_path)
    _seed_basic_report_db(db_path)

    result = run_fund_agent_report(str(config_path), output_dir=tmp_path, use_llm=False)
    report = Path(result["report_path"]).read_text(encoding="utf-8")
    debug_report = Path(result["debug_report_path"]).read_text(encoding="utf-8")

    assert "## SQL 输入字段列表" not in report
    assert "## SQL 输入字段列表" in debug_report


def test_include_sql_debug_flag(tmp_path):
    db_path = tmp_path / "fund.sqlite3"
    config_path = _write_minimal_config(tmp_path, db_path)
    _seed_basic_report_db(db_path)

    result = run_fund_agent_report(str(config_path), output_dir=tmp_path, use_llm=False, include_sql_debug=True)
    report = Path(result["report_path"]).read_text(encoding="utf-8")

    assert "## SQL 输入字段列表" in report


def test_debug_report_generated(tmp_path):
    db_path = tmp_path / "fund.sqlite3"
    config_path = _write_minimal_config(tmp_path, db_path)
    _seed_basic_report_db(db_path)

    result = run_fund_agent_report(str(config_path), output_dir=tmp_path, use_llm=False)
    debug_path = Path(result["debug_report_path"])
    debug_report = debug_path.read_text(encoding="utf-8")

    assert debug_path.exists()
    assert "context_json_path" in debug_report
    assert "llm_status" in debug_report


def test_data_source_run_filtered_by_trade_date(tmp_path):
    db_path = tmp_path / "fund.sqlite3"
    config_path = _write_minimal_config(tmp_path, db_path)
    _seed_basic_report_db(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO data_source_run
            (run_id, trade_date, decision_time, source_name, source_type, fetch_status, matched_fields_count, missing_fields_count)
            VALUES ('old-run', '2026-06-29', '1445', 'market_quotes', 'market', 'failed', 0, 7)
            """
        )
        conn.execute(
            """
            INSERT INTO data_source_run
            (run_id, trade_date, decision_time, source_name, source_type, fetch_status, matched_fields_count, missing_fields_count)
            VALUES ('new-run', '2026-06-30', '1445', 'market_quotes', 'market', 'success', 6, 1)
            """
        )

    result = run_fund_agent_report(str(config_path), output_dir=tmp_path, use_llm=False)
    context_payload = json.loads(Path(result["context_path"]).read_text(encoding="utf-8"))
    context = context_payload["context"]

    assert context["source_run_filter"]["old_source_runs_excluded"] == 1
    assert "market_quotes" in context["data_source_summary"]
    assert all(item["trade_date"] == "2026-06-29" for item in context_payload["debug_only_source_runs"])


def test_agent_report_core_coverage_groups_and_excludes_raw_fallback():
    context = {
        "decision_time": "1445",
        "portfolio": {
            "total_position_pct": 20,
            "target_position_pct": 30,
            "max_position_pct": 35,
            "cash_position_pct": 80,
            "max_single_position_pct": 15,
        },
        "funds": {
            "020671": {
                "fields": {"fund_name": "测试", "fund_type": "etf_feeder", "role": "base", "position_pct": 12, "estimate_reliability": "high"},
                "estimates": {"estimate_nav": 1.23, "estimate_change_pct": -0.8},
                "nav": {"unit_nav": 1.22},
                "tracking": {"etfs": ["512480"], "indices": ["科创50"], "sectors": ["半导体"]},
                "holdings": [{"code": "603986", "name": "兆易创新", "weight_pct": 8.8}],
            }
        },
        "etfs": {"512480": {"latest_price": 1.2, "change_pct": 2.1, "amount": 100, "source_status": "success", "final_source": "eastmoney_push2"}},
        "indices": {"科创50": {"latest_price": 900, "change_pct": 1.2, "amount": 300, "source_status": "success", "final_source": "eastmoney_push2"}},
        "sectors": {"半导体": {"change_pct": 3.4, "source_status": "success", "final_source": "firecrawl_raw"}},
        "securities": {"603986": {"latest_price": 88.5, "change_pct": 1.2, "amount": 50, "turnover_rate": 3.2, "ma20": 82.0, "trend_status": "above_ma20", "source_status": "success", "final_source": "eastmoney_push2"}},
    }

    coverage = calculate_agent_report_core_coverage(context)

    assert coverage["groups"]["etf"]["coverage"] == 100.0
    assert coverage["groups"]["sector"]["coverage"] == 0.0
    assert "sector.半导体.change_pct" in coverage["missing_core_fields"]


def test_sector_missing_visible_in_report():
    context = {
        "data_date": "2026-06-30",
        "decision_time": "1445",
        "source_run_filter": {"old_source_runs_excluded": 2},
        "funds": {},
        "portfolio": {},
        "etfs": {"512480": {"name": "半导体ETF", "latest_price": 1.23, "change_pct": 2.1, "amount": 123, "source_status": "success", "final_source": "eastmoney_push2"}},
        "indices": {"科创50": {"name": "科创50", "latest_price": 888, "change_pct": 1.2, "amount": 456, "source_status": "success", "final_source": "eastmoney_push2"}},
        "sectors": {
            "AI芯片": {"source_status": "missing"},
            "半导体": {"source_status": "missing"},
        },
        "securities": {},
        "market_quote_snapshot": {"trade_date": "2026-06-30", "snapshot_time": "14:45:00", "etf_count": 1, "index_count": 1, "sector_count": 0},
    }
    context["agent_report_core_coverage"] = calculate_agent_report_core_coverage(context)
    context["data_quality_summary"] = {"market": {"etf_success": 1, "etf_total": 1, "index_success": 1, "index_total": 1, "sector_success": 0, "sector_total": 2, "sector_missing_text": "AI芯片、半导体"}, "holdings": {"total": 0, "quote_success": 0}}

    report = render_agent_report(context, [], "", {"status": "skipped", "error_reason": "LLM disabled"}, "config.yaml", "db.sqlite3", "1445")

    assert "今日板块结构化行情缺失" in report
    assert "AI芯片、半导体" in report
    assert "2026-06-29" not in report


def test_top_holdings_weight_from_root_top_holdings(tmp_path):
    db_path = tmp_path / "fund.sqlite3"
    initialize_database(db_path)
    payload = {
        "fund_name": "东方阿尔法科技智选混合C",
        "top_holdings": [{"stock_code": "603986", "stock_name": "兆易创新", "weight_pct": 8.8, "report_period": "2026Q1"}],
        "tracking": {"stocks": [{"code": "603986", "name": "兆易创新"}]},
    }
    with sqlite3.connect(db_path) as conn:
        conn.execute("INSERT INTO fund_config (portfolio_id, fund_code, fund_name, fund_type) VALUES (1, '025500', '东方阿尔法科技智选混合C', 'active_equity')")
        conn.execute(
            "INSERT INTO fund_enrichment_result (run_id, fund_code, fund_name, auto_enriched_json) VALUES ('run1', '025500', '东方阿尔法科技智选混合C', ?)",
            (json.dumps(payload, ensure_ascii=False),),
        )
    fields = list_sql_fields_for_context(db_path, decision_time="1445")
    context = build_fund_context(fields, decision_time="1445")

    holding = context["funds"]["025500"]["holdings"][0]
    assert holding["weight_pct"] == 8.8
    assert holding["report_date"] == "2026Q1"


def test_firecrawl_extracted_not_override_structured_fields():
    enriched = fund_enrich._build_enriched_fund(  # type: ignore[attr-defined]
        fund={"code": "020671", "fund_company": "原基金公司", "fund_manager": "张三"},
        fund_name="测试基金",
        classifier={"fund_type": "etf_feeder", "confidence": "high", "manual_review_required": False, "reasons": []},
        tracking={"confidence": "high"},
        estimate={},
        daily={},
        nav_history=[],
        holdings_payload={},
        firecrawl={"extracted": {"fund_company": "这是一个明显过长且像网页摘要的基金公司介绍，不应进入正式字段。", "benchmark": "这是网页摘要，不应直接进入基准字段。"}},
    )

    assert enriched["fund_company"] == "原基金公司"
    assert enriched["fund_manager"] == "张三"
    assert enriched["benchmark"] == ""
    assert "benchmark" in enriched["enrichment"]["firecrawl_debug_only_fields"]


def test_weak_gate_softens_action_label():
    context = {
        "data_date": "2026-06-30",
        "decision_time": "1445",
        "source_run_filter": {"old_source_runs_excluded": 0},
        "portfolio": {"total_position_pct": 20, "target_position_pct": 30, "max_position_pct": 35, "cash_position_pct": 80, "max_single_position_pct": 15},
        "funds": {"020671": {"fields": {"fund_name": "测试基金", "fund_type": "etf_feeder", "role": "base", "position_pct": 12, "estimate_reliability": "high"}, "estimates": {"estimate_nav": 1.23, "estimate_change_pct": -0.8}, "nav": {"unit_nav": 1.22}, "tracking": {}, "holdings": []}},
        "etfs": {},
        "indices": {},
        "sectors": {},
        "securities": {},
        "market_quote_snapshot": {"trade_date": "2026-06-30", "snapshot_time": "14:45:00", "etf_count": 0, "index_count": 0, "sector_count": 0},
    }
    context["agent_report_core_coverage"] = {"agent_report_core_coverage": 60.0, "groups": {"fund": {"ok": 8, "total": 10, "coverage": 80.0}, "etf": {"ok": 0, "total": 0, "coverage": 0.0}, "index": {"ok": 0, "total": 0, "coverage": 0.0}, "sector": {"ok": 0, "total": 0, "coverage": 0.0}, "holding_stock": {"ok": 0, "total": 0, "coverage": 0.0}, "portfolio": {"ok": 5, "total": 5, "coverage": 100.0}}, "missing_core_fields": []}
    context["data_quality_summary"] = {"market": {"etf_success": 0, "etf_total": 0, "index_success": 0, "index_total": 0, "sector_success": 0, "sector_total": 0, "sector_missing_text": "-"}, "holdings": {"total": 0, "quote_success": 0}}

    report = render_agent_report(
        context,
        [],
        "",
        {"status": "success", "content": "## 1. 今日结论速览\n建议谨慎加仓，弱势时减仓。\n\n## 9. 免责声明\n仅供参考。"},
        "config.yaml",
        "db.sqlite3",
        "1445",
    )

    assert "谨慎加仓观察" in report
    assert "减仓观察" in report
    assert "建议谨慎加仓，弱势时减仓。" not in report


def test_windows_path_hardcode_removed():
    root = Path(__file__).resolve().parents[2]
    targets = [
        root / "tests/sector_fund/test_enriched_config_not_overwrite_original.py",
        root / "tests/sector_fund/test_fund_enrich_minimal_code.py",
    ]
    for path in targets:
        assert "D:/PycharmProjects/TradingAgents-CN-main" not in path.read_text(encoding="utf-8")


def test_include_sql_debug_cli_arg():
    parser = main.build_parser()
    args = parser.parse_args(["--mode", "fund_agent_report", "--include-sql-debug"])
    assert args.include_sql_debug is True


def test_no_agent_logic_modified():
    repo_root = Path(__file__).resolve().parents[2]
    output = subprocess.check_output(
        ["git", "diff", "--name-only", "--", "tradingagents/agents", "tradingagents/graph/trading_graph.py"],
        cwd=repo_root,
        text=True,
    ).strip()
    assert output == ""


def test_no_secret_leak(tmp_path, monkeypatch):
    db_path = tmp_path / "fund.sqlite3"
    config_path = _write_minimal_config(tmp_path, db_path)
    _seed_basic_report_db(db_path)
    secret = "sk-secret-value"
    monkeypatch.setenv("DEEPSEEK_API_KEY", secret)

    result = run_fund_agent_report(str(config_path), output_dir=tmp_path, use_llm=False)
    combined = Path(result["report_path"]).read_text(encoding="utf-8") + Path(result["debug_report_path"]).read_text(encoding="utf-8")

    assert secret not in combined
