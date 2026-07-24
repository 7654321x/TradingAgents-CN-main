"""Storage for raw documents obtained through the MCP web-resolver boundary."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, time, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from tradingagents.storage.models import Instrument, McpWebObservation


def save_mcp_observation(
    session: Session, *, dataset_type: str, field_name: str, payload: dict[str, Any] | None,
    source_level: str, source: str, source_url: str | None, confirmation_status: str,
    applicable_date: str | None = None, published_date: str | None = None,
    instrument_symbol: str | None = None, fund_code: str | None = "020671",
    status: str = "SUCCESS", error_message: str | None = None,
    available_at: datetime | None = None, fetched_at: datetime | None = None,
) -> bool:
    """Persist an MCP document without writing to API or market-bar tables."""
    payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str) if payload is not None else None
    content_hash = hashlib.sha256((payload_json or error_message or status).encode("utf-8")).hexdigest()
    instrument_id = None
    if instrument_symbol:
        instrument_id = session.scalar(select(Instrument.id).where(Instrument.symbol == instrument_symbol))
    existing = session.scalar(
        select(McpWebObservation.id).where(
            McpWebObservation.instrument_id == instrument_id,
            McpWebObservation.fund_code == fund_code,
            McpWebObservation.dataset_type == dataset_type,
            McpWebObservation.field_name == field_name,
            McpWebObservation.applicable_date == applicable_date,
            McpWebObservation.source == source,
            McpWebObservation.content_hash == content_hash,
        )
    )
    if existing:
        return False
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    available_at = available_at or now
    fetched_at = fetched_at or now
    session.add(McpWebObservation(
        instrument_id=instrument_id, fund_code=fund_code, dataset_type=dataset_type,
        field_name=field_name, applicable_date=applicable_date, published_date=published_date,
        available_at=available_at, source_level=source_level, source=source, source_url=source_url,
        confirmation_status=confirmation_status, content_hash=content_hash, payload_json=payload_json,
        fetched_at=fetched_at, status=status, error_message=error_message,
    ))
    return True


def latest_mcp_observations(
    session: Session, *, dataset_type: str, analysis_date: str, fund_code: str, limit: int = 200,
    include_failed: bool = False,
) -> list[dict[str, Any]]:
    """Read only MCP records that were available by the requested date."""
    local_end = datetime.combine(
        datetime.fromisoformat(analysis_date).date(), time.max, tzinfo=ZoneInfo("Asia/Shanghai")
    )
    as_of_utc = local_end.astimezone(timezone.utc).replace(tzinfo=None)
    query = (
        select(McpWebObservation)
        .where(McpWebObservation.dataset_type == dataset_type)
        .where(McpWebObservation.fund_code == fund_code)
        .where((McpWebObservation.applicable_date.is_(None)) | (McpWebObservation.applicable_date <= analysis_date))
        .where(McpWebObservation.available_at <= as_of_utc)
        .order_by(McpWebObservation.applicable_date.desc(), McpWebObservation.fetched_at.desc(), McpWebObservation.id.desc())
        .limit(limit)
    )
    if not include_failed:
        query = query.where(McpWebObservation.status == "SUCCESS")
    rows = session.scalars(query).all()
    return [{
        "field_name": row.field_name, "payload": json.loads(row.payload_json) if row.payload_json else None,
        "source_level": row.source_level, "source": row.source, "source_url": row.source_url,
        "confirmation_status": row.confirmation_status, "applicable_date": row.applicable_date,
        "published_date": row.published_date, "status": row.status, "error_message": row.error_message,
    } for row in rows]


_CLOSE_STATUSES = {"闭市", "已收盘", "收盘", "交易结束", "CLOSED", "CLOSE"}


def load_current_daily_bar(
    session: Session,
    *,
    instrument_symbol: str,
    analysis_date: str,
    fund_code: str = "020671",
    require_close_confirmation: bool = False,
) -> dict[str, Any] | None:
    """Return a verified MCP raw bar; never falls back to ``market_bar_observation``.

    ``SUCCESS`` means a web document passed structural validation.  It does
    not by itself prove that a same-day quote is final, so close-mode callers
    must opt into the target-security trading-status check.
    """
    row = session.scalar(
        select(McpWebObservation)
        .join(Instrument, Instrument.id == McpWebObservation.instrument_id)
        .where(Instrument.symbol == instrument_symbol)
        .where(McpWebObservation.dataset_type == "current_daily_market")
        .where(McpWebObservation.field_name == "daily_bar")
        .where(McpWebObservation.applicable_date == analysis_date)
        .where(McpWebObservation.fund_code == fund_code)
        .where(McpWebObservation.status == "SUCCESS")
        .where(McpWebObservation.source_level.in_(("A", "B")))
        .where(McpWebObservation.confirmation_status == "VERIFIED_WEB_SOURCE")
        .order_by(McpWebObservation.fetched_at.desc(), McpWebObservation.id.desc())
    )
    if row is None or not row.payload_json:
        return None
    payload = json.loads(row.payload_json)
    if require_close_confirmation:
        status = str(payload.get("trading_status") or "").strip().upper()
        if status not in _CLOSE_STATUSES:
            return None
    return payload.get("bar") if isinstance(payload, dict) else None
