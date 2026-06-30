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
        "DASHSCOPE_MODEL",
        "DEEPSEEK_MODEL",
        "OPENAI_MODEL",
        "DASHSCOPE_BASE_URL",
        "DEEPSEEK_BASE_URL",
        "OPENAI_BASE_URL",
    ]:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(resolver, "load_env", lambda path=".env": None)


def test_env_provider_overrides_dashscope_default(monkeypatch):
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("DASHSCOPE_API_KEY", "dash-key")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deep-key")
    monkeypatch.setenv("FUND_AGENT_REPORT_PROVIDER", "deepseek")

    resolved = resolver.resolve_provider()

    assert resolved["provider"] == "deepseek"
    assert resolved["provider_source"] == "env"
    assert resolved["model"] == "deepseek-chat"


def test_cli_provider_overrides_env_provider(monkeypatch):
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deep-key")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.setenv("FUND_AGENT_REPORT_PROVIDER", "deepseek")

    resolved = resolver.resolve_provider("openai")

    assert resolved["provider"] == "openai"
    assert resolved["provider_source"] == "cli"


def test_default_provider_can_be_dashscope(monkeypatch):
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("DASHSCOPE_API_KEY", "dash-key")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deep-key")

    resolved = resolver.resolve_provider()

    assert resolved["provider"] == "dashscope"
    assert resolved["provider_source"] == "default"
