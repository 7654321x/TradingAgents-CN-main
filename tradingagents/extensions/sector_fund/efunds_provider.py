"""Official E-Funds fund identity provider for the sector-fund extension."""
from __future__ import annotations

import html
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser

import requests


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._blocked = 0

    def handle_starttag(self, tag, attrs):
        if tag.lower() in {"script", "style", "noscript"}:
            self._blocked += 1

    def handle_endtag(self, tag):
        if tag.lower() in {"script", "style", "noscript"} and self._blocked:
            self._blocked -= 1

    def handle_data(self, data):
        if not self._blocked:
            self.parts.append(data)


@dataclass(frozen=True)
class EFundsIdentity:
    fund_code: str
    fund_name: str | None
    fund_type: str | None
    manager_name: str | None
    fund_size: float | None
    fund_size_as_of: str | None
    nav_date: str | None
    benchmark_index_name: str | None
    benchmark_index_code: str | None
    target_etf_code: str | None
    target_etf_ratio_min_pct: float | None
    source_url: str
    fetched_at: str
    purchase_fee_description: str | None = None
    redemption_fee_description: str | None = None
    management_fee_pct: float | None = None
    custody_fee_pct: float | None = None
    sales_service_fee_pct: float | None = None
    source: str = "efunds_official_v2"
    is_official: bool = True

    def to_dict(self) -> dict[str, object]:
        return self.__dict__.copy()


@dataclass(frozen=True)
class EFundsNavObservation:
    fund_code: str
    nav_date: str
    unit_nav: float
    cumulative_nav: float
    daily_change_pct: float | None
    source_url: str
    fetched_at: str
    source: str = "efunds_official"
    status: str = "SUCCESS"

    def to_dict(self) -> dict[str, object]:
        return self.__dict__.copy()


def _clean_text(body: str) -> str:
    parser = _TextParser()
    parser.feed(body)
    return re.sub(r"\s+", " ", html.unescape(" ".join(parser.parts))).strip()


def _capture(text: str, pattern: str) -> str | None:
    match = re.search(pattern, text)
    return match.group(1).strip() if match else None


def fetch_efunds_identity(fund_code: str, *, timeout: float = 20.0) -> EFundsIdentity:
    code = str(fund_code).strip()
    if not re.fullmatch(r"\d{6}", code):
        raise ValueError(f"invalid fund code: {fund_code}")
    url = f"https://www.efunds.com.cn/fund/{code}.shtml"
    response = requests.get(url, headers={"User-Agent": "TradingAgents/1.0"}, timeout=timeout)
    response.raise_for_status()
    response.encoding = "utf-8"
    text = _clean_text(response.text)
    if not re.search(rf"基金代码[：:]\s*{re.escape(code)}", text):
        raise ValueError(f"official page did not confirm fund code {code}")
    size_match = re.search(r"基金规模[：:]\s*数据截至(\d{4}-\d{2}-\d{2})[：:]?([\d,]+(?:\.\d+)?)元", text)
    ratio_match = re.search(r"投资于目标ETF的资产不低于基金资产净值的\s*(\d+(?:\.\d+)?)%", text)
    target_match = re.search(
        r"(\d{6})\s+易方达上证科创板芯片交易型开放式指数证券投资基金",
        text,
    )
    management_fee = re.search(r"管理费\s+(\d+(?:\.\d+)?)%", text)
    custody_fee = re.search(r"托管费\s+(\d+(?:\.\d+)?)%", text)
    sales_fee = re.search(r"销售服务费\s+(\d+(?:\.\d+)?)%", text)
    purchase_fee = "本基金不收取申购费" if "本基金不收取申购费" in text else None
    redemption_match = re.search(
        r"赎回费率\s+持有时间（天）\s+赎回费率\s+(.*?)\s+管理费、托管费、销售服务费",
        text,
    )
    return EFundsIdentity(
        fund_code=code,
        fund_name=_capture(text, r"基金名称[：:]\s*(.*?)\s+基金简称[：:]"),
        fund_type=_capture(text, r"基金类型[：:]\s*(.*?)\s+成立日期[：:]"),
        manager_name=_capture(text, r"基金经理[：:]\s*(.*?)\s+基金托管人[：:]"),
        fund_size=float(size_match.group(2).replace(",", "")) if size_match else None,
        fund_size_as_of=size_match.group(1) if size_match else None,
        nav_date=_capture(text, r"基金净值日期[：:]\s*(\d{4}-\d{2}-\d{2})"),
        benchmark_index_name=_capture(text, r"标的指数名称[：:]\s*(.*?)\s+投资比例[：:]"),
        # The official CSI factsheet/methodology identifies 上证科创板芯片指数 as 000685.
        # E-Funds' fund page exposes the name but not the code; this mapping is only
        # used for the verified 020671 identity and is not inferred from ticker data.
        benchmark_index_code="000685" if code == "020671" else None,
        target_etf_code=target_match.group(1) if target_match else None,
        target_etf_ratio_min_pct=float(ratio_match.group(1)) if ratio_match else None,
        source_url=url,
        fetched_at=datetime.now(timezone.utc).isoformat(),
        purchase_fee_description=purchase_fee,
        redemption_fee_description=redemption_match.group(1).strip() if redemption_match else None,
        management_fee_pct=float(management_fee.group(1)) if management_fee else None,
        custody_fee_pct=float(custody_fee.group(1)) if custody_fee else None,
        sales_service_fee_pct=float(sales_fee.group(1)) if sales_fee else None,
    )


