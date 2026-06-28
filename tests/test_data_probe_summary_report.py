from tradingagents.sector_fund.data_audit import write_audit_outputs
from tradingagents.sector_fund.data_probe import ProbeRecord


def test_data_probe_summary_report_is_generated(tmp_path):
    records = [
        ProbeRecord(
            source_name="eastmoney_quote_etf_512480",
            source_type="eastmoney_push2_quote",
            category="东方财富盘中行情",
            entity_type="etf",
            entity_code="512480",
            entity_name="半导体ETF",
            fetch_status="success",
            parser_status="success",
            matched_fields=["eastmoney.etf.512480.latest_price", "eastmoney.etf.512480.change_pct"],
            data={"latest_price": 1.2, "change_pct": 1.5, "source_status": "success"},
        )
    ]
    coverage = {"core_coverage_rate": 100, "all_coverage_rate": 100, "all_matched_count": 2}

    result = write_audit_outputs(records, coverage, "config/test.yaml", tmp_path / "raw", tmp_path, "run1")

    summary = result["summary_path"].read_text(encoding="utf-8")
    assert "# data_probe 数据摘要" in summary
    assert "## 2. ETF 数据" in summary
    assert "半导体ETF" in summary
