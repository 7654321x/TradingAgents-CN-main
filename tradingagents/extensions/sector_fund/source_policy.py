"""Field-level source, validation, and cache policy for fund analysis."""
from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class FieldSourcePolicy:
    """A data field's permitted acquisition and validation path.

    ``discovery`` may use a search engine, but only the source domains listed
    here may contribute values.  A lower-quality fallback never overwrites a
    stored higher-quality value without an explicit conflict record.
    """

    dataset_type: str
    primary_level: str
    primary_domains: tuple[str, ...]
    fallback_level: str | None = None
    fallback_domains: tuple[str, ...] = ()
    verification_domains: tuple[str, ...] = ()
    acquisition_chain: tuple[str, ...] = ("verified_cache", "official_or_platform_webpage")
    freshness: str = "on_demand"
    cache_rule: str = "raw_source_document_and_normalized_value"
    missing_rule: str = "mark_missing_and_reduce_confidence"

    @property
    def allowed_domains(self) -> tuple[str, ...]:
        return (*self.primary_domains, *self.fallback_domains, *self.verification_domains)


SECTOR_FUND_SOURCE_POLICIES: dict[str, FieldSourcePolicy] = {
    "fund_identity": FieldSourcePolicy(
        "fund_identity", "A", ("efunds.com.cn",), verification_domains=("sse.com.cn", "szse.cn"),
    ),
    "official_nav": FieldSourcePolicy(
        "official_nav", "A", ("efunds.com.cn",), "B", ("eastmoney.com", "1234567.com.cn"),
        freshness="official_publish_time",
    ),
    "index_constituents": FieldSourcePolicy(
        "index_constituents", "A", ("csindex.com.cn",), freshness="index_rebalance_or_publication",
    ),
    "current_daily_market": FieldSourcePolicy(
        "current_daily_market", "B", ("eastmoney.com",), "B", ("10jqka.com.cn",),
        verification_domains=("sse.com.cn", "szse.cn"), freshness="user_requested_current_session",
        acquisition_chain=(
            "verified_mcp_cache",
            "firecrawl_backend_primary_page",
            "firecrawl_backend_fresh_retry",
            "firecrawl_backend_fallback_page",
            "chrome_manual_diagnostic_only_with_user_authorization",
        ),
        cache_rule="isolated_mcp_raw_document_only; never_write_market_bar_observation",
        missing_rule="retry_primary_then_fallback_page; record_failure; do_not_substitute_history_or_estimate",
    ),
    "etf_status": FieldSourcePolicy(
        "etf_status", "A", ("sse.com.cn", "szse.cn"), "B", ("eastmoney.com",),
        freshness="post_close_or_official_publication",
    ),
    "company_event": FieldSourcePolicy(
        "company_event", "A", ("cninfo.com.cn", "sse.com.cn", "szse.cn"), "C",
        ("stcn.com", "yicai.com", "caixin.com", "reuters.com"), freshness="recent_7d",
        cache_rule="raw_document_hash_and_entity_deduplication",
        missing_rule="C_level_is_lead_only; do_not_score_without_confirmation",
    ),
    "industry_cycle": FieldSourcePolicy(
        "industry_cycle", "A", ("stats.gov.cn", "customs.gov.cn", "miit.gov.cn"), "B",
        ("eastmoney.com", "10jqka.com.cn"), verification_domains=("wsts.org", "semiconductors.org"),
        acquisition_chain=(
            "verified_cache",
            "official_original_page",
            "akshare_historical_proxy",
            "firecrawl_search_and_original_page",
            "manual_diagnostic_only_with_user_authorization",
        ),
        freshness="publication_date",
        missing_rule="store_raw_mcp_document_then_mark_missing_until_structurally_verified",
    ),
}


def source_policy_for(dataset_type: str) -> FieldSourcePolicy:
    try:
        return SECTOR_FUND_SOURCE_POLICIES[dataset_type]
    except KeyError as exc:
        raise ValueError(f"no source policy registered for {dataset_type!r}") from exc


def source_policy_summary() -> dict[str, dict[str, object]]:
    """Safe, static policy summary suitable for reports and LLM input."""
    return {key: asdict(policy) for key, policy in SECTOR_FUND_SOURCE_POLICIES.items()}
