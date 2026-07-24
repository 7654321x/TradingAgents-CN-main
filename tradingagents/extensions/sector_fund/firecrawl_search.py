"""Firecrawl search-and-document resolver for non-quote web fallbacks.

Search-result snippets are discovery aids only.  This resolver requests the
associated page markdown, returns the original document plus provenance, and
leaves field extraction/confirmation to a later deterministic adapter.
"""
from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlparse

import requests

FIRECRAWL_SEARCH_URL = "https://api.firecrawl.dev/v2/search"


def _matches(url: str, domains: tuple[str, ...]) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host == domain.lower() or host.endswith(f".{domain.lower()}") for domain in domains)


class FirecrawlSearchDocumentResolver:
    """Return allowed original documents found through Firecrawl Search."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        api_url: str | None = None,
        session: requests.Session | None = None,
        official_domains: tuple[str, ...] = (),
        platform_domains: tuple[str, ...] = (),
        lead_domains: tuple[str, ...] = (),
    ):
        self.api_key = api_key or os.getenv("FIRECRAWL_API_KEY")
        self.api_url = api_url or os.getenv("FIRECRAWL_SEARCH_API_URL") or FIRECRAWL_SEARCH_URL
        self.session = session or requests.Session()
        self.official_domains = official_domains
        self.platform_domains = platform_domains
        self.lead_domains = lead_domains
        self.last_error: str | None = None

    @staticmethod
    def _results(body: dict[str, Any]) -> list[dict[str, Any]]:
        data = body.get("data", body)
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        if not isinstance(data, dict):
            return []
        for key in ("web", "results", "items"):
            value = data.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        return []

    def resolve(self, query: str, allowed_domains: tuple[str, ...]) -> list[dict[str, Any]]:
        self.last_error = None
        if not self.api_key:
            self.last_error = "FIRECRAWL_API_KEY is not configured"
            return []
        payload = {
            "query": query,
            "limit": 5,
            "scrapeOptions": {
                "formats": ["markdown"],
                "onlyMainContent": False,
                "waitFor": 5_000,
            },
        }
        try:
            response = self.session.post(
                self.api_url,
                json=payload,
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                timeout=45,
            )
            response.raise_for_status()
            body = response.json()
            if body.get("success") is False:
                raise RuntimeError(str(body.get("error") or "Firecrawl Search returned success=false"))
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            return []
        resolved: list[dict[str, Any]] = []
        for item in self._results(body):
            metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            url = str(item.get("url") or metadata.get("sourceURL") or metadata.get("url") or "")
            markdown = item.get("markdown") or item.get("content")
            if not url or not _matches(url, allowed_domains) or not isinstance(markdown, str) or not markdown.strip():
                continue
            if _matches(url, self.official_domains):
                level = "A"
            elif _matches(url, self.platform_domains):
                level = "B"
            elif _matches(url, self.lead_domains):
                level = "C"
            else:
                continue
            resolved.append(
                {
                    "source_level": level,
                    "source_url": url,
                    "payload": {
                        "search_query": query,
                        "source_document": {"markdown": markdown, "metadata": metadata},
                    },
                }
            )
        if not resolved:
            self.last_error = "No allowed result with a retrievable original page document"
        return resolved


def build_firecrawl_search_resolver_from_env(
    *,
    official_domains: tuple[str, ...] = (),
    platform_domains: tuple[str, ...] = (),
    lead_domains: tuple[str, ...] = (),
) -> FirecrawlSearchDocumentResolver | None:
    return (
        FirecrawlSearchDocumentResolver(
            official_domains=official_domains,
            platform_domains=platform_domains,
            lead_domains=lead_domains,
        )
        if os.getenv("FIRECRAWL_API_KEY")
        else None
    )
