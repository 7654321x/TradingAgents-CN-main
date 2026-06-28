from tradingagents.sector_fund import data_probe
from tradingagents.sector_fund.data_probe import ProbeRecord, calculate_probe_coverage


def test_core_coverage_counts_fund_and_quote_fields():
    records = [
        ProbeRecord(
            source_name="fund",
            source_type="tiantian",
            category="天天基金基金估算",
            matched_fields=["fund.020671.estimate_nav", "fund.020671.estimate_change_pct"],
            missing_fields=["fund.020671.estimate_time"],
            core_fields=["fund.020671.estimate_nav", "fund.020671.estimate_change_pct", "fund.020671.estimate_time"],
        ),
        ProbeRecord(
            source_name="quote",
            source_type="eastmoney",
            category="东方财富盘中行情",
            matched_fields=["eastmoney.etf.512480.latest_price", "eastmoney.etf.512480.change_pct"],
            missing_fields=[],
            core_fields=["eastmoney.etf.512480.latest_price", "eastmoney.etf.512480.change_pct"],
        ),
        ProbeRecord(
            source_name="raw",
            source_type="raw",
            category="网页 raw 兜底",
            matched_fields=[],
            missing_fields=["raw.cninfo.announcement"],
            core_fields=[],
        ),
    ]

    coverage = calculate_probe_coverage(records)

    assert coverage["core_coverage_rate"] == 80.0
    assert coverage["all_coverage_rate"] == 66.67
    assert "raw.cninfo.announcement" not in coverage["core_missing_fields"]


class FakeResponse:
    ok = True
    status_code = 200
    text = "<html>no useful fields</html>"
    apparent_encoding = "utf-8"
    encoding = "utf-8"


def test_raw_parser_no_match_records_error_reason(monkeypatch, tmp_path):
    monkeypatch.setattr(data_probe.requests, "get", lambda *args, **kwargs: FakeResponse())

    record = data_probe._http_record(
        source_name="raw",
        source_type="raw_text_fallback",
        category="网页 raw 兜底",
        entity_type="raw",
        url="https://example.com",
        raw_dir=tmp_path,
        timeout=1,
        parser=lambda text: {},
        expected_fields=["raw.example.field"],
        core_fields=[],
    )

    assert record.parser_status == "no_match"
    assert record.error_reason == "fetch succeeded but parser matched no expected fields"
