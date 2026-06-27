"""兼容现有 dataflows.providers 目录的国内网页数据适配器入口。"""

from tradingagents.sector_fund.domestic_web_provider import (
    DEFAULT_DOMESTIC_URLS,
    DomesticWebProvider,
    DomesticWebResult,
)

__all__ = ["DEFAULT_DOMESTIC_URLS", "DomesticWebProvider", "DomesticWebResult"]