def fetch_efunds_nav_history(
    fund_code: str, *, timeout: float = 20.0, max_rows: int = 250
) -> tuple[EFundsNavObservation, ...]:
    """Parse the official page's disclosed NAV table, newest rows first."""
    code = str(fund_code).strip()
    if not re.fullmatch(r"\d{6}", code):
        raise ValueError(f"invalid fund code: {fund_code}")
    url = f"https://www.efunds.com.cn/fund/{code}.shtml"
    response = requests.get(url, headers={"User-Agent": "TradingAgents/1.0"}, timeout=timeout)
    response.raise_for_status()
    response.encoding = "utf-8"
    text = _clean_text(response.text)
    if not re.search(rf"基金代码[：:]\s*{re.escape(code)}", text):
        raise ValueError(f"official page did not confirm fund code {code}")
    pattern = re.compile(
        r"(?P<nav_date>\d{4}-\d{2}-\d{2})\s+"
        r"(?P<unit_nav>\d+(?:\.\d+)?)\s+"
        r"(?P<change>[+-]?\d+(?:\.\d+)?%)\s+"
        r"(?P<cumulative_nav>\d+(?:\.\d+)?)"
    )
    seen: set[str] = set()
    rows: list[EFundsNavObservation] = []
    fetched_at = datetime.now(timezone.utc).isoformat()
    history_url = f"https://cdn.efunds.com.cn/market/2.0/{code}_1y.js"
    history_text = ""
    try:
        history_response = requests.get(
            history_url, headers={"User-Agent": "TradingAgents/1.0"}, timeout=timeout
        )
        history_response.raise_for_status()
        history_response.encoding = "utf-8"
        history_text = history_response.text
    except Exception:
        history_text = ""
    # The official JS feed has: date_accumulated_change_unit_nav_cumulative_nav_daily_change.
    js_match = re.search(rf"mk_{re.escape(code)}_1y=\"([^\"]+)\"", history_text)
    js_rows = []
    if js_match:
        for item in js_match.group(1).split(";")[1:]:
            parts = item.split("_")
            if len(parts) != 5 or not re.fullmatch(r"\d{8}", parts[0]):
                continue
            js_rows.append(
                (
                    f"{parts[0][:4]}-{parts[0][4:6]}-{parts[0][6:]}",
                    float(parts[2]),
                    float(parts[3]),
                    float(parts[4]),
                )
            )
    source_url = history_url if js_rows else url
    iterable = (
        [(date, unit, cumulative, change) for date, unit, cumulative, change in js_rows]
        if js_rows
        else [
            (m.group("nav_date"), float(m.group("unit_nav")), float(m.group("cumulative_nav")), float(m.group("change").rstrip("%")))
            for m in pattern.finditer(text)
        ]
    )
    for nav_date, unit_nav, cumulative_nav, daily_change in iterable:
        if nav_date in seen:
            continue
        seen.add(nav_date)
        rows.append(
            EFundsNavObservation(
                fund_code=code,
                nav_date=nav_date,
                unit_nav=unit_nav,
                cumulative_nav=cumulative_nav,
                daily_change_pct=daily_change,
                source_url=source_url,
                fetched_at=fetched_at,
            )
        )
        if len(rows) >= max_rows:
            break
    if not rows:
        raise ValueError(f"official page contains no NAV rows for {code}")
    return tuple(sorted(rows, key=lambda row: row.nav_date, reverse=True))
