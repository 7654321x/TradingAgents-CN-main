from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

import requests


SECTOR_ALIAS_MAP = {
    "PCB": ["PCB", "印制电路板"],
    "AI芯片": ["AI芯片", "人工智能芯片", "算力芯片", "芯片概念"],
    "半导体": ["半导体", "半导体概念"],
    "存储芯片": ["存储芯片", "存储器", "半导体存储"],
    "半导体设备": ["半导体设备", "设备"],
    "消费电子": ["消费电子"],
    "科创芯片": ["科创芯片", "半导体", "芯片"],
    "芯片概念": ["芯片概念", "国产芯片", "AI芯片", "半导体"],
}

LOW_CONFIDENCE_SECTOR_ALIASES = {"芯片", "半导体", "设备"}


@dataclass
class EastMoneyQuoteResult:
    code: str
    name: str = ""
    latest_price: Optional[float] = None
    change_pct: Optional[float] = None
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    preclose: Optional[float] = None
    amount: Optional[float] = None
    turnover_rate: Optional[float] = None
    source: str = "eastmoney_push2"
    source_status: str = "not_started"
    error_reason: str = ""
    field_sources: Dict[str, str] | None = None

    def to_dict(self) -> Dict[str, Any]:
        data = {
            "code": self.code,
            "name": self.name,
            "latest_price": self.latest_price,
            "change_pct": self.change_pct,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "preclose": self.preclose,
            "amount": self.amount,
            "turnover_rate": self.turnover_rate,
            "source": self.source,
            "source_status": self.source_status,
            "error_reason": self.error_reason,
        }
        data["field_sources"] = self.field_sources or {
            key: self.source for key, value in data.items() if key not in {"source", "source_status", "error_reason", "field_sources"} and value not in (None, "")
        }
        return data


class EastMoneyQuoteProvider:
    """Structured EastMoney push2 quote provider for sector_fund diagnostics.

    This provider intentionally returns facts only. It does not generate decisions
    or transform facts into investment rules.
    """

    QUOTE_URL = "https://push2.eastmoney.com/api/qt/ulist.np/get"
    SECTOR_URL = "https://push2.eastmoney.com/api/qt/clist/get"
    SECTOR_FS_LIST = ("m:90+t:2", "m:90+t:3", "m:90")

    def __init__(self, timeout: int = 10):
        self.timeout = timeout
        self.last_error = ""

    def fetch_quotes(self, codes: Iterable[str]) -> Dict[str, Dict[str, Any]]:
        secids = [to_eastmoney_secid(code) for code in codes if code]
        if not secids:
            return {}
        try:
            response = requests.get(
                self.QUOTE_URL,
                timeout=self.timeout,
                headers=_headers(),
                params={
                    "fltt": "2",
                    "invt": "2",
                    "fields": "f12,f14,f2,f3,f17,f15,f16,f18,f6,f8",
                    "secids": ",".join(secids),
                },
            )
            response.raise_for_status()
            payload = response.json()
            rows = (payload.get("data") or {}).get("diff") or []
            result: Dict[str, Dict[str, Any]] = {}
            for row in rows:
                quote = _quote_from_row(row)
                result[quote.code] = quote.to_dict()
            return result
        except Exception as exc:
            self.last_error = str(exc)
            return {}

    def fetch_sector_changes(self, sector_names: Iterable[str]) -> Dict[str, Dict[str, Any]]:
        wanted = [name for name in sector_names if name]
        if not wanted:
            return {}
        try:
            rows: List[Dict[str, Any]] = []
            seen_codes = set()
            for fs in self.SECTOR_FS_LIST:
                for page in range(1, 8):
                    response = requests.get(
                        self.SECTOR_URL,
                        timeout=self.timeout,
                        headers=_headers(),
                        params={
                            "pn": str(page),
                            "pz": "100",
                            "po": "1",
                            "np": "1",
                            "fltt": "2",
                            "invt": "2",
                            "fid": "f3",
                            "fs": fs,
                            "fields": "f12,f14,f3,f6,f62",
                        },
                    )
                    response.raise_for_status()
                    page_rows = (response.json().get("data") or {}).get("diff") or []
                    if not page_rows:
                        break
                    for row in page_rows:
                        code = str(row.get("f12") or "")
                        if code and code not in seen_codes:
                            row["_fs"] = fs
                            rows.append(row)
                            seen_codes.add(code)
            result: Dict[str, Dict[str, Any]] = {}
            rows_by_name = [(str(row.get("f14") or ""), row) for row in rows]
            for wanted_name in wanted:
                matched = _match_sector(wanted_name, rows_by_name)
                if not matched:
                    continue
                name, row, match_method, confidence = matched
                result[wanted_name] = {
                    "code": row.get("f12"),
                    "name": name,
                    "change_pct": _num(row.get("f3")),
                    "amount": _num(row.get("f6")),
                    "main_inflow": _num(row.get("f62")),
                    "source": "eastmoney_push2_sector",
                    "source_status": "success",
                    "match_method": match_method,
                    "match_confidence": confidence,
                    "sector_fs": row.get("_fs"),
                    "field_sources": {
                        "change_pct": "eastmoney_push2_sector",
                        "amount": "eastmoney_push2_sector",
                        "main_inflow": "eastmoney_push2_sector",
                    },
                }
            return result
        except Exception as exc:
            self.last_error = str(exc)
            return {}


