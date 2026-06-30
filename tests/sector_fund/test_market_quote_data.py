import json
import sqlite3
from pathlib import Path

import main

from tradingagents.sector_fund.db import initialize_database
from tradingagents.sector_fund.fund_agent_report import render_agent_report, run_fund_agent_report
from tradingagents.sector_fund.fund_context_report import build_fund_context
from tradingagents.sector_fund.fund_sql_list import list_sql_fields_for_context
from tradingagents.sector_fund.market_quote_data import collect_market_quote_targets, write_market_quotes_to_sql


def test_refresh_market_quotes_cli_args():
    parser = main.build_parser()

    args = parser.parse_args(["--mode", "fund_agent_report", "--refresh-market-quotes", "--unique-report-name"])

    assert args.refresh_market_quotes is True
    assert args.unique_report_name is True


def test_market_quote_targets_from_config_and_sql(tmp_path):
    db_path = tmp_path / "fund.sqlite3"
    initialize_database(db_path)
    config = {
        "funds": [
            {
                "tracking": {
                    "etfs": ["512480"],
                    "indices": ["科创50"],
                    "sectors": ["半导体"],
                }
            }
        ],
        "etfs": [{"code": "159995", "name": "芯片ETF"}],
    }
    enriched = {"tracking": {"etfs": ["588200"], "indices": ["创业板指"], "sectors": ["存储芯片"]}}
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO fund_enrichment_result (run_id, fund_code, fund_name, auto_enriched_json) VALUES ('run1', '020671', '测试', ?)",
            (json.dumps(enriched, ensure_ascii=False),),
        )
        targets = collect_market_quote_targets(config, sql_conn=conn)

    assert {item["code"] for item in targets["etfs"]} == {"512480", "159995", "588200"}
    assert set(targets["indices"]) == {"科创50", "创业板指"}
    assert set(targets["sectors"]) == {"半导体", "存储芯片"}


def test_market_quotes_written_to_security_quote_snapshot_and_field_source(tmp_path):
    db_path = tmp_path / "fund.sqlite3"

    result = write_market_quotes_to_sql(
        db_path=db_path,
        run_id="market-run",
        trade_date="2026-06-29",
        decision_time="1445",
        snapshot_time="14:45:00",
        etf_quotes={
            "512480": {
                "name": "半导体ETF",
                "latest_price": 1.23,
                "change_pct": 2.1,
                "amount": 123,
                "source": "eastmoney_push2",
                "final_source": "eastmoney_push2",
                "source_status": "success",
            }
        },
        index_quotes={
            "科创50": {
                "name": "科创50",
                "latest_price": 888,
                "change_pct": 1.2,
                "amount": 456,
                "source": "eastmoney_push2",
                "final_source": "eastmoney_push2",
                "source_status": "success",
            }
        },
        sector_quotes={
            "半导体": {
                "name": "半导体",
                "change_pct": 3.4,
                "amount": 789,
                "source": "eastmoney_push2_sector",
                "final_source": "eastmoney_push2",
                "source_status": "success",
            }
        },
    )

    assert result["security_quote_snapshot_rows"] == 3
    assert result["field_source_rows"] > 0
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT entity_type, code, change_pct, final_source FROM security_quote_snapshot").fetchall()
        assert {(row["entity_type"], row["code"]) for row in rows} == {("etf", "512480"), ("index", "科创50"), ("sector", "半导体")}
        assert all(row["final_source"] in {"eastmoney_push2", "akshare"} for row in rows)
        assert conn.execute("SELECT COUNT(*) FROM field_source WHERE semantic_field='etf.512480.latest_price'").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM field_source WHERE semantic_field='sector.半导体.change_pct'").fetchone()[0] == 1


def test_fund_agent_context_prefers_today_market_quotes(tmp_path):
    db_path = tmp_path / "fund.sqlite3"
    initialize_database(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO security_quote_snapshot
            (entity_type, code, name, trade_date, snapshot_time, latest_price, change_pct, source, source_status, final_source)
            VALUES ('etf', '512480', '半导体ETF', '2026-06-26', '14:45:00', 1.11, -1.0, 'baostock', 'success', 'baostock')
            """
        )
        conn.execute(
            """
            INSERT INTO security_quote_snapshot
            (entity_type, code, name, trade_date, snapshot_time, latest_price, change_pct, amount, source, source_status, final_source, audit_status)
            VALUES ('etf', '512480', '半导体ETF', '2026-06-29', '14:45:00', 1.23, 2.1, 123, 'eastmoney_push2', 'success', 'eastmoney_push2', 'ok')
            """
        )

    fields = list_sql_fields_for_context(db_path, decision_time="1445")
    context = build_fund_context(fields, decision_time="1445")

    assert context["etfs"]["512480"]["latest_price"] == 1.23
    assert context["etfs"]["512480"]["final_source"] == "eastmoney_push2"
    assert context["market_quote_snapshot"]["etf_count"] == 1
    assert context["stale_field_count"] == 0


def test_etf_report_not_using_old_baostock_as_today():
    context = {
        "data_date": "2026-06-29",
        "market_quote_snapshot": {"trade_date": "2026-06-29", "snapshot_time": "14:45:00", "etf_count": 1, "index_count": 1, "sector_count": 1},
        "etfs": {"512480": {"name": "半导体ETF", "latest_price": 1.23, "change_pct": 2.1, "amount": 123, "final_source": "eastmoney_push2", "source_status": "success"}},
        "indices": {"科创50": {"name": "科创50", "latest_price": 888, "change_pct": 1.2, "amount": 456, "final_source": "eastmoney_push2", "source_status": "success"}},
        "sectors": {"半导体": {"name": "半导体", "change_pct": 3.4, "final_source": "eastmoney_push2", "source_status": "success"}},
        "funds": {},
    }

    report = render_agent_report(context, [], "", {"status": "missing_api_key"}, "config.yaml", "db.sqlite3", "1445")

    assert "ETF 今日盘中表现（2026-06-29 14:45:00）" in report
    assert "512480" in report
    assert "科创50" in report
    assert "半导体" in report
    assert "2026-06-26" not in report
    assert "今日ETF实时数据缺失" not in report


def test_unique_report_name(monkeypatch, tmp_path):
    db_path = tmp_path / "fund.sqlite3"
    config_path = tmp_path / "portfolio.yaml"
    config_path.write_text(f"database:\n  path: {db_path.as_posix()}\n", encoding="utf-8")
    initialize_database(db_path)

    monkeypatch.setattr("tradingagents.sector_fund.fund_agent_report.refresh_market_quotes", lambda **kwargs: {"summary": {}, "write_result": {}, "market_quote_count": 0})

    result = run_fund_agent_report(
        str(config_path),
        output_dir=tmp_path,
        decision_time="1445",
        use_llm=False,
        refresh_market_quotes_enabled=True,
        unique_report_name=True,
    )

    path = Path(result["report_path"])
    assert path.exists()
    assert path.name.startswith("fund_agent_report_")
    assert len(path.stem.split("_")) >= 6
