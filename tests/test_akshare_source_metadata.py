from tradingagents.sector_fund.data_audit import build_audit_rows
from tradingagents.sector_fund.data_probe import ProbeRecord


def test_akshare_source_metadata_in_audit_rows():
    record = ProbeRecord(
        source_name="akshare_fund_estimate_020671",
        source_type="akshare_fund_estimate",
        category="AKShare 基金估算",
        entity_type="fund",
        entity_code="020671",
        matched_fields=["akshare.fund.020671.estimate_nav"],
        data={"estimate_nav": 1.2, "source": "akshare", "source_status": "success"},
    )

    row = build_audit_rows([record], "run", "2026-06-28T15:00:00", "config.yaml")[0]

    assert row["source"] == "akshare"
    assert row["upstream_group"] == "eastmoney"
    assert row["source_level"] == "structured_wrapper"
    assert row["independent"] is False
