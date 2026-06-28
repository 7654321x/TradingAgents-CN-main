from tradingagents.sector_fund.data_audit import build_audit_rows, render_terminal_summary
from tradingagents.sector_fund.data_probe import ProbeRecord


def test_kc50_terminal_view_shows_baostock_missing_eastmoney_success():
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
                "baostock.index.科创50.kline",
                "baostock.index.科创50.latest_close",
                "baostock.index.科创50.pct_chg",
                "baostock.index.科创50.source_status",
            ],
            error_reason="baostock returned no rows",
            data={"rows": 0, "source_status": "missing"},
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
        ),
    ]
    rows = build_audit_rows(records, "run", "2026-06-28T16:00:00", "config.yaml")

    output = render_terminal_summary(rows, {"core_coverage_rate": 100, "all_coverage_rate": 50})

    assert "科创50：Baostock missing，EastMoney success，最终采用 EastMoney。" in output
    assert "use eastmoney index quote as primary source" in output

