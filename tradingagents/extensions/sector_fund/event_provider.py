"""Official E-Funds announcement discovery for explicit incremental sync."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, time, timezone
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


@dataclass(frozen=True)
class FundEventRecord:
    fund_code: str
    event_date: str
    available_at: str
    title: str
    url: str
    source: str
    source_level: str
    event_type: str
    confirmation_status: str
    already_reflected_status: str
    content_hash: str
    dedup_key: str
    summary: str | None
    fetched_at: str

    def to_dict(self) -> dict[str, object]:
        return self.__dict__.copy()


def _event_type(title: str) -> str:
    if "季度报告" in title or "年度报告" in title or "中期报告" in title:
        return "PERIODIC_REPORT"
    if "招募说明书" in title:
        return "PROSPECTUS"
    if "产品资料概要" in title:
        return "PRODUCT_SUMMARY"
    if "基金合同" in title or "托管协议" in title:
        return "LEGAL_DOCUMENT"
    if "关联交易" in title:
        return "RELATED_TRANSACTION"
    return "OFFICIAL_ANNOUNCEMENT"


def fetch_efunds_events(
    fund_code: str,
    *,
    since_exclusive: str | None = None,
    timeout: float = 20.0,
) -> tuple[FundEventRecord, ...]:
    """Fetch the official listing once and return only rows newer than the cursor."""
    code = str(fund_code).strip()
    if not re.fullmatch(r"\d{6}", code):
        raise ValueError(f"invalid fund code: {fund_code}")
    page_url = f"https://www.efunds.com.cn/fund/{code}.shtml"
    response = requests.get(page_url, headers={"User-Agent": "TradingAgents/1.0"}, timeout=timeout)
    response.raise_for_status()
    response.encoding = "utf-8"
    soup = BeautifulSoup(response.text, "html.parser")
    fetched_at = datetime.now(timezone.utc).isoformat()
    output: list[FundEventRecord] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        title = " ".join(anchor.get_text(" ", strip=True).split())
        url = urljoin(page_url, anchor["href"])
        match = re.search(r"/bulletin/(\d{8})/", url)
        if not title or not match:
            continue
        raw_date = match.group(1)
        event_date = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:]}"
        if since_exclusive and event_date <= since_exclusive:
            continue
        # The page exposes a publication date but not a timestamp. End-of-day is
        # conservative for point-in-time analysis and avoids same-day lookahead.
        available_at = datetime.combine(
            datetime.fromisoformat(event_date).date(), time(23, 59, 59)
        ).isoformat()
        content_hash = hashlib.sha256(f"{title}\n{url}".encode()).hexdigest()
        dedup_key = hashlib.sha256(f"efunds_official\n{url}".encode()).hexdigest()
        if dedup_key in seen:
            continue
        seen.add(dedup_key)
        output.append(
            FundEventRecord(
                fund_code=code,
                event_date=event_date,
                available_at=available_at,
                title=title,
                url=url,
                source="efunds_official",
                source_level="OFFICIAL_FUND_MANAGER",
                event_type=_event_type(title),
                confirmation_status="CONFIRMED",
                already_reflected_status="UNKNOWN",
                content_hash=content_hash,
                dedup_key=dedup_key,
                summary=None,
                fetched_at=fetched_at,
            )
        )
    return tuple(sorted(output, key=lambda item: (item.event_date, item.title), reverse=True))
