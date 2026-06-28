from pathlib import Path

from tradingagents.sector_fund import fund_enrich


def test_enriched_config_not_overwrite_original(monkeypatch, tmp_path):
    original = """
portfolio:
  name: test
database:
  path: ":memory:"
funds:
  - code: "025500"
    enabled: true
"""
    config_path = tmp_path / "portfolio.yaml"
    config_path.write_text(original, encoding="utf-8")
    monkeypatch.chdir(Path("D:/PycharmProjects/TradingAgents-CN-main"))
    monkeypatch.setattr(
        fund_enrich,
        "_fetch_akshare",
        lambda codes, fund_types, raw_dir: {
            "availability": {"source_status": "success"},
            "estimates": {codes[0]: {"source_status": "success", "fund_name": "测试基金"}},
            "daily": {codes[0]: {"source_status": "success", "fund_name": "测试基金"}},
            "nav_history": {codes[0]: []},
            "holdings": {codes[0]: {"source_status": "failed", "top_holdings": []}},
        },
    )
    monkeypatch.setattr(fund_enrich, "_fetch_firecrawl", lambda codes, funds, raw_dir, use_firecrawl: {codes[0]: {"source_status": "skipped", "extracted": {}, "results": []}})
    monkeypatch.setattr(fund_enrich, "_write_sql", lambda *args, **kwargs: {"status": "success"})

    result = fund_enrich.run_fund_enrich(str(config_path), output_dir=tmp_path, raw_root=tmp_path / "raw", write_enriched_config=True)

    assert config_path.read_text(encoding="utf-8") == original
    assert Path(result["enriched_config_path"]).exists()
