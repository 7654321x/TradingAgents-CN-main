"""Non-destructive quality audit for cached sector-fund observations."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from tradingagents.storage.models import FundDataObservation, McpWebObservation


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _amount_is_consistent(bar: dict[str, Any]) -> bool:
    close = _number(bar.get("Close"))
    volume = _number(bar.get("Volume"))
    amount = _number(bar.get("Amount"))
    if close is None or volume is None or amount is None:
        return False
    if volume == 0:
        return amount == 0
    implied_price = amount / (volume * 100.0)
    return close * 0.15 <= implied_price <= close * 6.0


@dataclass(frozen=True)
class DataQualityAuditResult:
    inspected_mcp_rows: int
    inspected_derived_rows: int
    invalid_mcp_ids: tuple[int, ...]
    invalid_derived_ids: tuple[int, ...]
    applied: bool


def audit_sector_fund_data(
    session: Session,
    *,
    fund_code: str,
    analysis_date: str,
    apply: bool = False,
) -> DataQualityAuditResult:
    """Flag, but never delete, records that cannot be used for analysis.

    This audit only invalidates two objectively unsafe cases:

    * MCP current-day bars whose amount/volume/price units are inconsistent;
    * derived market structures assembled from more than one market date.
    """
    mcp_rows = session.scalars(
        select(McpWebObservation)
        .where(McpWebObservation.fund_code == fund_code)
        .where(McpWebObservation.dataset_type == "current_daily_market")
        .where(McpWebObservation.applicable_date == analysis_date)
        .where(McpWebObservation.status == "SUCCESS")
    ).all()
    derived_rows = session.scalars(
        select(FundDataObservation)
        .where(FundDataObservation.fund_code == fund_code)
        .where(FundDataObservation.dataset_type == "market_structure")
        .where(FundDataObservation.applicable_date == analysis_date)
        .where(FundDataObservation.status == "SUCCESS")
    ).all()

    invalid_mcp = []
    for row in mcp_rows:
        payload = json.loads(row.payload_json) if row.payload_json else {}
        bar = payload.get("bar") if isinstance(payload, dict) else None
        if not isinstance(bar, dict) or not _amount_is_consistent(bar):
            invalid_mcp.append(row)

    invalid_derived = []
    for row in derived_rows:
        value = json.loads(row.value_json) if row.value_json else {}
        dates = value.get("latest_market_dates") if isinstance(value, dict) else None
        if isinstance(dates, list) and len(set(dates)) > 1:
            invalid_derived.append(row)

    if apply:
        for row in invalid_mcp:
            row.status = "INVALIDATED"
            row.error_message = "AMOUNT_VOLUME_PRICE_UNIT_INCONSISTENT"
        for row in invalid_derived:
            row.status = "INVALIDATED"
            row.error_message = "MIXED_MARKET_DATES"
        session.commit()

    return DataQualityAuditResult(
        inspected_mcp_rows=len(mcp_rows),
        inspected_derived_rows=len(derived_rows),
        invalid_mcp_ids=tuple(row.id for row in invalid_mcp),
        invalid_derived_ids=tuple(row.id for row in invalid_derived),
        applied=apply,
    )
