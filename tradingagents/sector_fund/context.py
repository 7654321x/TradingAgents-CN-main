from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class MarketEnvironment:
    shanghai_change_pct: Optional[float] = None
    shenzhen_change_pct: Optional[float] = None
    chinext_change_pct: Optional[float] = None
    star50_change_pct: Optional[float] = None
    csi300_change_pct: Optional[float] = None
    total_turnover_billion: Optional[float] = None
    advancing_count: Optional[int] = None
    declining_count: Optional[int] = None
    limit_up_count: Optional[int] = None
    limit_down_count: Optional[int] = None


@dataclass
class SectorPerformance:
    name: str
    change_pct: Optional[float] = None
    turnover_billion: Optional[float] = None
    turnover_rate: Optional[float] = None
    advancing_count: Optional[int] = None
    declining_count: Optional[int] = None
    leading_stocks: List[str] = field(default_factory=list)
    lagging_stocks: List[str] = field(default_factory=list)
    change_3d_pct: Optional[float] = None
    change_5d_pct: Optional[float] = None
    change_10d_pct: Optional[float] = None


@dataclass
class FundFlow:
    semiconductor_main_inflow_billion: Optional[float] = None
    storage_main_inflow_billion: Optional[float] = None
    electronics_main_inflow_billion: Optional[float] = None
    chip_main_inflow_billion: Optional[float] = None
    top_inflow_rank: List[str] = field(default_factory=list)
    five_day_inflow_billion: Optional[float] = None
    ten_day_inflow_billion: Optional[float] = None
    super_large_order_inflow_billion: Optional[float] = None
    large_order_inflow_billion: Optional[float] = None
    largest_stock_inflow: Optional[str] = None
    largest_stock_outflow: Optional[str] = None


@dataclass
class StockObservation:
    code: str
    name: str
    theme: str
    change_pct: Optional[float] = None
    turnover_billion: Optional[float] = None
    turnover_rate: Optional[float] = None
    main_inflow_billion: Optional[float] = None
    open_price: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    close: Optional[float] = None
    previous_close: Optional[float] = None
    limit_up: bool = False
    limit_down: bool = False
    intraday_pullback: bool = False
    long_upper_shadow: bool = False
    below_ma5: bool = False
    below_ma10: bool = False
    on_lhb: bool = False


@dataclass
class FundHolding:
    code: str
    name: str
    unit_nav: Optional[float] = None
    daily_change_pct: Optional[float] = None
    week_change_pct: Optional[float] = None
    month_change_pct: Optional[float] = None
    three_month_change_pct: Optional[float] = None
    ytd_change_pct: Optional[float] = None
    top_holdings: List[str] = field(default_factory=list)
    top_holdings_weight_pct: Optional[float] = None
    industry_allocation: Dict[str, float] = field(default_factory=dict)
    size_billion: Optional[float] = None
    manager: Optional[str] = None
    role: str = ""
    position_role: str = ""


@dataclass
class EtfObservation:
    code: str
    name: str
    latest_price: Optional[float] = None
    change_pct: Optional[float] = None
    turnover_billion: Optional[float] = None
    turnover_rate: Optional[float] = None
    premium_rate_pct: Optional[float] = None
    five_day_change_pct: Optional[float] = None
    ma5: Optional[float] = None
    ma10: Optional[float] = None
    ma20: Optional[float] = None
    pullback_ma5: bool = False
    pullback_ma10: bool = False
    below_ma10: bool = False
    below_ma20: bool = False


@dataclass
class Announcement:
    title: str
    date: str
    stock_code: str = ""
    stock_name: str = ""
    announcement_type: str = ""
    earnings_up: bool = False
    earnings_down: bool = False
    shareholder_reduce: bool = False
    private_placement: bool = False
    major_order: bool = False
    risk_warning: bool = False
    summary: str = ""
    impact_direction: str = "中性"
    impact_strength: int = 3


@dataclass
class SectorFundContext:
    analysis_date: str
    profile: Dict[str, Any]
    config: Dict[str, Any]
    market: MarketEnvironment
    sectors: List[SectorPerformance]
    fund_flow: FundFlow
    stocks: List[StockObservation]
    funds: List[FundHolding]
    etfs: List[EtfObservation]
    announcements: List[Announcement]
    raw_text: Dict[str, str] = field(default_factory=dict)
    source_status: Dict[str, str] = field(default_factory=dict)
    field_sources: Dict[str, str] = field(default_factory=dict)
    data_quality: Dict[str, Any] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
