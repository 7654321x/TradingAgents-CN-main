import inspect

from tradingagents.sector_fund import data_probe


class FakeResponse:
    ok = True
    status_code = 200
    apparent_encoding = "utf-8"
    encoding = "utf-8"
    reason = "OK"

    def __init__(self, text):
        self.text = text


def test_data_probe_loops_over_configured_funds(monkeypatch, tmp_path):
    config_path = tmp_path / "funds.yaml"
    config_path.write_text(
        """
portfolio:
  name: test
database:
  path: test.sqlite3
data_sources: {}
funds:
  - code: "020671"
    name: "基金A"
    type: "etf_feeder"
    tracking: {etfs: [], indices: [], sectors: [], manual_holdings: []}
  - code: "025500"
    name: "基金B"
    type: "active_equity"
    tracking: {etfs: [], indices: [], sectors: [], manual_holdings: []}
  - code: "123456"
    name: "新增基金"
    type: "active_equity"
    tracking: {etfs: [], indices: [], sectors: [], manual_holdings: []}
""",
        encoding="utf-8",
    )

    monkeypatch.setattr(data_probe, "_probe_baostock", lambda config, raw_dir: [])
    monkeypatch.setattr(data_probe, "_probe_eastmoney_structured", lambda config, raw_dir, timeout: [])
    monkeypatch.setattr(data_probe, "_probe_raw_fallbacks", lambda config, raw_dir, timeout: [])
    monkeypatch.setattr(data_probe, "_probe_firecrawl", lambda config, raw_dir, timeout: [])
    monkeypatch.setattr(data_probe, "_write_sql_diagnostics", lambda *args, **kwargs: {"status": "success"})
    monkeypatch.setattr(
        data_probe.requests,
        "get",
        lambda url, **kwargs: FakeResponse('jsonpgz({"gsz":"1.23","gszzl":"2.34","dwjz":"1.20","gztime":"2026-06-28 14:45"});'),
    )

    result = data_probe.run_data_probe(str(config_path), output_dir=tmp_path, raw_root=tmp_path / "raw")

    estimate_records = [record for record in result["records"] if record["source_type"] == "tiantian_fund_estimate"]
    assert [record["entity_code"] for record in estimate_records] == ["020671", "025500", "123456"]
    assert "fund.123456.estimate_nav" in result["coverage"]["matched_fields"]
    source = inspect.getsource(data_probe._probe_tiantian_fund)
    assert "020671" not in source
    assert "025500" not in source
