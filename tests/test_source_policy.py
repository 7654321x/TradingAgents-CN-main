from tradingagents.extensions.sector_fund.source_policy import (
    source_policy_for,
    source_policy_summary,
)


def test_current_market_policy_is_mcp_isolated_and_has_retry_failure_rule():
    policy = source_policy_for("current_daily_market")
    assert policy.primary_level == "B"
    assert policy.primary_domains == ("eastmoney.com",)
    assert "10jqka.com.cn" in policy.fallback_domains
    assert "sse.com.cn" in policy.verification_domains
    assert policy.acquisition_chain[1] == "firecrawl_backend_primary_page"
    assert policy.acquisition_chain[-1] == "chrome_manual_diagnostic_only_with_user_authorization"
    assert "never_write_market_bar_observation" in policy.cache_rule
    assert "do_not_substitute_history_or_estimate" in policy.missing_rule


def test_policy_summary_is_safe_static_report_input():
    summary = source_policy_summary()
    assert summary["official_nav"]["primary_level"] == "A"
    assert "csindex.com.cn" in summary["index_constituents"]["primary_domains"]
