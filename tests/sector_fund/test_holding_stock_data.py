import json
import sqlite3
from pathlib import Path

from tradingagents.sector_fund.db import initialize_database
from tradingagents.sector_fund.fund_context_report import run_fund_context_report
from tradingagents.sector_fund.analyze_holdings import run_analyze_holdings
from tradingagents.sector_fund.holding_stock_data import (
    HoldingStock,
    collect_holding_stock_codes,
    compute_holding_stock_ma_fields,
    write_holding_stock_quotes_to_sql,
)


def test_collect_holding_stock_codes_from_enrichment_json(tmp_path):
    db_path = tmp_path / "fund.sqlite3"
    config_path = tmp_path / "portfolio.yaml"
    config_path.write_text(f"database:\n  path: {db_path.as_posix()}\n", encoding="utf-8")
    initialize_database(db_path)
    payload = {
        "tracking": {
            "stocks": [
                {"code": "603986", "name": "兆易创新", "holding_weight_pct": 8.8},
                {"code": "688525", "name": "佰维存储", "holding_weight_pct": 7.5},
            ]
        }
    }
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO fund_enrichment_result (run_id, fund_code, fund_name, auto_enriched_json) VALUES (?, ?, ?, ?)",
            ("run1", "025500", "东方阿尔法科技智选混合C", json.dumps(payload, ensure_ascii=False)),
        )

    rows = collect_holding_stock_codes(config_path=str(config_path), db_path=str(db_path), top_n=1)

    assert len(rows) == 1
    assert rows[0].stock_code == "603986"
    assert rows[0].stock_name == "兆易创新"


def test_holding_stock_ma_fields_and_sql_write(tmp_path):
    db_path = tmp_path / "fund.sqlite3"
    stock = HoldingStock("025500", "603986", "兆易创新", 8.8)
    quotes = {
        "603986": {
            "code": "603986",
            "name": "兆易创新",
            "latest_price": 88.5,
            "change_pct": -1.2,
            "amount": 123456789,
            "turnover_rate": 2.1,
            "source": "eastmoney_push2",
            "final_source": "eastmoney_push2",
            "source_status": "success",
            "parser_status": "success",
        }
    }
    history = {
        "603986": {
            "indicator": {"ma5": 87.1, "ma10": 85.2, "ma20": 82.3},
            "trade_date": "2026-06-29",
            "source": "baostock",
            "final_source": "baostock",
            "source_status": "success",
            "parser_status": "success",
        }
    }
    ma = compute_holding_stock_ma_fields(quotes, history)
    result = write_holding_stock_quotes_to_sql(str(db_path), "run-test", [stock], quotes, ma, decision_time="1445")

    assert ma["603986"]["trend_status"] == "above_ma20"
    assert result["security_quote_snapshot_rows"] == 1
    assert result["field_source_rows"] >= 15
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        quote = conn.execute("SELECT * FROM security_quote_snapshot WHERE code='603986'").fetchone()
        assert quote["latest_price"] == 88.5
        assert quote["ma20"] == 82.3
        assert quote["trend_status"] == "above_ma20"
        assert conn.execute("SELECT COUNT(*) FROM field_source WHERE entity_code='603986'").fetchone()[0] >= 15


def test_context_and_holdings_reports_use_holding_quotes(tmp_path):
    db_path = tmp_path / "fund.sqlite3"
    config_path = tmp_path / "portfolio.yaml"
    config_path.write_text(f"database:\n  path: {db_path.as_posix()}\n", encoding="utf-8")
    stock = HoldingStock("025500", "603986", "兆易创新", 8.8)
    quotes = {"603986": {"latest_price": 88.5, "change_pct": -1.2, "amount": 10, "turnover_rate": 2.1, "source": "eastmoney_push2", "final_source": "eastmoney_push2", "source_status": "success", "parser_status": "success"}}
    ma = {"603986": {"ma5": 87.1, "ma10": 85.2, "ma20": 82.3, "below_ma20": 0, "trend_status": "above_ma20", "source_status": "success", "parser_status": "success", "final_source": "baostock"}}
    write_holding_stock_quotes_to_sql(str(db_path), "run-test", [stock], quotes, ma)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO fund_enrichment_result (run_id, fund_code, fund_name, auto_enriched_json) VALUES (?, ?, ?, ?)",
            ("run1", "025500", "东方阿尔法科技智选混合C", json.dumps({"tracking": {"stocks": [{"code": "603986", "name": "兆易创新"}]}}, ensure_ascii=False)),
        )

    context_result = run_fund_context_report(str(config_path), output_dir=tmp_path)
    holdings_result = run_analyze_holdings(str(config_path), output_dir=tmp_path)

    context_text = Path(context_result["report_path"]).read_text(encoding="utf-8")
    holdings_text = Path(holdings_result["report_path"]).read_text(encoding="utf-8")
    assert "above_ma20" in context_text
    assert "88.5" in holdings_text
    assert "对基金影响" in holdings_text
