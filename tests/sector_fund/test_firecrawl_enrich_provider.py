from tradingagents.sector_fund import firecrawl_enrich_provider as provider_module
from tradingagents.sector_fund.firecrawl_enrich_provider import FirecrawlEnrichProvider


def test_firecrawl_missing_key_not_crash(monkeypatch):
    monkeypatch.setattr(provider_module, "_load_firecrawl_key", lambda: "")

    result = FirecrawlEnrichProvider().search_fund_info("025500")

    assert result["source_status"] == "firecrawl_missing_key"
    assert result["parser_status"] == "skipped"


def test_firecrawl_result_sanitized(monkeypatch):
    secret = "fc-secret-test"

    class FakeResponse:
        status_code = 200

        def __init__(self, body):
            self._body = body
            self.text = "ok"

        def json(self):
            return self._body

    def fake_post(url, headers, json, timeout):
        assert headers["Authorization"] == f"Bearer {secret}"
        if url.endswith("/v2/search"):
            return FakeResponse({"success": True, "data": {"web": [{"url": "https://example.com/fund", "title": "基金档案"}]}})
        return FakeResponse({"success": True, "data": {"markdown": f"基金经理：张三\n业绩比较基准：中证指数\n投资范围：本基金主要投资股票和债券\n基金管理人：测试基金管理有限公司\n{secret}"}})

    monkeypatch.setattr(provider_module, "_load_firecrawl_key", lambda: secret)
    monkeypatch.setattr(provider_module.requests, "post", fake_post)

    result = FirecrawlEnrichProvider().search_fund_info("025500", "测试基金")

    assert result["source_status"] == "success"
    assert result["extracted"]["fund_manager"] == "张三"
    assert secret not in str(result["results"])
