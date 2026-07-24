"""Firecrawl-backed current A-share quote resolver.

The resolver is intentionally narrow: it retrieves a fresh original
Eastmoney quote page for a requested Shanghai/Shenzhen security, validates a
complete OHLCV bar, and returns the raw evidence for the isolated MCP table.
It never writes to the historical AKShare market-bar store.
"""
from __future__ import annotations

import os
import re
import time
from typing import Any

import requests

FIRECRAWL_SCRAPE_URL = "https://api.firecrawl.dev/v2/scrape"
_SYMBOL_PATTERN = re.compile(r"\b(\d{6})\.(SS|SZ)\b", re.IGNORECASE)
# A source may write the same state in a few different ways.  Keep this
# deliberately small and explicit: a price or percentage is never a status.
_CLOSE_STATUSES = {"闭市", "已收盘", "收盘", "交易结束", "CLOSED", "CLOSE"}
_QUOTE_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "quote_date_or_timestamp": {"type": "string"},
        "open": {"type": "number"},
        "high": {"type": "number"},
        "low": {"type": "number"},
        "close_or_latest_price": {"type": "number"},
        "previous_close": {"type": "number"},
        "volume": {"type": "number"},
        "amount": {"type": "number"},
        "volume_raw": {"type": "string"},
        "amount_raw": {"type": "string"},
        "trading_status": {"type": "string"},
    },
}


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        value = value.strip().replace(",", "")
        if not value or value.lower() == "null":
            return None
        multiplier = 1.0
        if value.endswith("亿"):
            value, multiplier = value[:-1], 100_000_000.0
        elif value.endswith("万"):
            value, multiplier = value[:-1], 10_000.0
        try:
            return float(value) * multiplier
        except ValueError:
            return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _symbol_from_query(query: str) -> tuple[str, str] | None:
    match = _SYMBOL_PATTERN.search(query)
    return (match.group(1), match.group(2).upper()) if match else None


def _raw_or_number(structured: dict[str, Any], raw_key: str, numeric_key: str) -> float | None:
    """Prefer a source string because it retains Chinese quantity units."""
    raw = structured.get(raw_key)
    return _number(raw) if raw not in {None, ""} else _number(structured.get(numeric_key))


def _amount_is_consistent(*, close: float, volume: float, amount: float) -> bool:
    """Validate A-share quote units through its implied average price.

    Public A-share quote pages report volume in lots (100 shares).  A missing
    ``亿``/``万`` suffix otherwise changes the implied price by orders of
    magnitude while still passing a basic non-negative check.
    """
    if volume == 0:
        return amount == 0
    implied_price = amount / (volume * 100.0)
    return close * 0.15 <= implied_price <= close * 6.0


