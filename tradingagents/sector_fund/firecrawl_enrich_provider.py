from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List

import requests


class FirecrawlEnrichProvider:
    def __init__(self, api_key: str | None = None, api_url: str | None = None, timeout: int = 20):
        self.api_key = api_key or _load_firecrawl_key()
        self.api_url = (api_url or os.environ.get("FIRECRAWL_API_URL") or "https://api.firecrawl.dev").rstrip("/")
        self.timeout = timeout

    def search_fund_info(self, fund_code: str, fund_name: str = "", max_results: int = 3) -> Dict[str, Any]:
        if not self.api_key:
            return {
                "source": "firecrawl",
                "source_status": "firecrawl_missing_key",
                "parser_status": "skipped",
                "error_reason": "FIRECRAWL_API_KEY is missing",
                "results": [],
                "extracted": {},
            }
        queries = [
            f"{fund_code} 基金档案",
            f"{fund_code} 天天基金",
            f"{fund_name} 投资范围" if fund_name else "",
            f"{fund_name} 业绩比较基准" if fund_name else "",
            f"{fund_name} 基金经理" if fund_name else "",
        ]
        results: List[Dict[str, Any]] = []
        errors: List[str] = []
        for query in [item for item in queries if item][:3]:
            payload = {"query": query, "limit": max_results}
            response = self._post_search(payload)
            if response.get("source_status") != "success":
                errors.append(response.get("error_reason", "firecrawl search failed"))
                continue
            for item in response.get("results", []):
                results.append(item)
        hydrated = []
        for item in results[:3]:
            url = item.get("url") or item.get("source_url")
            if not url:
                continue
            scraped = self._post_scrape(str(url))
            merged = {**item, **scraped.get("data", {})}
            merged["scrape_status"] = scraped.get("source_status")
            if scraped.get("error_reason"):
                merged["scrape_error_reason"] = scraped.get("error_reason")
            hydrated.append(merged)
        if hydrated:
            results = hydrated
        extracted = _extract_fields(results)
        return {
            "source": "firecrawl",
            "source_status": "success" if results else "failed",
            "parser_status": "success" if extracted else "no_match",
            "error_reason": "" if results else "; ".join(errors)[:500],
            "fetched_at": datetime.now().isoformat(timespec="seconds"),
            "results": _sanitize_results(results),
            "extracted": extracted,
            "confidence": "medium" if extracted else "low",
        }

    def _post_search(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        for path in ("/v2/search", "/v1/search"):
            try:
                response = requests.post(f"{self.api_url}{path}", headers=headers, json=payload, timeout=self.timeout)
                if response.status_code >= 400:
                    last_error = f"HTTP {response.status_code}: {response.text[:300]}"
                    continue
                body = response.json()
                data = body.get("data", body.get("results", body))
                if isinstance(data, dict) and isinstance(data.get("web"), list):
                    data = data["web"]
                if isinstance(data, dict) and isinstance(data.get("data"), list):
                    data = data["data"]
                if not isinstance(data, list):
                    data = []
                return {"source_status": "success", "results": data}
            except Exception as exc:
                last_error = str(exc)
        return {"source_status": "failed", "error_reason": locals().get("last_error", "firecrawl search failed")}

    def _post_scrape(self, url: str) -> Dict[str, Any]:
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        payload = {"url": url, "formats": ["markdown"]}
        for path in ("/v2/scrape", "/v1/scrape"):
            try:
                response = requests.post(f"{self.api_url}{path}", headers=headers, json=payload, timeout=self.timeout)
                if response.status_code >= 400:
                    last_error = f"HTTP {response.status_code}: {response.text[:300]}"
                    continue
                body = response.json()
                data = body.get("data", body)
                return {"source_status": "success", "data": data if isinstance(data, dict) else {}}
            except Exception as exc:
                last_error = str(exc)
        return {"source_status": "failed", "data": {}, "error_reason": locals().get("last_error", "firecrawl scrape failed")}


def _load_firecrawl_key() -> str:
    value = os.environ.get("FIRECRAWL_API_KEY", "")
    if value:
        return value
    env_path = Path(".env")
    if not env_path.exists():
        return ""
    for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, raw = line.split("=", 1)
        if key.strip() == "FIRECRAWL_API_KEY":
            return raw.strip().strip('"').strip("'")
    return ""


def _extract_fields(results: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    text = "\n".join(str(item.get("markdown") or item.get("content") or item.get("description") or item.get("snippet") or "") for item in results)
    extracted: Dict[str, Any] = {}
    manager = re.search(r"基金经理[:：\s]*([\u4e00-\u9fa5A-Za-z、·]{2,30})", text)
    if manager:
        extracted["fund_manager"] = manager.group(1).strip(" 。；;")
    benchmark = re.search(r"业绩比较基准[:：\s]*([^\n。]{4,120})", text)
    if benchmark:
        extracted["benchmark"] = benchmark.group(1).strip()
    scope = re.search(r"投资范围[:：\s]*([^\n]{10,200})", text)
    if scope:
        extracted["invest_scope"] = scope.group(1).strip()
    company = re.search(r"基金管理人[:：\s]*([\u4e00-\u9fa5A-Za-z（）()]{4,60})", text)
    if company:
        extracted["fund_company"] = company.group(1).strip()
    return extracted


def _sanitize_results(results: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    clean = []
    for item in results:
        clean.append(
            {
                "title": item.get("title", ""),
                "url": item.get("url") or item.get("source_url") or "",
                "description": item.get("description") or item.get("snippet") or "",
                "markdown_length": len(str(item.get("markdown") or item.get("content") or "")),
            }
        )
    return clean
