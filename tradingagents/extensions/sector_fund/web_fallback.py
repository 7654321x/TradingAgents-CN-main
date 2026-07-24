"""Controlled MCP/web fallback contract.

The application never treats a search snippet as data.  An orchestration host
may inject resolved source documents from MCP; this module admits only the
allowed source levels and requires a canonical URL plus extracted payload.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlparse

import pandas as pd

from .akshare_market_provider import validate_raw_daily_frame


class WebResolver(Protocol):
    def resolve(self, query: str, allowed_domains: tuple[str, ...]) -> list[dict[str, Any]]: ...


@dataclass(frozen=True)
class WebFallbackResult:
    status: str
    source_level: str | None = None
    source_url: str | None = None
    payload: dict[str, Any] | None = None
    reason: str | None = None


def _url_matches_allowed_domain(source_url: str, allowed_domains: tuple[str, ...]) -> bool:
    host = (urlparse(source_url).hostname or "").lower()
    return any(host == domain.lower() or host.endswith("." + domain.lower()) for domain in allowed_domains)


def resolve_structured_fallback(resolver: WebResolver | None, *, query: str, allowed_domains: tuple[str, ...], allow_b_level: bool = True) -> WebFallbackResult:
    if resolver is None:
        return WebFallbackResult("MCP_REQUIRED", reason="No MCP resolver was injected by the host")
    for item in resolver.resolve(query, allowed_domains):
        level = str(item.get("source_level", ""))
        if level not in ({"A", "B"} if allow_b_level else {"A"}):
            continue
        source_url = item.get("source_url")
        if not source_url or not _url_matches_allowed_domain(str(source_url), allowed_domains) or not isinstance(item.get("payload"), dict):
            continue
        return WebFallbackResult("SUCCESS", level, source_url, item["payload"])
    return WebFallbackResult(
        "UNAVAILABLE_FROM_ALLOWED_WEB_SOURCES",
        reason=getattr(resolver, "last_error", None) or "No structured A/B source document",
    )


def resolve_current_daily_bar(
    resolver: WebResolver | None, *, symbol: str, analysis_date: str, allowed_domains: tuple[str, ...],
    require_close_confirmation: bool = False,
) -> WebFallbackResult:
    """Read one current-day bar from an injected MCP result without persistence.

    The resolver must supply an extracted original-page payload.  Search-result
    snippets are intentionally not accepted.  The caller stores the raw
    document in ``mcp_web_observation``; it is never written as an AKShare
    market bar.
    """
    resolved = resolve_structured_fallback(
        resolver,
        query=f"{symbol} {analysis_date} 日线 开盘 最高 最低 收盘 成交量 成交额",
        allowed_domains=allowed_domains,
    )
    if resolved.status != "SUCCESS" or not resolved.payload:
        return resolved
    payload = resolved.payload
    quote_timestamp = str(payload.get("quote_timestamp") or "")
    if quote_timestamp and not quote_timestamp.startswith(analysis_date):
        return WebFallbackResult(
            "SOURCE_DATE_MISMATCH", resolved.source_level, resolved.source_url, payload,
            f"source quote timestamp {quote_timestamp!r} does not match {analysis_date}",
        )
    if require_close_confirmation and str(payload.get("trading_status") or "").upper() not in {"闭市", "收盘", "CLOSED", "CLOSE"}:
        return WebFallbackResult(
            "CLOSE_CONFIRMATION_REQUIRED", resolved.source_level, resolved.source_url, payload,
            "current-day close requires a source trading-status confirmation",
        )
    candidate = payload.get("bar", payload)
    try:
        frame = pd.DataFrame([candidate])
        if "Date" not in frame.columns:
            frame["Date"] = analysis_date
        frame["Date"] = pd.to_datetime(frame["Date"], errors="coerce")
        if frame["Date"].isna().any() or frame["Date"].iloc[0].date().isoformat() != analysis_date:
            raise ValueError("payload Date does not match requested analysis date")
        frame = frame.set_index("Date")
        for column in ("Open", "High", "Low", "Close", "Volume", "Amount"):
            if column in frame.columns:
                frame[column] = pd.to_numeric(frame[column], errors="coerce")
        validated = validate_raw_daily_frame(frame)
        if "Amount" in frame.columns and frame["Amount"].isna().any():
            raise ValueError("payload Amount is null")
    except Exception as exc:
        return WebFallbackResult(
            "INVALID_STRUCTURED_WEB_BAR", resolved.source_level, resolved.source_url,
            payload, f"{type(exc).__name__}: {exc}",
        )
    payload = {**payload, "bar": validated.reset_index().assign(Date=lambda data: data["Date"].dt.strftime("%Y-%m-%d")).iloc[0].to_dict()}
    return WebFallbackResult("SUCCESS", resolved.source_level, resolved.source_url, payload)


def current_bar_frame(result: WebFallbackResult) -> pd.DataFrame:
    """Convert an already-validated MCP response to an in-memory daily frame."""
    if result.status != "SUCCESS" or not result.payload:
        return pd.DataFrame()
    frame = pd.DataFrame([result.payload["bar"]])
    frame["Date"] = pd.to_datetime(frame["Date"])
    return frame.set_index("Date").sort_index()
