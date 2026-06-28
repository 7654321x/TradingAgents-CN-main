from __future__ import annotations

from typing import Any, Dict, Iterable, List


FUND_TYPES = {
    "etf_feeder",
    "index_fund",
    "active_equity",
    "sector_theme",
    "qdii",
    "bond_fund",
    "money_fund",
    "balanced",
    "unknown",
}


def classify_fund(
    name: str = "",
    invest_scope: str = "",
    holdings: Iterable[Dict[str, Any]] | None = None,
    existing_type: str = "",
) -> Dict[str, Any]:
    if existing_type in FUND_TYPES and existing_type != "unknown":
        return {
            "fund_type": existing_type,
            "confidence": "high",
            "manual_review_required": False,
            "reasons": ["config_existing_type"],
        }

    text = f"{name} {invest_scope}".lower()
    reasons: List[str] = []
    fund_type = "unknown"
    confidence = "low"

    if "etf联接" in text or "联接" in text and "etf" in text:
        fund_type = "etf_feeder"
        confidence = "high"
        reasons.append("name_contains_etf_feeder")
    elif any(token in text for token in ("qdii", "全球", "纳斯达克", "标普", "恒生", "海外")):
        fund_type = "qdii"
        confidence = "medium"
        reasons.append("name_contains_qdii_keyword")
    elif "货币" in text:
        fund_type = "money_fund"
        confidence = "high"
        reasons.append("name_contains_money")
    elif "债券" in text or "债" in text:
        fund_type = "bond_fund"
        confidence = "high"
        reasons.append("name_contains_bond")
    elif "指数" in text and "增强" not in text:
        fund_type = "index_fund"
        confidence = "medium_high"
        reasons.append("name_contains_index")
    elif any(token in text for token in ("半导体", "芯片", "科技", "人工智能", "新能源", "医药", "消费")):
        fund_type = "sector_theme"
        confidence = "medium"
        reasons.append("name_contains_theme_keyword")
    elif "混合" in text or "股票" in text:
        fund_type = "active_equity"
        confidence = "medium"
        reasons.append("name_contains_equity_keyword")

    holding_list = list(holdings or [])
    if fund_type == "unknown" and holding_list:
        equity_count = sum(1 for item in holding_list if str(item.get("holding_stock_code") or item.get("code") or "").isdigit())
        if equity_count >= 5:
            fund_type = "active_equity"
            confidence = "medium_low"
            reasons.append("holdings_look_like_equities")

    return {
        "fund_type": fund_type,
        "confidence": confidence,
        "manual_review_required": fund_type == "unknown" or confidence in {"low", "medium_low"},
        "reasons": reasons or ["insufficient_evidence"],
    }
