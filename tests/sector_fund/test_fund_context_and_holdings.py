import sqlite3
import json
from pathlib import Path

from tradingagents.sector_fund.analyze_holdings import run_analyze_holdings
from tradingagents.sector_fund.db import initialize_database
from tradingagents.sector_fund.fund_context_report import run_fund_context_report


def _seed_context_db(db_path: Path) -> None:
    initialize_database(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO portfolio (id, name, total_position_pct, target_position_pct, max_position_pct) VALUES (1, 'test', 20, 30, 35)"
        )
        conn.execute(
            """
            INSERT INTO fund_config
            (portfolio_id, fund_code, fund_name, fund_type, role, position_pct)
            VALUES (1, '025500', '东方阿尔法科技智选混合C', 'active_equity', 'aggressive', 8)
            """
        )
        conn.execute(
            """
            INSERT INTO fund_holding_snapshot
            (fund_code, report_date, holding_stock_code, holding_stock_name, holding_weight_pct, source, source_status)
            VALUES ('025500', '2026-03-31', '603986', '兆易创新', 8.8, 'akshare', 'success')
            """
        )
        conn.execute(
            """
            INSERT INTO security_quote_snapshot
            (entity_type, code, name, trade_date, snapshot_time, latest_price, change_pct, source, source_status)
            VALUES ('stock', '603986', '兆易创新', '2026-06-29', '14:45:00', 88.5, -1.2, 'eastmoney', 'success')
            """
        )
        conn.execute(
            """
            INSERT INTO security_indicator_daily
            (code, trade_date, ma5, ma10, ma20)
            VALUES ('603986', '2026-06-29', 87.1, 85.2, 82.3)
            """
        )


def test_fund_context_report_groups_holdings_and_securities(tmp_path):
    db_path = tmp_path / "fund.sqlite3"
    config_path = tmp_path / "portfolio.yaml"
    config_path.write_text(f"database:\n  path: {db_path.as_posix()}\n", encoding="utf-8")
    _seed_context_db(db_path)

    result = run_fund_context_report(str(config_path), output_dir=tmp_path, decision_time="1445")
    fund = result["context"]["funds"]["025500"]

    assert fund["holdings"][0]["code"] == "603986"
    assert fund["holdings"][0]["weight_pct"] == 8.8
    assert result["context"]["securities"]["603986"]["latest_price"] == 88.5
    assert Path(result["report_path"]).exists()


def test_analyze_holdings_outputs_deep_stock_table(tmp_path):
    db_path = tmp_path / "fund.sqlite3"
    config_path = tmp_path / "portfolio.yaml"
    config_path.write_text(f"database:\n  path: {db_path.as_posix()}\n", encoding="utf-8")
    _seed_context_db(db_path)

    result = run_analyze_holdings(str(config_path), output_dir=tmp_path, decision_time="1445")
    analysis = result["analysis"]

    assert analysis["summary"]["holding_row_count"] == 1
    assert analysis["holdings"][0]["stock_code"] == "603986"
    assert analysis["holdings"][0]["change_pct"] == -1.2
    assert analysis["holdings"][0]["data_status"] == "ok"
    assert Path(result["report_path"]).exists()
    assert Path(result["json_path"]).exists()


def test_context_uses_auto_enriched_tracking_stocks_when_holding_table_empty(tmp_path):
    db_path = tmp_path / "fund.sqlite3"
    config_path = tmp_path / "portfolio.yaml"
    config_path.write_text(f"database:\n  path: {db_path.as_posix()}\n", encoding="utf-8")
    initialize_database(db_path)
    enriched = {
        "code": "025500",
        "name": "东方阿尔法科技智选混合C",
        "tracking": {"stocks": [{"code": "603986", "name": "兆易创新", "source": "akshare_holdings"}]},
    }
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO fund_enrichment_result
            (run_id, fund_code, fund_name, auto_enriched_json)
            VALUES ('run1', '025500', '东方阿尔法科技智选混合C', ?)
            """,
            (json.dumps(enriched, ensure_ascii=False),),
        )

    result = run_fund_context_report(str(config_path), output_dir=tmp_path, decision_time="1445")

    assert result["context"]["funds"]["025500"]["holdings"][0]["code"] == "603986"
