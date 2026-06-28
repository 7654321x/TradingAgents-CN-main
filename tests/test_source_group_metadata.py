from tradingagents.sector_fund.data_audit import build_audit_rows
from tradingagents.sector_fund.data_probe import ProbeRecord


def _record(source_type, data_source, entity_type="fund", field="estimate_nav"):
    return ProbeRecord(
        source_name=f"{source_type}_x",
        source_type=source_type,
        category="test",
        entity_type=entity_type,
        entity_code="x",
        matched_fields=[f"{data_source}.{entity_type}.x.{field}"],
        data={field: 1, "source": data_source, "source_status": "success"},
    )


def test_source_group_metadata():
    rows = build_audit_rows(
        [
            _record("tiantian_fund_estimate", "tiantianfund_direct"),
            _record("eastmoney_push2_quote", "eastmoney_push2", entity_type="etf", field="latest_price"),
            _record("akshare_fund_estimate", "akshare"),
            _record("baostock_daily_k", "baostock", entity_type="etf", field="latest_close"),
        ],
        "run",
        "2026-06-28T15:00:00",
        "config.yaml",
    )

    by_source = {row["source"]: row for row in rows}
    assert by_source["tiantianfund_direct"]["upstream_group"] == "eastmoney"
    assert by_source["eastmoney_push2"]["upstream_group"] == "eastmoney"
    assert by_source["akshare"]["upstream_group"] == "eastmoney"
    assert by_source["baostock"]["upstream_group"] == "baostock"
    assert by_source["baostock"]["independent"] is True
    assert by_source["akshare"]["independent"] is False
