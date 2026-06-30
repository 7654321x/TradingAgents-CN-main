from tradingagents.sector_fund import fund_agent_report
from tradingagents.sector_fund import llm_provider_resolver as resolver


def _clear_provider_env(monkeypatch):
    for name in [
        "FUND_AGENT_REPORT_PROVIDER",
        "FUND_AGENT_REPORT_MODEL",
        "DASHSCOPE_API_KEY",
        "DASH_SCOPE_API_KEY",
        "QWEN_API_KEY",
        "DEEPSEEK_API_KEY",
        "OPENAI_API_KEY",
        "DASHSCOPE_BASE_URL",
        "DEEPSEEK_BASE_URL",
        "OPENAI_BASE_URL",
    ]:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(resolver, "load_env", lambda path=".env": None)


def test_fund_agent_report_uses_env_deepseek(monkeypatch):
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("DASHSCOPE_API_KEY", "dash-key")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deep-key")
    monkeypatch.setenv("FUND_AGENT_REPORT_PROVIDER", "deepseek")
    captured = {}

    def fake_post(url, headers, json, timeout):
        captured.update({"url": url, "headers": headers, "json": json, "timeout": timeout})

        class Response:
            status_code = 200
            text = "{}"

            def json(self):
                return {"choices": [{"message": {"content": "ok"}}]}

        return Response()

    monkeypatch.setattr(fund_agent_report.requests, "post", fake_post)

    result = fund_agent_report.call_llm("hello", timeout=1)

    assert result["status"] == "success"
    assert result["provider"] == "deepseek"
    assert result["provider_source"] == "env"
    assert result["model"] == "deepseek-chat"
    assert captured["url"].startswith("https://api.deepseek.com/v1/")
    assert captured["json"]["model"] == "deepseek-chat"
    assert captured["headers"]["Authorization"] == "Bearer deep-key"


def test_fund_agent_report_cli_provider_overrides_env(monkeypatch):
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deep-key")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.setenv("FUND_AGENT_REPORT_PROVIDER", "deepseek")
    captured = {}

    def fake_post(url, headers, json, timeout):
        captured.update({"url": url, "headers": headers, "json": json})

        class Response:
            status_code = 200
            text = "{}"

            def json(self):
                return {"choices": [{"message": {"content": "ok"}}]}

        return Response()

    monkeypatch.setattr(fund_agent_report.requests, "post", fake_post)

    result = fund_agent_report.call_llm("hello", provider_override="openai", timeout=1)

    assert result["status"] == "success"
    assert result["provider"] == "openai"
    assert result["provider_source"] == "cli"
    assert captured["url"].startswith("https://api.openai.com/v1/")
    assert captured["headers"]["Authorization"] == "Bearer openai-key"
