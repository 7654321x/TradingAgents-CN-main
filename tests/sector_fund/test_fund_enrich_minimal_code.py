from pathlib import Path

import yaml

from tradingagents.sector_fund import fund_enrich


def _fake_akshare_payload(codes, fund_types, raw_dir):
    code = codes[0]
    return {
        "availability": {"source_status": "success"},
        "estimates": {
            code: {
                "source_status": "success",
                "fund_name": "东方阿尔法科技智选混合C",
                "estimate_nav": 2.5,
                "estimate_change_pct": 1.2,
                "published_nav": 2.4,
                "published_change_pct": 0.8,
            }
        },
        "daily": {code: {"source_status": "success", "fund_name": "东方阿尔法科技智选混合C", "purchase_status": "开放申购", "redeem_status": "开放赎回"}},
        "nav_history": {code: [{"nav_date": "2026-06-26", "unit_nav": 2.4}]},
        "holdings": {
            code: {
                "source_status": "success",
                "holding_is_stale": True,
                "top_holdings": [{"holding_stock_code": "603986", "holding_stock_name": "兆易创新", "holding_weight_pct": 8.8}],
            }
        },
    }


def test_fund_enrich_minimal_code_generates_enriched_config(monkeypatch, tmp_path):
    config_path = tmp_path / "minimal.yaml"
    config_path.write_text(
        """
portfolio:
  name: test
database:
  path: ":memory:"
funds:
  - code: "025500"
    enabled: true
""",
        encoding="utf-8",
    )
    monkeypatch.chdir(Path("D:/PycharmProjects/TradingAgents-CN-main"))
    monkeypatch.setattr(fund_enrich, "_fetch_akshare", _fake_akshare_payload)
    monkeypatch.setattr(fund_enrich, "_fetch_firecrawl", lambda codes, funds, raw_dir, use_firecrawl: {codes[0]: {"source_status": "skipped", "extracted": {}, "results": []}})
    monkeypatch.setattr(fund_enrich, "_write_sql", lambda *args, **kwargs: {"status": "success"})

    result = fund_enrich.run_fund_enrich(str(config_path), output_dir=tmp_path, raw_root=tmp_path / "raw", use_akshare=True, use_firecrawl=False)
    generated = yaml.safe_load(Path(result["enriched_config_path"]).read_text(encoding="utf-8"))

    item = generated["funds"][0]
    assert item["name"] == "东方阿尔法科技智选混合C"
    assert item["type"] in {"sector_theme", "active_equity"}
    assert item["estimate_nav"] == 2.5
    assert item["top_holdings"][0]["holding_stock_code"] == "603986"
    assert item["tracking"]["stocks"][0]["code"] == "603986"
