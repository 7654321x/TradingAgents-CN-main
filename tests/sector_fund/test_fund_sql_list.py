import sqlite3
from pathlib import Path

from tradingagents.sector_fund.db import initialize_database
from tradingagents.sector_fund.fund_sql_list import list_sql_fields, run_fund_sql_list


def _seed_db(db_path: Path) -> None:
    initialize_database(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO portfolio (id, name, total_position_pct, target_position_pct, max_position_pct) VALUES (1, 'test', 20, 30, 35)"
        )
        conn.execute(
            """
            INSERT INTO fund_config
            (portfolio_id, fund_code, fund_name, fund_type, role, position_pct, tracking_json)
            VALUES (1, '020671', '易方达科创芯片ETF联接C', 'etf_feeder', 'base', 12, '{"etfs":["588200"]}')
            """
        )
        conn.execute(
            """
            INSERT INTO fund_intraday_estimate
            (fund_code, trade_date, decision_time, estimate_time, estimate_nav, estimate_change_pct, unit_nav_previous, estimate_source, source_status)
            VALUES ('020671', '2026-06-29', '1445', '2026-06-29 14:45:00', 1.23, -0.8, 1.24, 'tiantianfund', 'success')
            """
        )


def test_fund_sql_list_reads_all_core_fields(tmp_path):
    db_path = tmp_path / "fund.sqlite3"
    config_path = tmp_path / "portfolio.yaml"
    config_path.write_text(f"database:\n  path: {db_path.as_posix()}\n", encoding="utf-8")
    _seed_db(db_path)

    fields = list_sql_fields(db_path, decision_time="1445")
    names = {(field.table_name, field.field_name) for field in fields}

    assert ("fund_intraday_estimate", "estimate_change_pct") in names
    assert ("fund_config", "fund_name") in names

    result = run_fund_sql_list(str(config_path), output_dir=tmp_path, decision_time="1445")

    assert result["field_count"] > 0
    assert Path(result["report_path"]).exists()
    assert Path(result["json_path"]).exists()
