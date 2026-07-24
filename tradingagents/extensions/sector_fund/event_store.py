"""Database-first event sync and read service.

Reports call ``load_recent_fund_events`` only. Network access exists solely in
the explicit ``sync_fund_events`` workflow.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from tradingagents.storage.db import init_db
from tradingagents.storage.models import FundEvent, FundEventSyncState, Instrument

from .event_provider import fetch_efunds_events


def _naive_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed
    return parsed.astimezone(timezone.utc).replace(tzinfo=None)


def sync_fund_events(
    fund_code: str,
    *,
    engine=None,
    provider: Callable = fetch_efunds_events,
    force: bool = False,
    minimum_refresh_hours: int = 24,
    now: datetime | None = None,
    scanned_through_date: str | None = None,
    lookback_days: int = 7,
) -> dict[str, object]:
    """Sync official events, optionally proving a bounded as-of-date scan.

    ``scanned_through_date`` is used by an as-of report.  It intentionally
    bypasses the ordinary incremental cursor so an empty seven-day result can
    be audited as a completed scan instead of being confused with no cache.
    """
    engine = init_db(engine)
    checked_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).replace(tzinfo=None)
    with Session(engine) as session:
        fund = session.scalar(
            select(Instrument).where(
                Instrument.local_code == str(fund_code), Instrument.instrument_type == "fund"
            )
        )
        if fund is None:
            raise ValueError(f"fund instrument not found: {fund_code}")
        state = session.scalar(
            select(FundEventSyncState).where(
                FundEventSyncState.fund_instrument_id == fund.id,
                FundEventSyncState.source == "efunds_official",
            )
        )
        if (
            not force
            and scanned_through_date is None
            and state is not None
            and state.last_checked_at is not None
            and checked_at - state.last_checked_at < timedelta(hours=minimum_refresh_hours)
        ):
            return {
                "status": "SKIPPED_RECENTLY_SYNCED",
                "provider_call_count": 0,
                "inserted": 0,
                "last_successful_event_date": state.last_successful_event_date,
            }
        cursor = state.last_successful_event_date if state else None
        if scanned_through_date is not None:
            through = date.fromisoformat(scanned_through_date)
            since_exclusive = (through - timedelta(days=lookback_days)).isoformat()
        else:
            # Re-read the cursor date to catch multiple announcements published on
            # that day; dedup_key prevents duplicate inserts.
            since_exclusive = (
                (datetime.fromisoformat(cursor).date() - timedelta(days=1)).isoformat()
                if cursor
                else None
            )
        if state is None:
            state = FundEventSyncState(
                fund_instrument_id=fund.id,
                source="efunds_official",
                status="RUNNING",
            )
            session.add(state)
            session.flush()
        try:
            events = provider(fund_code, since_exclusive=since_exclusive)
            if scanned_through_date is not None:
                events = [event for event in events if event.event_date <= scanned_through_date]
            inserted = 0
            for event in events:
                if session.scalar(select(FundEvent.id).where(FundEvent.dedup_key == event.dedup_key)):
                    continue
                session.add(
                    FundEvent(
                        fund_instrument_id=fund.id,
                        event_date=event.event_date,
                        available_at=_naive_utc(event.available_at),
                        title=event.title,
                        url=event.url,
                        source=event.source,
                        source_level=event.source_level,
                        event_type=event.event_type,
                        confirmation_status=event.confirmation_status,
                        already_reflected_status=event.already_reflected_status,
                        content_hash=event.content_hash,
                        dedup_key=event.dedup_key,
                        summary=event.summary,
                        fetched_at=_naive_utc(event.fetched_at),
                        payload_json=json.dumps(event.to_dict(), ensure_ascii=False, sort_keys=True),
                    )
                )
                inserted += 1
            newest = max((event.event_date for event in events), default=cursor)
            state.last_successful_event_date = max(filter(None, [cursor, newest]), default=None)
            state.last_checked_at = checked_at
            state.status = "SUCCESS"
            state.error_message = None
            session.commit()
            return {
                "status": "SUCCESS",
                "provider_call_count": 1,
                "received": len(events),
                "inserted": inserted,
                "last_successful_event_date": state.last_successful_event_date,
                "scanned_through_date": scanned_through_date,
                "lookback_days": lookback_days if scanned_through_date is not None else None,
            }
        except Exception as exc:
            state.last_checked_at = checked_at
            state.status = "FAILED"
            state.error_message = f"{type(exc).__name__}: {exc}"
            session.commit()
            raise


def load_recent_fund_events(
    session: Session, fund_code: str, analysis_date: str, *, days: int = 7
) -> list[FundEvent]:
    """Read cached events only; this function performs no network access."""
    cutoff = (datetime.fromisoformat(analysis_date).date() - timedelta(days=days - 1)).isoformat()
    end_available = datetime.combine(
        datetime.fromisoformat(analysis_date).date(), datetime.max.time()
    )
    return session.scalars(
        select(FundEvent)
        .join(Instrument, Instrument.id == FundEvent.fund_instrument_id)
        .where(
            Instrument.local_code == str(fund_code),
            FundEvent.event_date >= cutoff,
            FundEvent.event_date <= analysis_date,
            FundEvent.available_at <= end_available,
        )
        .order_by(FundEvent.available_at.desc(), FundEvent.id.desc())
    ).all()
