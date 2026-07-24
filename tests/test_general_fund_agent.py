from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from tradingagents.extensions.fund_agent import (
    FundAnalysisProfile,
    build_general_fund_agent_prompt,
    profile_payload,
    resolve_fund_analysis_profile,
)
from tradingagents.extensions.fund_agent.runtime import (
    analyze_fund_database_only,
    classify_fund_analysis_mode,
)
from tradingagents.storage.db import init_db


def test_generic_prompt_parameterizes_fund_theme_and_history_policy():
    prompt = build_general_fund_agent_prompt(
        FundAnalysisProfile(
            fund_code="123456",
            theme_name="新能源",
            industry_chain_buckets=("上游资源", "电池", "整车"),
            cycle_indicators=("电池价格",),
            event_keywords=("补贴政策",),
            official_domains=("example.gov.cn",),
            b_level_domains=("eastmoney.com",),
        )
    )
    assert "当前请求基金代码：123456" in prompt
    assert "主题：新能源" in prompt
    assert "上游资源" in prompt
    assert "历史相似行情修正当前停用" in prompt
    assert "概率输出当前停用" in prompt
    assert "当日行情只能从 MCP 抓取" in prompt
    assert "系统不做无人值守持续抓取" in prompt
    assert "搜索摘要不得直接入库或计分" in prompt
    assert "Firecrawl 后台抓取" in prompt
    assert "example.gov.cn" in prompt
    assert "eastmoney.com" in prompt
    assert "020671" not in prompt


def test_generic_prompt_can_enable_audited_history_policy():
    prompt = build_general_fund_agent_prompt(
        FundAnalysisProfile(
            fund_code="654321",
            enable_historical_adjustment=True,
            enable_probability_output=True,
            minimum_probability_samples=40,
        )
    )
    assert "修正范围为-5至+5分" in prompt
    assert "有效历史样本不少于40" in prompt


def test_profile_registry_uses_explicit_theme_and_safe_generic_fallback():
    semiconductor = resolve_fund_analysis_profile("020671", {"source_url": "https://www.efunds.com.cn/fund/020671"})
    generic = resolve_fund_analysis_profile("999999", {"source_url": "https://manager.example/fund/999999"})

    assert semiconductor.theme_name == "半导体"
    assert "设备" in semiconductor.industry_chain_buckets
    assert "manager.example" in generic.official_domains
    assert generic.theme_name == "未分类主题（待核验）"
    assert profile_payload(semiconductor)["fund_code"] == "020671"


def test_runtime_mode_requires_both_verified_target_etf_and_index():
    assert classify_fund_analysis_mode(
        {"target_etf_code": "589130", "benchmark_index_code": "000685"}
    ) == "INDEX_LINKED"
    assert classify_fund_analysis_mode({"target_etf_code": "589130"}) == "ACTIVE_DEGRADED"
    assert classify_fund_analysis_mode({}) == "ACTIVE_DEGRADED"


def test_active_fund_route_is_explicitly_degraded_when_disclosure_is_missing():
    engine = init_db(create_engine("sqlite+pysqlite:///:memory:"))
    with Session(engine) as session:
        result = analyze_fund_database_only(
            session, fund_code="999999", analysis_date="2026-07-24"
        )
    assert result.mode == "ACTIVE_DEGRADED"
    assert result.status == "DEGRADED_DATA_UNAVAILABLE"
    assert "不会以其他基金" in result.limitations[-1]
