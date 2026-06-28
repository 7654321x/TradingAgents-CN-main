import json
import sqlite3

from tradingagents.sector_fund.intraday_snapshot import build_intraday_snapshot, build_context_from_snapshot


def test_intraday_snapshot_can_save_and_load_from_sql(tmp_path):
    db_path = tmp_path / "fund.sqlite3"

    snapshot = build_intraday_snapshot(
        "config/personal_fund_portfolio.yaml",
        decision_time="1445",
        db_path=db_path,
        refresh_data=False,
        save_snapshot=True,
    )
    loaded = build_context_from_snapshot(snapshot["snapshot_id"], db_path)

    assert loaded["id"] == snapshot["snapshot_id"]
    assert loaded["decision_time"] == "1445"
    assert loaded["snapshot"]["funds"]


def test_intraday_snapshot_upserts_same_day_decision_time(tmp_path):
    db_path = tmp_path / "fund.sqlite3"

    first = build_intraday_snapshot("config/personal_fund_portfolio.yaml", "1000", db_path, False, save_snapshot=True)
    second = build_intraday_snapshot("config/personal_fund_portfolio.yaml", "1000", db_path, False, save_snapshot=True)

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT snapshot_json FROM intraday_snapshot").fetchall()
    assert first["snapshot_id"] == second["snapshot_id"]
    assert len(rows) == 1
    assert json.loads(rows[0][0])["funds"]