def to_eastmoney_secid(code: str) -> str:
    raw = str(code).strip().lower()
    if raw.startswith("sh."):
        return "1." + raw.replace("sh.", "")
    if raw.startswith("sz."):
        return "0." + raw.replace("sz.", "")
    if raw in {"上证指数", "上证综指"}:
        return "1.000001"
    if raw in {"深成指", "深证成指"}:
        return "0.399001"
    if raw == "创业板指":
        return "0.399006"
    if raw == "科创50":
        return "1.000688"
    digits = "".join(ch for ch in raw if ch.isdigit()).zfill(6)
    if digits.startswith(("5", "6", "9")):
        return f"1.{digits}"
    return f"0.{digits}"


def _match_sector(wanted_name: str, rows_by_name: List[tuple[str, Dict[str, Any]]]) -> tuple[str, Dict[str, Any], str, str] | None:
    for name, row in rows_by_name:
        if name == wanted_name:
            return name, row, "matched_by_exact", "high"
    aliases = SECTOR_ALIAS_MAP.get(wanted_name, [])
    for alias in aliases:
        for name, row in rows_by_name:
            if name == alias:
                confidence = "low" if alias in LOW_CONFIDENCE_SECTOR_ALIASES else "high"
                return name, row, f"matched_by_alias:{alias}", confidence
    for alias in aliases:
        for name, row in rows_by_name:
            if alias and (alias in name or name in alias):
                confidence = "low" if alias in LOW_CONFIDENCE_SECTOR_ALIASES else "medium"
                return name, row, f"matched_by_contains:{alias}", confidence
    for name, row in rows_by_name:
        if wanted_name in name or name in wanted_name:
            return name, row, "matched_by_contains", "medium"
    return None


def _quote_from_row(row: Dict[str, Any]) -> EastMoneyQuoteResult:
    code = str(row.get("f12") or "")
    source_status = "success" if code else "empty"
    return EastMoneyQuoteResult(
        code=code,
        name=str(row.get("f14") or ""),
        latest_price=_num(row.get("f2")),
        change_pct=_num(row.get("f3")),
        open=_num(row.get("f17")),
        high=_num(row.get("f15")),
        low=_num(row.get("f16")),
        preclose=_num(row.get("f18")),
        amount=_num(row.get("f6")),
        turnover_rate=_num(row.get("f8")),
        source_status=source_status,
    )


def _num(value: Any) -> Optional[float]:
    if value in (None, "", "-", "--"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _headers() -> Dict[str, str]:
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json,text/plain,*/*",
        "Referer": "https://quote.eastmoney.com/",
    }
