import os
from dataclasses import dataclass, field
from typing import Any, Dict

import requests


DEFAULT_DOMESTIC_URLS = {
    "eastmoney_home": "https://www.eastmoney.com/",
    "eastmoney_sector_fund_flow": "https://data.eastmoney.com/bkzj/",
    "eastmoney_lhb": "https://data.eastmoney.com/stock/lhb.html",
    "eastmoney_announcements": "https://data.eastmoney.com/notices/",
    "ths_industry_flow": "https://data.10jqka.com.cn/funds/hyzjl/",
    "ths_lhb": "https://data.10jqka.com.cn/market/longhu/",
    "ths_announcements": "https://data.10jqka.com.cn/market/ggsd/",
    "fund_020671": "https://fundf10.eastmoney.com/020671.html",
    "fund_020671_holdings": "https://fundf10.eastmoney.com/ccmx_020671.html",
    "fund_025500": "https://fundf10.eastmoney.com/025500.html",
    "fund_025500_holdings": "https://fundf10.eastmoney.com/ccmx_025500.html",
    "cninfo": "https://www.cninfo.com.cn/",
}


@dataclass
class DomesticWebResult:
    raw_text: Dict[str, str] = field(default_factory=dict)
    source_status: Dict[str, str] = field(default_factory=dict)


class DomesticWebProvider:
    """国内公开网页 + 可选 Firecrawl raw_text 采集器。

    当前只采集原始文本供调试和后续解析使用；失败不会中断报告流程。
    """

    def __init__(self, timeout: int = 8):
        self.timeout = timeout
        self.firecrawl_api_key = os.getenv("FIRECRAWL_API_KEY")
        self.firecrawl_api_url = os.getenv("FIRECRAWL_API_URL", "https://api.firecrawl.dev")

    def fetch_raw_pages(self, urls: Dict[str, str] | None = None, use_firecrawl: bool = False) -> DomesticWebResult:
        urls = urls or DEFAULT_DOMESTIC_URLS
        result = DomesticWebResult()
        for name, url in urls.items():
            text = self._fetch_with_firecrawl(url) if use_firecrawl else self._fetch_with_requests(url)
            if text:
                result.raw_text[name] = text[:6000]
                result.source_status[name] = "success"
            else:
                result.raw_text[name] = ""
                result.source_status[name] = "failed"
        return result

    def fetch_sector_fund_pages(self, config: Dict[str, Any], use_firecrawl: bool = False) -> DomesticWebResult:
        return self.fetch_raw_pages(build_sector_fund_urls(config), use_firecrawl=use_firecrawl)

    def _fetch_with_requests(self, url: str) -> str:
        try:
            response = requests.get(
                url,
                timeout=self.timeout,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                },
            )
            response.raise_for_status()
            response.encoding = response.apparent_encoding or response.encoding
            return response.text
        except Exception:
            return ""

    def _fetch_with_firecrawl(self, url: str) -> str:
        if not self.firecrawl_api_key:
            return ""
        try:
            endpoint = self.firecrawl_api_url.rstrip("/") + "/v1/scrape"
            response = requests.post(
                endpoint,
                timeout=self.timeout,
                headers={
                    "Authorization": f"Bearer {self.firecrawl_api_key}",
                    "Content-Type": "application/json",
                },
                json={"url": url, "formats": ["markdown"]},
            )
            response.raise_for_status()
            payload = response.json()
            data = payload.get("data", payload)
            return data.get("markdown") or data.get("content") or ""
        except Exception:
            return ""


def merge_raw_text_status(context, result: DomesticWebResult):
    context.raw_text.update(result.raw_text)
    context.source_status.update(result.source_status)
    return context


def _market_prefix(code: str) -> str:
    if code.startswith(("5", "6", "9")):
        return "sh"
    return "sz"


def build_sector_fund_urls(config: Dict[str, Any]) -> Dict[str, str]:
    urls = dict(DEFAULT_DOMESTIC_URLS)

    for etf in config.get("etfs", []):
        code = etf.get("code")
        if not code:
            continue
        prefix = _market_prefix(code)
        urls[f"etf_eastmoney_{code}"] = f"https://quote.eastmoney.com/{prefix}{code}.html"
        urls[f"etf_fund_{code}"] = f"https://fundf10.eastmoney.com/{code}.html"
        urls[f"etf_10jqka_{code}"] = f"https://stockpage.10jqka.com.cn/{code}/"

    for rows in config.get("watch_stocks", {}).values():
        for stock in rows:
            code = stock.get("code")
            if not code:
                continue
            prefix = _market_prefix(code)
            urls[f"stock_eastmoney_{code}"] = f"https://quote.eastmoney.com/{prefix}{code}.html"
            urls[f"stock_10jqka_{code}"] = f"https://stockpage.10jqka.com.cn/{code}/"

    return urls
