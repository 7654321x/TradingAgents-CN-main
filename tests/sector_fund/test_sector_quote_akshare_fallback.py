import sqlite3
import subprocess
from pathlib import Path

from tradingagents.sector_fund.akshare_provider import AkShareProvider
from tradingagents.sector_fund.db import initialize_database
from tradingagents.sector_fund.fund_agent_report import calculate_agent_report_core_coverage, render_agent_report
from tradingagents.sector_fund.fund_context_report import build_fund_context
from tradingagents.sector_fund.fund_sql_list import list_sql_fields_for_context
from tradingagents.sector_fund.market_quote_data import _fetch_sector_quotes, write_market_quotes_to_sql


def test_sector_quote_akshare_fallback(monkeypatch):
    monkeypatch.setattr(
        "tradingagents.sector_fund.market_quote_data.EastMoneyQuoteProvider.fetch_sector_changes",
        lambda self, names: {"半导体": {"source_status": "failed", "error_reason": "eastmoney no_match"}},
    )
    monkeypatch.setattr(
        "tradingagents.sector_fund.market_quote_data.AkShareProvider.fetch_sector_boards",
        lambda self, names: {
            "半导体": {
                "name": "半导体概念",
                "change_pct": 3.21,
                "amount": 123456789,
                "source": "akshare",
                "final_source": "akshare",
                "source_status": "success",
            }
        },
    )

    result = _fetch_sector_quotes(["半导体"])

    assert result["半导体"]["source_status"] == "success"
    assert result["半导体"]["final_source"] == "akshare"
    assert result["半导体"]["change_pct"] == 3.21


def test_sector_alias_mapping(monkeypatch):
    rows = [
        {"板块名称": "印制电路板", "涨跌幅": 1.1, "成交额": 1000},
        {"板块名称": "算力芯片", "涨跌幅": 2.2, "成交额": 2000},
        {"板块名称": "半导体概念", "涨跌幅": 3.3, "成交额": 3000},
        {"板块名称": "存储器", "涨跌幅": 4.4, "成交额": 4000},
        {"板块名称": "芯片", "涨跌幅": 5.5, "成交额": 5000},
    ]
    monkeypatch.setattr(AkShareProvider, "_import_akshare", lambda self: object())
    monkeypatch.setattr(
        AkShareProvider,
        "_sector_board_datasets",
        lambda self, ak: [{"source_interface": "stock_board_concept_name_em", "rows": rows}],
    )

    result = AkShareProvider().fetch_sector_boards(["PCB", "AI芯片", "半导体", "存储芯片", "科创芯片"])

    assert result["PCB"]["sector_name"] == "印制电路板"
    assert result["AI芯片"]["sector_name"] == "算力芯片"
    assert result["半导体"]["sector_name"] == "半导体概念"
    assert result["存储芯片"]["sector_name"] == "存储器"
    assert result["科创芯片"]["sector_name"] == "芯片"


def test_sector_missing_not_using_old_data(tmp_path):
    db_path = tmp_path / "fund.sqlite3"
    initialize_database(db_path)
    write_market_quotes_to_sql(
        db_path=db_path,
        run_id="old-run",
        trade_date="2026-06-29",
        decision_time="1445",
        snapshot_time="14:45:00",
        etf_quotes={"512480": {"name": "半导体ETF", "latest_price": 1.2, "change_pct": 2.1, "amount": 100, "source": "eastmoney_push2", "final_source": "eastmoney_push2", "source_status": "success"}},
        index_quotes={},
        sector_quotes={"半导体": {"name": "半导体", "change_pct": 3.4, "amount": 500, "source": "eastmoney_push2_sector", "final_source": "eastmoney_push2", "source_status": "success"}},
    )
    write_market_quotes_to_sql(
        db_path=db_path,
        run_id="new-run",
        trade_date="2026-06-30",
        decision_time="1445",
        snapshot_time="14:45:00",
        etf_quotes={"512480": {"name": "半导体ETF", "latest_price": 1.3, "change_pct": 2.2, "amount": 120, "source": "eastmoney_push2", "final_source": "eastmoney_push2", "source_status": "success"}},
        index_quotes={},
        sector_quotes={"半导体": {"name": "半导体", "source": "missing", "final_source": "missing", "source_status": "missing"}},
    )

    context = build_fund_context(list_sql_fields_for_context(db_path, decision_time="1445"), decision_time="1445")

    assert context["data_date"] == "2026-06-30"
    assert context["sectors"]["半导体"]["source_status"] == "missing"
    assert context["sectors"]["半导体"]["final_source"] == "missing"
    assert context["sectors"]["半导体"].get("change_pct") is None


def test_sector_coverage_partial_success():
    context = {
        "data_date": "2026-06-30",
        "decision_time": "1445",
        "source_run_filter": {"old_source_runs_excluded": 0},
        "portfolio": {"total_position_pct": 20, "target_position_pct": 30, "max_position_pct": 35, "cash_position_pct": 80, "max_single_position_pct": 15},
        "funds": {
            "020671": {
                "fields": {"fund_name": "测试基金", "fund_type": "etf_feeder", "role": "base", "position_pct": 12, "estimate_reliability": "high"},
                "estimates": {"estimate_nav": 1.23, "estimate_change_pct": -0.8},
                "nav": {"unit_nav": 1.22},
                "tracking": {"sectors": ["半导体", "AI芯片"]},
                "holdings": [],
            }
        },
        "etfs": {},
        "indices": {},
        "sectors": {
            "半导体": {"name": "半导体", "change_pct": 3.4, "source_status": "success", "final_source": "akshare"},
            "AI芯片": {"name": "AI芯片", "source_status": "missing", "final_source": "missing"},
        },
        "securities": {},
        "market_quote_snapshot": {"trade_date": "2026-06-30", "snapshot_time": "14:45:00", "etf_count": 0, "index_count": 0, "sector_count": 1},
    }
    coverage = calculate_agent_report_core_coverage(context)
    context["agent_report_core_coverage"] = coverage
    context["data_quality_summary"] = {
        "market": {
            "etf_success": 0,
            "etf_total": 0,
            "index_success": 0,
            "index_total": 0,
            "sector_success": 1,
            "sector_total": 2,
            "sector_missing_text": "AI芯片",
        },
        "holdings": {"total": 0, "quote_success": 0},
    }

    report = render_agent_report(context, [], "", {"status": "skipped", "error_reason": "LLM disabled"}, "config.yaml", "db.sqlite3", "1445")

    assert coverage["groups"]["sector"]["coverage"] == 50.0
    assert "板块行情：1/2，缺失：AI芯片" in report


def test_no_agent_logic_modified():
    repo_root = Path(__file__).resolve().parents[2]
    output = subprocess.check_output(
        ["git", "diff", "--name-only", "--", "tradingagents/agents", "tradingagents/graph/trading_graph.py"],
        cwd=repo_root,
        text=True,
    ).strip()
    assert output == ""
