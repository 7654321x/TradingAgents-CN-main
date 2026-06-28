from tradingagents.sector_fund.data_audit import build_audit_rows, render_summary_markdown
from tradingagents.sector_fund.data_probe import ProbeRecord


def test_same_upstream_group_is_reported_as_consistency_check_not_independent_cross_validation():
    records = [
            ProbeRecord(
                source_name="tiantian_020671",
                source_type="tiantian_fund_estimate",
                category="天天基金基金估算",
                entity_type="fund",
            entity_code="020671",
            matched_fields=["fund.020671.estimate_nav"],
            data={"estimate_nav": 1.2, "source": "tiantianfund_direct", "source_status": "success"},
        ),
            ProbeRecord(
                source_name="akshare_020671",
                source_type="akshare_fund_estimate",
                category="AKShare 基金估算",
                entity_type="fund",
            entity_code="020671",
            matched_fields=["akshare.fund.020671.estimate_nav"],
            data={"estimate_nav": 1.21, "source": "akshare", "source_status": "success"},
        ),
    ]
    rows = build_audit_rows(records, "run", "2026-06-28T15:00:00", "config.yaml")

    report = render_summary_markdown(rows, {"core_coverage_rate": 100, "all_coverage_rate": 100}, [])

    assert "read_consistency_check" in report
    assert "independent_cross_validation" not in report
