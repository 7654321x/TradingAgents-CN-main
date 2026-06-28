from tradingagents.sector_fund.data_probe import ProbeRecord, calculate_probe_coverage


def test_core_coverage_deduplicates_baostock_missing_when_eastmoney_has_index_quote():
    records = [
        ProbeRecord(
            source_name="baostock_index_科创50",
            source_type="baostock_daily_k",
            category="Baostock 日K",
            entity_type="index",
            entity_code="科创50",
            entity_name="科创50",
            fetch_status="missing",
            parser_status="no_data",
            missing_fields=[
                "baostock.index.科创50.latest_close",
                "baostock.index.科创50.pct_chg",
                "baostock.index.科创50.source_status",
            ],
            data={"source_status": "missing"},
            core_fields=[
                "baostock.index.科创50.latest_close",
                "baostock.index.科创50.pct_chg",
                "baostock.index.科创50.source_status",
            ],
        ),
        ProbeRecord(
            source_name="eastmoney_quote_index_科创50",
            source_type="eastmoney_push2_quote",
            category="东方财富盘中行情",
            entity_type="index",
            entity_code="科创50",
            entity_name="科创50",
            fetch_status="success",
            parser_status="success",
            matched_fields=[
                "eastmoney.index.科创50.latest_price",
                "eastmoney.index.科创50.change_pct",
                "eastmoney.index.科创50.source_status",
            ],
            data={"latest_price": 1200, "change_pct": 1.1, "source_status": "success"},
            core_fields=[
                "eastmoney.index.科创50.latest_price",
                "eastmoney.index.科创50.change_pct",
                "eastmoney.index.科创50.source_status",
            ],
        ),
    ]

    coverage = calculate_probe_coverage(records)

    assert coverage["core_total_count"] == 3
    assert coverage["core_matched_count"] == 3
    assert coverage["core_coverage_rate"] == 100
    assert coverage["core_missing_fields"] == []

