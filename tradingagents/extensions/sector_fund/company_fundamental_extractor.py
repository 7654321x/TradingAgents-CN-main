"""Strict financial-fact extraction from traceable company source documents."""
from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any

_DATE_PATTERN = re.compile(r"(20\d{2})[年\-/](\d{1,2})[月\-/](\d{1,2})")
_PERIOD_PATTERN = re.compile(r"(20\d{2}年(?:[一二三四1-4]季度|半年度|上半年|全年|1[—-]?[0-2]?\d?月))")
_REVENUE_PATTERN = re.compile(r"(?:实现)?营业(?:总)?收入[^。；，]{0,80}?([0-9][0-9,]*(?:\.\d+)?)\s*(万亿元|亿元|万元)")
_NET_PROFIT_PATTERN = re.compile(
    r"(?:归属于上市公司股东的|归母)?净利润[^。；，]{0,80}?([0-9][0-9,]*(?:\.\d+)?)\s*(万亿元|亿元|万元)"
)
_GROSS_MARGIN_PATTERN = re.compile(r"(?:销售)?毛利率[^。；，]{0,40}?([0-9]+(?:\.\d+)?)\s*%")


@dataclass(frozen=True)
class CompanyFundamentalFact:
    metric_name: str
    value: float
    unit: str
    report_period: str
    published_date: str
    source_url: str
    source_level: str
    evidence: str
    extractor_version: str = "company_fundamental_extractor_v1"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _date(value: str) -> str | None:
    match = _DATE_PATTERN.search(value)
    if not match:
        return None
    return f"{match.group(1)}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"


def _published_date(metadata: Mapping[str, Any], markdown: str) -> str | None:
    for key in ("publishedTime", "publishedDate", "date", "article:published_time"):
        if (value := metadata.get(key)) and (parsed := _date(str(value))):
            return parsed
    for line in markdown.splitlines()[:30]:
        if any(token in line for token in ("发布时间", "发布日期", "披露日期", "公告日期")) and (parsed := _date(line)):
            return parsed
    return None


def extract_company_fundamental_facts(
    *, source_url: str, source_level: str, payload: Mapping[str, Any]
) -> tuple[CompanyFundamentalFact, ...]:
    """Return only facts with a published date, report period, and evidence."""
    if source_level not in {"A", "B"}:
        return ()
    document = payload.get("source_document")
    if not isinstance(document, Mapping):
        return ()
    markdown, metadata = document.get("markdown"), document.get("metadata")
    if not isinstance(markdown, str) or not isinstance(metadata, Mapping):
        return ()
    published_date = _published_date(metadata, markdown)
    period_match = _PERIOD_PATTERN.search(markdown)
    if published_date is None or period_match is None:
        return ()
    period = period_match.group(1)
    facts: list[CompanyFundamentalFact] = []

    def add(metric_name: str, raw_value: str, unit: str, start: int, end: int) -> None:
        try:
            value = float(raw_value.replace(",", ""))
        except ValueError:
            return
        facts.append(
            CompanyFundamentalFact(
                metric_name=metric_name,
                value=value,
                unit=unit,
                report_period=period,
                published_date=published_date,
                source_url=source_url,
                source_level=source_level,
                evidence=markdown[max(0, start - 100):min(len(markdown), end + 100)].strip(),
            )
        )

    for match in _REVENUE_PATTERN.finditer(markdown):
        add("revenue", *match.groups(), match.start(), match.end())
    for match in _NET_PROFIT_PATTERN.finditer(markdown):
        add("net_profit", *match.groups(), match.start(), match.end())
    for match in _GROSS_MARGIN_PATTERN.finditer(markdown):
        add("gross_margin_pct", match.group(1), "%", match.start(), match.end())
    unique: dict[str, CompanyFundamentalFact] = {}
    for fact in facts:
        unique.setdefault(fact.metric_name, fact)
    return tuple(unique.values())
