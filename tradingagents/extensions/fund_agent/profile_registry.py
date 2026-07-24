"""Verified-profile defaults for the reusable fund analysis agent."""
from __future__ import annotations

from dataclasses import asdict
from typing import Any
from urllib.parse import urlparse

from .general_fund_agent import FundAnalysisProfile

_PROFILE_DEFAULTS: dict[str, dict[str, object]] = {
    "020671": {
        "theme_name": "半导体",
        "industry_chain_buckets": ("设备", "材料", "制造", "存储", "设计", "封测", "AI芯片", "高速互连"),
        "cycle_indicators": ("集成电路产量", "集成电路进出口", "半导体销售", "存储价格", "AI资本开支"),
        "event_keywords": ("基金公告", "国家大基金", "出口管制", "业绩预告", "并购", "解禁", "存储价格"),
        "official_domains": ("efunds.com.cn", "csindex.com.cn", "sse.com.cn", "szse.cn", "cninfo.com.cn", "stats.gov.cn", "customs.gov.cn", "miit.gov.cn"),
        "b_level_domains": ("eastmoney.com", "10jqka.com.cn", "1234567.com.cn"),
    }
}


def resolve_fund_analysis_profile(
    fund_code: str, identity: dict[str, Any] | None = None
) -> FundAnalysisProfile:
    """Resolve a profile without inferring an unverified investment theme.

    Known theme profiles are explicit.  Other funds retain a neutral profile
    until a verified identity/strategy adapter supplies dedicated taxonomy.
    """
    code = str(fund_code)
    values = dict(_PROFILE_DEFAULTS.get(code, {}))
    if not values:
        values = {
            "theme_name": "未分类主题（待核验）",
            "event_keywords": ("基金公告", "基金经理变更", "定期报告", "重大资产事件"),
            "official_domains": ("sse.com.cn", "szse.cn", "cninfo.com.cn"),
            "b_level_domains": ("eastmoney.com", "10jqka.com.cn", "1234567.com.cn"),
        }
    identity = identity or {}
    source_url = identity.get("source_url")
    host = (urlparse(str(source_url)).hostname or "").lower() if source_url else ""
    official = tuple(values.get("official_domains", ()))
    if host and host not in official:
        official = (*official, host)
    return FundAnalysisProfile(fund_code=code, official_domains=official, **{
        key: value for key, value in values.items() if key != "official_domains"
    })


def profile_payload(profile: FundAnalysisProfile) -> dict[str, object]:
    """Return a JSON-safe profile for reports and LLM explanation input."""
    return asdict(profile)
