SCHEMA_TABLES = (
    "portfolio",
    "fund_config",
    "fund_nav_daily",
    "fund_intraday_estimate",
    "fund_holding_snapshot",
    "security_master",
    "security_kline_daily",
    "security_indicator_daily",
    "sector_snapshot",
    "market_snapshot",
    "lhb_event",
    "announcement_event",
    "intraday_snapshot",
    "agent_analysis_result",
    "estimate_error",
    "data_source_run",
    "field_source",
)


VALID_FUND_TYPES = {
    "etf_feeder",
    "index_fund",
    "active_equity",
    "sector_theme",
    "qdii",
    "bond_fund",
    "money_fund",
    "balanced",
    "core",
    "offensive",
    "satellite",
}


DECISION_TIMES = {"1000", "1445", "night"}
