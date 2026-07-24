"""Database-only fund NAV, ETF status, and cached event context for reports."""
from __future__ import annotations

import json
from types import SimpleNamespace

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tradingagents.storage.models import (
    EtfStatusObservation,
    FundDataObservation,
    FundMetadataSnapshot,
    FundNavObservation,
    Instrument,
)

from .data_observation_store import latest_observations
from .event_store import load_recent_fund_events
from .mcp_observation_store import latest_mcp_observations
from .nav_metrics import calculate_fund_nav_metrics
from .source_policy import source_policy_summary


def load_fund_context(
    session: Session,
    *,
    fund_code: str,
    etf_code: str,
    analysis_date: str,
    market_date: str,
) -> dict[str, object]:
    """Read existing database rows only. This function never calls a provider."""
    nav_rows = session.scalars(
        select(FundNavObservation)
        .join(Instrument, Instrument.id == FundNavObservation.fund_instrument_id)
        .where(
            Instrument.local_code == fund_code,
            FundNavObservation.nav_date <= analysis_date,
            FundNavObservation.status == "SUCCESS",
        )
        .order_by(FundNavObservation.nav_date)
    ).all()
    nav = None
    if nav_rows:
        nav = calculate_fund_nav_metrics(
            [
                SimpleNamespace(
                    fund_code=fund_code,
                    nav_date=row.nav_date,
                    unit_nav=row.unit_nav,
                    cumulative_nav=row.cumulative_nav,
                    daily_change_pct=row.daily_change_pct,
                    source=row.source,
                )
                for row in nav_rows
            ],
            analysis_date,
        ).to_dict()
    metadata = session.scalar(
        select(FundMetadataSnapshot)
        .join(Instrument, Instrument.id == FundMetadataSnapshot.fund_instrument_id)
        .where(
            Instrument.local_code == fund_code,
            FundMetadataSnapshot.as_of_date <= analysis_date,
            FundMetadataSnapshot.status == "SUCCESS",
        )
        .order_by(FundMetadataSnapshot.as_of_date.desc(), FundMetadataSnapshot.id.desc())
    )
    identity = json.loads(metadata.payload_json) if metadata and metadata.payload_json else {}
    product_terms = {
        "purchase_fee_description": identity.get("purchase_fee_description"),
        "redemption_fee_description": identity.get("redemption_fee_description"),
        "management_fee_pct": identity.get("management_fee_pct"),
        "custody_fee_pct": identity.get("custody_fee_pct"),
        "sales_service_fee_pct": identity.get("sales_service_fee_pct"),
        "fund_purchase_redemption_status": "UNAVAILABLE_FROM_VERIFIED_SOURCE",
        "etf_primary_market_subscription_redemption_status": "UNAVAILABLE_FROM_VERIFIED_SOURCE",
    }
    etf_rows = session.scalars(
        select(EtfStatusObservation)
        .join(Instrument, Instrument.id == EtfStatusObservation.etf_instrument_id)
        .where(
            Instrument.local_code == etf_code,
            EtfStatusObservation.observed_date <= analysis_date,
            EtfStatusObservation.status == "SUCCESS",
        )
        .order_by(EtfStatusObservation.observed_at.desc(), EtfStatusObservation.id.desc())
    ).all()
    # Several intraday snapshots can exist for one observed date.  A same-day
    # pair measures a clock-time change, not an ETF share change, so retain
    # only the latest snapshot from each distinct trading date.
    distinct_dates = []
    seen_dates = set()
    for row in etf_rows:
        if row.observed_date in seen_dates:
            continue
        distinct_dates.append(row)
        seen_dates.add(row.observed_date)
        if len(distinct_dates) == 2:
            break
    etf = distinct_dates[0] if distinct_dates else None
    previous_etf = distinct_dates[1] if len(distinct_dates) > 1 else None
    shares_change_pct = (
        (etf.shares / previous_etf.shares - 1) * 100
        if etf
        and previous_etf
        and etf.shares is not None
        and previous_etf.shares not in {None, 0}
        else None
    )
    etf_payload = (
        {
            "observed_date": etf.observed_date,
            "observed_at": etf.observed_at.isoformat(),
            "nav_date": etf.nav_date,
            "unit_nav": etf.unit_nav,
            "market_price": etf.market_price,
            "iopv": etf.iopv,
            "discount_rate_pct": etf.discount_rate_pct,
            "shares": etf.shares,
            "shares_change_pct": shares_change_pct,
            "shares_change_status": "AVAILABLE" if shares_change_pct is not None else "INSUFFICIENT_HISTORY",
            "previous_observed_at": previous_etf.observed_at.isoformat() if previous_etf else None,
            "amount": etf.amount,
            "circulating_market_cap": etf.circulating_market_cap,
            "total_market_cap": etf.total_market_cap,
            "source": etf.source,
        }
        if etf
        else None
    )
    events = []
    for event in load_recent_fund_events(session, fund_code, analysis_date, days=7):
        if event.event_date < market_date:
            reflection = "MARKET_PERIOD_AFTER_EVENT_EXISTS"
        elif event.event_date == market_date:
            reflection = "SAME_DAY_NOT_ASSESSED"
        else:
            reflection = "NO_POST_EVENT_MARKET_DATA"
        events.append(
            {
                "event_date": event.event_date,
                "available_at": event.available_at.isoformat(),
                "title": event.title,
                "url": event.url,
                "source": event.source,
                "source_level": event.source_level,
                "event_type": event.event_type,
                "confirmation_status": event.confirmation_status,
                "market_reflection_status": reflection,
            }
        )
    health_rows = session.execute(
        select(
            FundDataObservation.dataset_type,
            FundDataObservation.status,
            func.count(),
            func.max(FundDataObservation.applicable_date),
        )
        .where((FundDataObservation.fund_code == fund_code) | (FundDataObservation.fund_code.is_(None)))
        .group_by(FundDataObservation.dataset_type, FundDataObservation.status)
    ).all()
    event_scans = latest_observations(
        session,
        dataset_type="event_scan",
        analysis_date=analysis_date,
        fund_code=fund_code,
        limit=10,
        include_failed=True,
    )
    completed_event_scan = next(
        (
            row
            for row in event_scans
            if row["status"] == "SUCCESS"
            and isinstance(row["value"], dict)
            and row["value"].get("status") == "SUCCESS"
            and row["value"].get("scanned_through_date") == analysis_date
        ),
        None,
    )
    return {
        "load_mode": "DATABASE_ONLY",
        "network_call_count": 0,
        "official_nav": nav,
        "product_terms": product_terms,
        "etf_status": etf_payload,
        "recent_events_7d": events,
        "event_scan_status": "COMPLETE" if completed_event_scan else "CACHED_EVENTS_ONLY",
        "field_health": [
            {
                "dataset_type": row[0],
                "status": row[1],
                "record_count": row[2],
                "latest_applicable_date": row[3],
            }
            for row in health_rows
        ],
        "extended_observations": {
            dataset: latest_observations(
                session,
                dataset_type=dataset,
                analysis_date=analysis_date,
                fund_code=fund_code,
                limit=30,
                include_failed=True,
            )
            # ``news_lead`` is intentionally separate from scoring inputs.
            # It contains only traceable C-level media context and must never
            # be promoted to an event fact without an A/B confirmation.
            for dataset in (
                "market_structure",
                "fund_flow",
                "financial",
                "industry_cycle",
                "intraday",
                "news_lead",
                "market_data_audit",
                "event_scan",
            )
        },
        "mcp_web_observations": {
            "current_daily_market": latest_mcp_observations(
                session,
                dataset_type="current_daily_market",
                analysis_date=analysis_date,
                fund_code=fund_code,
                limit=80,
            ),
        },
        "source_policy": source_policy_summary(),
    }
