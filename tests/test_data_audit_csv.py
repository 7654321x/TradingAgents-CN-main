import csv

from tradingagents.sector_fund.data_audit import write_audit_outputs
from tradingagents.sector_fund.data_probe import ProbeRecord


def test_data_audit_csv_is_generated_with_required_columns(tmp_path):
    records = [
        ProbeRecord(
            source_name="fund",
            source_type="tiantian_fund_estimate",
            category="天天基金基金估算",
            entity_type="fund",
            entity_code="020671",
            entity_name="基金A",
            fetch_status="success",
            parser_status="success",
            matched_fields=["fund.020671.estimate_nav"],
            data={"fund.020671.estimate_nav": 1.23},
        )
    ]

    result = write_audit_outputs(records, {"core_coverage_rate": 100, "all_coverage_rate": 100}, "cfg", tmp_path, tmp_path, "run1")

    with result["audit_csv_path"].open("r", encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))
    assert rows[0]["run_id"] == "run1"
    assert rows[0]["field_name"] == "fund.020671.estimate_nav"
    assert rows[0]["audit_status"] == "ok"
