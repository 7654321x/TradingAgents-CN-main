import sqlite3

from tradingagents.sector_fund.data_probe import ProbeRecord, _write_sql_diagnostics


def test_data_probe_writes_sql_diagnostics(tmp_path):
    db_path = tmp_path / "probe.sqlite3"
    records = [
        ProbeRecord(
            source_name="tiantian_fund_estimate_020671",
            source_type="tiantian_fund_estimate",
            category="天天基金基金估算",
            entity_type="fund",
            entity_code="020671",
            fetch_status="success",
            status_code=200,
            raw_text_length=128,
            matched_fields=["fund.020671.estimate_nav"],
            missing_fields=["fund.020671.estimate_time"],
            data={"fund.020671.estimate_nav": 1.23},
        )
    ]

    status = _write_sql_diagnostics(db_path, "run-test", "2026-06-28", records)

    assert status["status"] == "success"
    with sqlite3.connect(db_path) as conn:
        run_count = conn.execute("SELECT COUNT(*) FROM data_source_run").fetchone()[0]
        field_count = conn.execute("SELECT COUNT(*) FROM field_source").fetchone()[0]
        statuses = {
            row[0]
            for row in conn.execute("SELECT audit_status FROM field_source").fetchall()
        }
    assert run_count == 1
    assert field_count == 2
    assert {"ok", "missing"} <= statuses
