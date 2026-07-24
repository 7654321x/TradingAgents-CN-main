"""Strict extraction of dated industry-cycle facts from original web pages."""
from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import urlparse

_DATE_PATTERN = re.compile(r"(20\d{2})[年\-/](\d{1,2})[月\-/](\d{1,2})")
_PERIOD_PATTERN = re.compile(r"(20\d{2}年(?:1[—-]?[0-2]?\d?月|[一二三四1-4]季度|全年|上半年))")
_IC_OUTPUT_PATTERN = re.compile(
    r"集成电路(?:产量|产品产量)[^。；，]{0,80}?([0-9][0-9,]*(?:\.\d+)?)\s*(亿块|万块|块)"
)
_IC_TRADE_PATTERN = re.compile(
    r"(出口|进口)集成电路[^。；，]{0,80}?([0-9][0-9,]*(?:\.\d+)?)\s*(亿个|万个|个)"
)
_ELECTRONIC_VALUE_ADDED_PATTERN = re.compile(
    r"规模以上电子信息制造业增加值同比增长\s*([0-9]+(?:\.\d+)?)\s*%"
)
_ELECTRONIC_REVENUE_PATTERN = re.compile(
    r"电子信息制造业(?:累计)?实现营业收入\s*([0-9][0-9,]*(?:\.\d+)?)\s*(万亿元|亿元)"
)


@dataclass(frozen=True)
class IndustryCycleFact:
    metric_name: str
    value: float
    unit: str
    period: str
    published_date: str
    source_url: str
    source_level: str
    evidence: str
    extractor_version: str = "industry_cycle_extractor_v1"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _date(value: str) -> str | None:
    match = _DATE_PATTERN.search(value)
    if not match:
        return None
    return f"{match.group(1)}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"


def _published_date(metadata: Mapping[str, Any], markdown: str) -> str | None:
    for key in ("publishedTime", "publishedDate", "date", "article:published_time"):
        value = metadata.get(key)
        if value and (parsed := _date(str(value))):
            return parsed
    # Prefer an explicit publication line over incidental historical dates in
    # the body.  A page without a reliable publication date stays unscored.
    for line in markdown.splitlines()[:30]:
        if any(token in line for token in ("发布时间", "发布日期", "发布于")) and (parsed := _date(line)):
            return parsed
    return None


def _period(markdown: str) -> str | None:
    match = _PERIOD_PATTERN.search(markdown)
    return match.group(1) if match else None


def extract_industry_cycle_facts(
    *, source_url: str, source_level: str, payload: Mapping[str, Any]
) -> tuple[IndustryCycleFact, ...]:
    """Extract only fully dated, source-backed metrics from one raw document.

    This adapter intentionally supports a small official metric set.  It is
    safer to return no facts than to reinterpret a percentage, an estimate, or
    an undated article sentence as a current cycle observation.
    """
    if source_level not in {"A", "B"}:
        return ()
    host = (urlparse(source_url).hostname or "").lower()
    if not host:
        return ()
    document = payload.get("source_document")
    if not isinstance(document, Mapping):
        return ()
    markdown = document.get("markdown")
    metadata = document.get("metadata")
    if not isinstance(markdown, str) or not isinstance(metadata, Mapping):
        return ()
    published_date = _published_date(metadata, markdown)
    period = _period(markdown)
    if published_date is None or period is None:
        return ()
    facts: list[IndustryCycleFact] = []

    def add_fact(metric_name: str, raw_value: str, unit: str, start: int, end: int) -> None:
        try:
            value = float(raw_value.replace(",", ""))
        except ValueError:
            return
        excerpt_start = max(0, start - 100)
        excerpt_end = min(len(markdown), end + 100)
        facts.append(
            IndustryCycleFact(
                metric_name=metric_name,
                value=value,
                unit=unit,
                period=period,
                published_date=published_date,
                source_url=source_url,
                source_level=source_level,
                evidence=markdown[excerpt_start:excerpt_end].strip(),
            )
        )
    for match in _IC_OUTPUT_PATTERN.finditer(markdown):
        add_fact("integrated_circuit_output", *match.groups(), match.start(), match.end())
    for match in _IC_TRADE_PATTERN.finditer(markdown):
        direction, raw_value, unit = match.groups()
        add_fact(
            "integrated_circuit_exports" if direction == "出口" else "integrated_circuit_imports",
            raw_value,
            unit,
            match.start(),
            match.end(),
        )
    for match in _ELECTRONIC_VALUE_ADDED_PATTERN.finditer(markdown):
        add_fact("electronic_information_value_added_yoy", match.group(1), "%", match.start(), match.end())
    for match in _ELECTRONIC_REVENUE_PATTERN.finditer(markdown):
        add_fact("electronic_information_revenue", *match.groups(), match.start(), match.end())
    # One page may repeat a fact in a table and prose.  Preserve one occurrence
    # of each metric; the raw MCP document retains the complete evidence.
    unique: dict[str, IndustryCycleFact] = {}
    for fact in facts:
        unique.setdefault(fact.metric_name, fact)
    return tuple(unique.values())
