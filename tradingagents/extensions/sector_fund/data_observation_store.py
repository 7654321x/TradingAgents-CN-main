"""Auditable storage for non-price fund analysis observations."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, time, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from tradingagents.storage.models import FundDataObservation, Instrument


def save_observation(
    session: Session, *, dataset_type: str, field_name: str, value: Any,
    source_level: str, source: str, source_url: str | None, confirmation_status: str,
    applicable_date: str | None = None, published_date: str | None = None,
    instrument_symbol: str | None = None, fund_code: str | None = "020671",
    status: str = "SUCCESS", error_message: str | None = None,
    available_at: datetime | None = None, fetched_at: datetime | None = None,
) -> bool:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    payload_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    instrument_id = None
    if instrument_symbol:
        instrument_id = session.scalar(select(Instrument.id).where(Instrument.symbol == instrument_symbol))
    existing = session.scalar(
        select(FundDataObservation.id).where(
            FundDataObservation.instrument_id == instrument_id,
            FundDataObservation.fund_code == fund_code,
            FundDataObservation.dataset_type == dataset_type,
            FundDataObservation.field_name == field_name,
            FundDataObservation.applicable_date == applicable_date,
            FundDataObservation.source == source,
            FundDataObservation.payload_hash == payload_hash,
        )
    )
    if existing:
        return False
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    available_at = available_at or now
    fetched_at = fetched_at or now
    session.add(FundDataObservation(
        instrument_id=instrument_id, fund_code=fund_code, dataset_type=dataset_type,
        field_name=field_name, applicable_date=applicable_date, published_date=published_date,
        available_at=available_at, source_level=source_level, source=source, source_url=source_url,
        confirmation_status=confirmation_status, payload_hash=payload_hash, value_json=payload,
        fetched_at=fetched_at, status=status, error_message=error_message,
    ))
    return True


def latest_observations(
    session: Session,
    *,
    dataset_type: str,
    analysis_date: str,
    fund_code: str,
    limit: int = 200,
    include_failed: bool = False,
) -> list[dict[str, Any]]:
    """Read one fund's observations that were available by the analysis date."""
    local_end = datetime.combine(
        datetime.fromisoformat(analysis_date).date(), time.max, tzinfo=ZoneInfo("Asia/Shanghai")
    )
    as_of_utc = local_end.astimezone(timezone.utc).replace(tzinfo=None)
    query = (
        select(FundDataObservation)
        .where(FundDataObservation.dataset_type == dataset_type)
        .where(FundDataObservation.fund_code == fund_code)
        .where((FundDataObservation.applicable_date.is_(None)) | (FundDataObservation.applicable_date <= analysis_date))
        .where(FundDataObservation.available_at <= as_of_utc)
        .order_by(
            FundDataObservation.applicable_date.desc(),
            FundDataObservation.fetched_at.desc(),
            FundDataObservation.id.desc(),
        )
        .limit(limit)
    )
    if not include_failed:
        query = query.where(FundDataObservation.status == "SUCCESS")
    rows = session.scalars(query).all()
    instruments = {
        instrument.id: instrument.symbol
        for instrument in session.scalars(
            select(Instrument).where(Instrument.id.in_({row.instrument_id for row in rows if row.instrument_id is not None}))
        )
    }
    return [{
        "field_name": row.field_name, "instrument_symbol": instruments.get(row.instrument_id),
        "value": json.loads(row.value_json), "source_level": row.source_level,
        "source": row.source, "source_url": row.source_url, "confirmation_status": row.confirmation_status,
        "applicable_date": row.applicable_date, "published_date": row.published_date,
        "status": row.status, "error_message": row.error_message,
    } for row in rows]
