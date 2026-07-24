"""Official CSI industry classification plus a transparent supply-chain view."""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import requests

BASE_URL = "https://www.csindex.com.cn/csindex-home"
SEARCH_URL = f"{BASE_URL}/indexInfo/security-industry-search"
UPDATE_DATE_URL = f"{BASE_URL}/indexInfo/getsecurityIndustrySearchData"

SUPPLY_CHAIN_BY_CICS4 = {
    "集成电路设计": "芯片设计",
    "集成电路制造": "晶圆制造",
    "半导体设备": "半导体设备",
    "半导体材料": "半导体材料",
    "集成电路封装与测试": "封装测试",
    "光学元件": "光电子与光学元件",
    "通信系统设备及组件": "其他相关组件",
}


@dataclass(frozen=True)
class CSIIndustryClassification:
    security_code: str
    security_name: str
    as_of_date: str
    cics1_code: str | None
    cics1_name: str | None
    cics2_code: str | None
    cics2_name: str | None
    cics3_code: str | None
    cics3_name: str | None
    cics4_code: str | None
    cics4_name: str | None
    supply_chain: str
    supply_chain_rule: str
    source_url: str
    fetched_at: str
    source: str = "csindex_official"

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def _response_data(response: requests.Response, context: str) -> Any:
    response.raise_for_status()
    payload = response.json()
    if payload.get("code") != "200" or not payload.get("success"):
        raise ValueError(f"CSI industry endpoint failed for {context}: {payload.get('msg')}")
    return payload.get("data")


def fetch_csindex_industry_classifications(
    security_codes: Iterable[str],
    *,
    timeout: float = 20.0,
    session: requests.Session | None = None,
) -> tuple[CSIIndustryClassification, ...]:
    """Fetch exact-code CICS classifications and derive a versioned chain bucket."""
    codes = tuple(dict.fromkeys(str(code).strip().zfill(6) for code in security_codes))
    if not codes or any(len(code) != 6 or not code.isdigit() for code in codes):
        raise ValueError("security_codes must contain valid six-digit codes")
    http = session or requests.Session()
    headers = {"User-Agent": "TradingAgents/1.0"}
    raw_date = str(_response_data(http.get(UPDATE_DATE_URL, headers=headers, timeout=timeout), "update-date"))
    if len(raw_date) != 8 or not raw_date.isdigit():
        raise ValueError(f"invalid CSI industry update date: {raw_date}")
    as_of_date = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:]}"
    fetched_at = datetime.now(timezone.utc).isoformat()
    results = []
    for code in codes:
        payload = {
            "searchInput": code,
            "pageNum": 1,
            "pageSize": 10,
            "sortField": None,
            "sortOrder": None,
        }
        rows = _response_data(
            http.post(SEARCH_URL, json=payload, headers=headers, timeout=timeout), code
        ) or []
        exact = [row for row in rows if str(row.get("securityCode", "")).zfill(6) == code]
        if len(exact) != 1:
            raise ValueError(f"CSI industry exact match count for {code}: {len(exact)}")
        row = exact[0]
        cics4 = row.get("cics4thName")
        results.append(
            CSIIndustryClassification(
                security_code=code,
                security_name=str(row.get("securityName") or code),
                as_of_date=as_of_date,
                cics1_code=row.get("cics1stCode"),
                cics1_name=row.get("cics1stName"),
                cics2_code=row.get("cics2ndCode"),
                cics2_name=row.get("cics2ndName"),
                cics3_code=row.get("cics3rdCode"),
                cics3_name=row.get("cics3rdName"),
                cics4_code=row.get("cics4thCode"),
                cics4_name=cics4,
                supply_chain=SUPPLY_CHAIN_BY_CICS4.get(cics4, "未分类"),
                supply_chain_rule="cics4_rule_v1",
                source_url=SEARCH_URL,
                fetched_at=fetched_at,
            )
        )
    return tuple(results)
