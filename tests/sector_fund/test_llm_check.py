from tradingagents.sector_fund import llm_check
from tradingagents.sector_fund import llm_provider_resolver


def test_llm_check_no_secret_leak(monkeypatch):
    secret = "sk-secret-value"
    monkeypatch.setenv("DASHSCOPE_API_KEY", secret)

    def fake_post(*args, **kwargs):
        class Response:
            status_code = 401
            text = "invalid_api_key"

        return Response()

    monkeypatch.setattr(llm_check.requests, "post", fake_post)
    result = llm_check.run_llm_check(view=False)
    rendered = llm_check.render_llm_check(result)

    assert result["providers"]["dashscope"]["api_status"] == "invalid_api_key"
    assert secret not in rendered
    assert "invalid_api_key" in rendered


def test_llm_check_missing(monkeypatch):
    for name in ["DASHSCOPE_API_KEY", "DASH_SCOPE_API_KEY", "QWEN_API_KEY", "DEEPSEEK_API_KEY", "OPENAI_API_KEY"]:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("FUND_AGENT_REPORT_PROVIDER", raising=False)
    monkeypatch.setattr(llm_check, "load_env", lambda: None)
    monkeypatch.setattr(llm_provider_resolver, "load_env", lambda: None)

    result = llm_check.run_llm_check(view=False)

    assert result["providers"]["dashscope"]["api_status"] == "missing"
    assert result["providers"]["openai"]["key_status"] == "missing"