class FirecrawlEastmoneyResolver:
    """Resolve current quote pages through Firecrawl with controlled retries.

    The primary page is retried with a fresh-cache request.  If it remains
    incomplete, the resolver tries Eastmoney's unified quote page.  Every
    rejected attempt is retained in the successful payload or exposed through
    ``last_error`` for the MCP audit record.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        api_url: str | None = None,
        session: requests.Session | None = None,
        retries_per_url: int = 2,
    ):
        self.api_key = api_key or os.getenv("FIRECRAWL_API_KEY")
        self.api_url = api_url or os.getenv("FIRECRAWL_API_URL") or FIRECRAWL_SCRAPE_URL
        self.session = session or requests.Session()
        self.retries_per_url = max(1, retries_per_url)
        self.last_error: str | None = None

    @staticmethod
    def _urls(code: str, exchange: str) -> tuple[str, ...]:
        market_prefix, market_id = ("sh", "1") if exchange == "SS" else ("sz", "0")
        return (
            f"https://quote.eastmoney.com/{market_prefix}{code}.html",
            f"https://quote.eastmoney.com/unify/r/{market_id}.{code}",
            f"https://stockpage.10jqka.com.cn/{code}/",
        )

    def _scrape(self, url: str, *, wait_for: int) -> dict[str, Any]:
        if not self.api_key:
            raise RuntimeError("FIRECRAWL_API_KEY is not configured")
        payload = {
            "url": url,
            "formats": [
                "markdown",
                {
                    "type": "json",
                    "schema": _QUOTE_SCHEMA,
                    "prompt": (
                        "Extract only the visible current quote fields. Return null for absent values; "
                        "do not infer or calculate missing values. Preserve the visible volume and amount "
                        "strings including Chinese units in volume_raw and amount_raw, then also return "
                        "their numeric values only when the page explicitly provides them."
                    ),
                },
            ],
            # Eastmoney's trade-status label is outside the semantic main
            # content on some pages.  Keep the full rendered source document
            # so a close-mode run can verify ``闭市`` rather than guessing.
            "onlyMainContent": False,
            "waitFor": wait_for,
            "proxy": "auto",
            "storeInCache": False,
            "maxAge": 0,
        }
        response = self.session.post(
            self.api_url,
            json=payload,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            timeout=45,
        )
        response.raise_for_status()
        body = response.json()
        if body.get("success") is False:
            raise RuntimeError(str(body.get("error") or "Firecrawl returned success=false"))
        return body.get("data", body)

    @staticmethod
    def _structured(data: dict[str, Any]) -> dict[str, Any]:
        value = data.get("json") or data.get("structuredData") or data.get("structured_data") or {}
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _bar(structured: dict[str, Any], analysis_date: str) -> dict[str, Any] | None:
        close = _number(structured.get("close_or_latest_price") or structured.get("close"))
        volume = _raw_or_number(structured, "volume_raw", "volume")
        amount = _raw_or_number(structured, "amount_raw", "amount")
        values = {
            "Date": analysis_date,
            "Open": _number(structured.get("open")),
            "High": _number(structured.get("high")),
            "Low": _number(structured.get("low")),
            "Close": close,
            "Volume": volume,
            "Amount": amount,
        }
        if any(value is None for value in values.values()):
            return None
        if values["Volume"] < 0 or values["Amount"] < 0:
            return None
        if values["Low"] > min(values["Open"], values["Close"]) or values["High"] < max(values["Open"], values["Close"]):
            return None
        if not _amount_is_consistent(close=values["Close"], volume=values["Volume"], amount=values["Amount"]):
            return None
        return values

    def resolve(self, query: str, allowed_domains: tuple[str, ...]) -> list[dict[str, Any]]:
        self.last_error = None
        symbol = _symbol_from_query(query)
        if symbol is None:
            self.last_error = "Firecrawl resolver could not find a six-digit .SS/.SZ symbol in query"
            return []
        analysis_date_match = re.search(r"\b\d{4}-\d{2}-\d{2}\b", query)
        if analysis_date_match is None:
            self.last_error = "Firecrawl resolver could not find an ISO analysis date in query"
            return []
        code, exchange = symbol
        attempts: list[dict[str, str]] = []
        for url in self._urls(code, exchange):
            for attempt in range(1, self.retries_per_url + 1):
                try:
                    data = self._scrape(url, wait_for=5_000 if attempt == 1 else 10_000)
                    structured = self._structured(data)
                    bar = self._bar(structured, analysis_date_match.group(0))
                    if bar is None:
                        raise ValueError("incomplete or invalid OHLCV/Amount response")
                    metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
                    source_url = str(metadata.get("sourceURL") or metadata.get("url") or url)
                    markdown = str(data.get("markdown") or "")
                    quote_timestamp = structured.get("quote_date_or_timestamp")
                    if not quote_timestamp:
                        timestamp_match = re.search(r"行情指标\s*(20\d{2}-\d{2}-\d{2}(?:\s+\d{2}:\d{2}:\d{2})?)", markdown)
                        quote_timestamp = timestamp_match.group(1) if timestamp_match else None
                    trading_status = str(structured.get("trading_status") or "").strip()
                    if trading_status.upper() not in _CLOSE_STATUSES:
                        # Do not infer a security's status from arbitrary
                        # page text.  Quote pages also contain global-market
                        # labels such as "沪股通 收盘", which are unrelated to
                        # the requested ETF/stock and would create a false
                        # close confirmation.  Only the structured field
                        # extracted from the target quote block is accepted.
                        trading_status = None
                    if trading_status is None:
                        # A page with a valid intraday bar but no close state
                        # cannot be used for a close-mode report.  Do not
                        # stop here: retry/fallback pages can expose the
                        # missing state.  The attempt remains in the raw MCP
                        # audit payload if a later source succeeds.
                        attempts.append({
                            "url": url,
                            "attempt": str(attempt),
                            "error": "MISSING_TRADING_STATUS",
                        })
                        break
                    return [{
                        "source_level": "B",
                        "source_url": source_url,
                        "payload": {
                            "bar": bar,
                            "quote_name": structured.get("name"),
                            "quote_timestamp": quote_timestamp,
                            "trading_status": trading_status,
                        "source_document": {
                                "markdown": markdown,
                                "metadata": metadata,
                            "structured_quote": structured,
                            "raw_units": {
                                "volume": structured.get("volume_raw"),
                                "amount": structured.get("amount_raw"),
                            },
                            },
                            "fetch_attempts": attempts,
                        },
                    }]
                except Exception as exc:
                    attempts.append({
                        "url": url,
                        "attempt": str(attempt),
                        "error": f"{type(exc).__name__}: {exc}",
                    })
                    if attempt < self.retries_per_url:
                        time.sleep(0.25 * attempt)
        self.last_error = " | ".join(item["error"] for item in attempts[-4:]) or "no Firecrawl attempt was made"
        return []


def build_firecrawl_resolver_from_env() -> FirecrawlEastmoneyResolver | None:
    """Return a configured resolver, or ``None`` when no local API key exists."""
    return FirecrawlEastmoneyResolver() if os.getenv("FIRECRAWL_API_KEY") else None
