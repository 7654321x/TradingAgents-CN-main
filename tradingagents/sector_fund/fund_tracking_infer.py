from __future__ import annotations

from typing import Any, Dict, Iterable, List


THEME_SECTORS = {
    "芯片": ["半导体概念", "国产芯片", "存储芯片", "科创芯片"],
    "半导体": ["半导体概念", "半导体设备", "国产芯片"],
    "科技": ["人工智能", "消费电子", "PCB"],
    "存储": ["存储芯片", "半导体概念"],
}

THEME_ETFS = {
    "芯片": ["588200", "588290", "512480", "159995"],
    "半导体": ["588200", "588290", "512480", "159995"],
}

THEME_INDICES = {
    "科创": ["科创50"],
    "创业": ["创业板指"],
}


def infer_tracking(
    fund_type: str,
    fund_name: str,
    holdings: Iterable[Dict[str, Any]] | None = None,
    existing_tracking: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    existing_tracking = existing_tracking or {}
    holding_list = list(holdings or [])
    tracking = {
        "stocks": [],
        "sectors": [],
        "etfs": [],
        "indices": [],
        "tracking_source": "",
        "confidence": "low",
        "holding_is_stale": bool(holding_list),
        "notes": [],
    }

    if fund_type in {"active_equity", "sector_theme"} and not existing_tracking.get("stocks"):
        tracking["stocks"] = [
            {
                "code": str(item.get("holding_stock_code") or item.get("code") or ""),
                "name": str(item.get("holding_stock_name") or item.get("name") or ""),
                "source": "akshare_holdings",
                "confidence": "medium",
            }
            for item in holding_list[:10]
            if item.get("holding_stock_code") or item.get("code")
        ]
        if tracking["stocks"]:
            tracking["tracking_source"] = "akshare_holdings"
            tracking["confidence"] = "medium"
            tracking["notes"].append("基金持仓来自季度披露，可能滞后，不代表实时持仓。")

    text = fund_name or ""
    for token, sectors in THEME_SECTORS.items():
        if token in text and not existing_tracking.get("sectors"):
            tracking["sectors"].extend({"name": item, "source": "name_keyword", "confidence": "medium_low"} for item in sectors)
    for token, etfs in THEME_ETFS.items():
        if token in text and fund_type == "etf_feeder" and not existing_tracking.get("etfs"):
            tracking["etfs"].extend({"code": item, "source": "name_keyword_suggestion", "confidence": "medium_low"} for item in etfs)
    for token, indices in THEME_INDICES.items():
        if token in text and not existing_tracking.get("indices"):
            tracking["indices"].extend({"name": item, "source": "name_keyword_suggestion", "confidence": "medium_low"} for item in indices)

    tracking["sectors"] = _dedupe_dicts(tracking["sectors"], "name")
    tracking["etfs"] = _dedupe_dicts(tracking["etfs"], "code")
    tracking["indices"] = _dedupe_dicts(tracking["indices"], "name")
    if tracking["sectors"] and tracking["confidence"] == "low":
        tracking["confidence"] = "medium_low"
    if not any(tracking[key] for key in ("stocks", "sectors", "etfs", "indices")):
        tracking["notes"].append("未能自动推断 tracking，建议人工补充。")
    return tracking


def _dedupe_dicts(items: List[Dict[str, Any]], key: str) -> List[Dict[str, Any]]:
    seen = set()
    result = []
    for item in items:
        value = item.get(key)
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(item)
    return result
