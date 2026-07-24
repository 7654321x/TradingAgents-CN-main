"""Traceable fund/index identity and constituent snapshot ingestion.

This module deliberately does not invent an index code when the configured
source has not supplied one.  Providers can be added later without changing
the storage contract.
"""
from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from tradingagents.storage.db import init_db
from tradingagents.storage.models import (
    EtfStatusObservation,
    FundMetadataSnapshot,
    FundNavObservation,
    Instrument,
    Universe,
    UniverseConstituentWeight,
    UniverseSnapshot,
)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _instrument(session: Session, item: dict[str, Any], instrument_type: str) -> Instrument:
    symbol = str(item["symbol"])
    obj = session.scalar(select(Instrument).where(Instrument.symbol == symbol))
    if obj is None:
        obj = Instrument(
            symbol=symbol,
            local_code=item.get("local_code"),
            name=item.get("name"),
            instrument_type=instrument_type,
            exchange=item.get("exchange"),
            currency=item.get("currency"),
            timezone=item.get("timezone", "Asia/Shanghai"),
        )
        session.add(obj)
        session.flush()
    return obj


def save_fund_metadata_snapshot(
    session: Session,
    *,
    fund: dict[str, Any],
    as_of_date: str,
    source: str,
    source_url: str | None = None,
    is_official: bool = False,
    status: str = "SUCCESS",
    error_message: str | None = None,
) -> FundMetadataSnapshot:
    """Insert or return an idempotent, source-traceable fund identity snapshot."""
    fund_obj = _instrument(
        session,
        {"symbol": f"FUND:{fund['fund_code']}", "local_code": fund["fund_code"], "name": fund.get("fund_name")},
        "fund",
    )
    existing = session.scalar(
        select(FundMetadataSnapshot).where(
            FundMetadataSnapshot.fund_instrument_id == fund_obj.id,
            FundMetadataSnapshot.as_of_date == as_of_date,
            FundMetadataSnapshot.source == source,
        )
    )
    if existing is not None:
        return existing
    snapshot = FundMetadataSnapshot(
        fund_instrument_id=fund_obj.id,
        as_of_date=as_of_date,
        source=source,
        source_url=source_url,
        fetched_at=_now(),
        is_official=is_official,
        status=status,
        payload_json=json.dumps(fund, ensure_ascii=False, sort_keys=True),
        error_message=error_message,
    )
    session.add(snapshot)
    session.flush()
    return snapshot


def save_universe_snapshot(
    session: Session,
    *,
    universe: dict[str, Any],
    constituents: Iterable[dict[str, Any]],
    as_of_date: str,
    source: str,
    source_url: str | None = None,
    status: str = "SUCCESS",
    error_message: str | None = None,
) -> UniverseSnapshot:
    """Persist one immutable constituent/weight snapshot and its source."""
    universe_obj = session.scalar(select(Universe).where(Universe.code == universe["code"]))
    if universe_obj is None:
        universe_obj = Universe(
            code=universe["code"],
            name=universe.get("name", universe["code"]),
            description=universe.get("description"),
            universe_type=universe.get("universe_type", "index_constituents"),
            as_of_date=as_of_date,
            metadata_json=json.dumps(universe.get("metadata", {}), ensure_ascii=False, sort_keys=True),
        )
        session.add(universe_obj)
        session.flush()
    snapshot = session.scalar(
        select(UniverseSnapshot).where(
            UniverseSnapshot.universe_id == universe_obj.id,
            UniverseSnapshot.as_of_date == as_of_date,
            UniverseSnapshot.source == source,
        )
    )
    if snapshot is not None:
        return snapshot
    items = list(constituents)
    snapshot = UniverseSnapshot(
        universe_id=universe_obj.id,
        as_of_date=as_of_date,
        source=source,
        source_url=source_url,
        fetched_at=_now(),
        status=status,
        payload_json=json.dumps({"universe": universe, "constituent_count": len(items)}, ensure_ascii=False, sort_keys=True),
        error_message=error_message,
    )
    session.add(snapshot)
    session.flush()
    for item in items:
        instrument = _instrument(session, item, item.get("instrument_type", "stock"))
        session.add(
            UniverseConstituentWeight(
                snapshot_id=snapshot.id,
                instrument_id=instrument.id,
                rank=item.get("rank"),
                weight_pct=item.get("weight_pct"),
                source=source,
            )
        )
    session.flush()
    return snapshot


def ingest_seed_identity_snapshot(seed: dict[str, Any], *, as_of_date: str, engine=None) -> dict[str, int]:
    """Store the existing public seed as a non-official baseline.

    The seed is explicitly marked non-official.  It is a reproducible fallback
    and does not claim to be the current index constituent list.
    """
    engine = init_db(engine)
    target = next((item for item in seed.get("funds", []) if str(item.get("fund_code")) == "020671"), None)
    if target is None:
        raise ValueError("fund 020671 is not present in the supplied seed")
    source = str(seed.get("provider", "manual_public_fund_disclosure"))
    with Session(engine) as session:
        save_fund_metadata_snapshot(
            session,
            fund=target,
            as_of_date=as_of_date,
            source=source,
            is_official=False,
            status="FALLBACK_SEED",
        )
        session.commit()
    return {"fund_metadata_snapshots": 1}


def ingest_official_identity_snapshot(identity: Any, *, engine=None) -> dict[str, int]:
    """Persist an identity returned by an official provider."""
    engine = init_db(engine)
    payload = identity.to_dict() if hasattr(identity, "to_dict") else dict(identity)
    as_of_date = payload.get("nav_date") or payload.get("fund_size_as_of")
    if not as_of_date:
        raise ValueError("official identity has no usable as_of_date")
    fund = dict(payload)
    with Session(engine) as session:
        save_fund_metadata_snapshot(
            session,
            fund=fund,
            as_of_date=str(as_of_date),
            source=str(payload.get("source", "official")),
            source_url=payload.get("source_url"),
            is_official=bool(payload.get("is_official", True)),
            status="SUCCESS",
        )
        session.commit()
    return {"fund_metadata_snapshots": 1}


def ingest_official_nav_history(observations: Iterable[Any], *, engine=None) -> dict[str, int]:
    """Persist official NAV rows idempotently; never overwrite an existing date."""
    engine = init_db(engine)
    rows = list(observations)
    if not rows:
        raise ValueError("official NAV history is empty")
    code = str(rows[0].fund_code)
    with Session(engine) as session:
        fund = session.scalar(
            select(Instrument).where(
                Instrument.local_code == code, Instrument.instrument_type == "fund"
            )
        )
        if fund is None:
            raise ValueError(f"fund instrument not found: {code}")
        inserted = 0
        for observation in rows:
            existing = session.scalar(
                select(FundNavObservation).where(
                    FundNavObservation.fund_instrument_id == fund.id,
                    FundNavObservation.nav_date == observation.nav_date,
                    FundNavObservation.source == observation.source,
                )
            )
            if existing is not None:
                continue
            payload = observation.to_dict() if hasattr(observation, "to_dict") else dict(observation)
            fetched_at = datetime.fromisoformat(
                str(payload["fetched_at"]).replace("Z", "+00:00")
            ).astimezone(timezone.utc).replace(tzinfo=None)
            session.add(
                FundNavObservation(
                    fund_instrument_id=fund.id,
                    nav_date=observation.nav_date,
                    unit_nav=observation.unit_nav,
                    cumulative_nav=observation.cumulative_nav,
                    daily_change_pct=observation.daily_change_pct,
                    source=observation.source,
                    source_url=observation.source_url,
                    fetched_at=fetched_at,
                    available_at=datetime.combine(
                        datetime.fromisoformat(observation.nav_date).date(), datetime.min.time()
                    ),
                    status=observation.status,
                    payload_json=json.dumps(payload, ensure_ascii=False, sort_keys=True),
                )
            )
            inserted += 1
        session.commit()
    return {"fund_nav_observations_inserted": inserted, "fund_nav_observations_received": len(rows)}


def ingest_etf_status_snapshot(snapshot: Any, *, engine=None) -> dict[str, int]:
    engine = init_db(engine)
    payload = snapshot.to_dict() if hasattr(snapshot, "to_dict") else dict(snapshot)
    with Session(engine) as session:
        instrument = session.scalar(
            select(Instrument).where(Instrument.local_code == str(snapshot.etf_code))
        )
        if instrument is None:
            instrument = _instrument(
                session,
                {
                    "symbol": f"{snapshot.etf_code}.SS",
                    "local_code": snapshot.etf_code,
                    "name": snapshot.etf_name,
                    "exchange": "SSE",
                    "currency": "CNY",
                },
                "etf",
            )
        fetched_at = datetime.fromisoformat(str(snapshot.fetched_at).replace("Z", "+00:00")).astimezone(timezone.utc).replace(tzinfo=None)
        observed_at = (
            datetime.fromisoformat(str(snapshot.observed_at)).astimezone(timezone.utc).replace(tzinfo=None)
            if snapshot.observed_at
            else fetched_at
        )
        existing = session.scalar(
            select(EtfStatusObservation).where(
                EtfStatusObservation.etf_instrument_id == instrument.id,
                EtfStatusObservation.observed_at == observed_at,
                EtfStatusObservation.source == snapshot.source,
            )
        )
        if existing is not None:
            return {"etf_status_observations_inserted": 0, "snapshot_id": existing.id}
        row = EtfStatusObservation(
            etf_instrument_id=instrument.id,
            observed_date=snapshot.observed_date,
            observed_at=observed_at,
            nav_date=snapshot.nav_date,
            unit_nav=snapshot.unit_nav,
            market_price=snapshot.market_price,
            iopv=snapshot.iopv,
            discount_rate_pct=snapshot.discount_rate_pct,
            shares=snapshot.shares,
            amount=snapshot.amount,
            circulating_market_cap=snapshot.circulating_market_cap,
            total_market_cap=snapshot.total_market_cap,
            source=snapshot.source,
            fetched_at=fetched_at,
            status=snapshot.status,
            payload_json=json.dumps(payload, ensure_ascii=False, sort_keys=True),
        )
        session.add(row)
        session.flush()
        snapshot_id = row.id
        session.commit()
    return {"etf_status_observations_inserted": 1, "snapshot_id": snapshot_id}


def ingest_official_index_snapshot(snapshot: Any, *, engine=None) -> dict[str, int]:
    """Persist an official index snapshot without overstating its coverage."""
    engine = init_db(engine)
    status = "SUCCESS" if snapshot.is_complete else "PARTIAL_OFFICIAL_TOP10"
    universe = {
        "code": f"INDEX:{snapshot.index_code}",
        "name": snapshot.index_name,
        "universe_type": "index_constituents",
        "metadata": {
            "index_code": snapshot.index_code,
            "coverage": snapshot.coverage,
            "expected_constituent_count": snapshot.expected_constituent_count,
            "received_constituent_count": len(snapshot.constituents),
            "membership_trade_date": snapshot.membership_trade_date,
            "weight_lag_days": snapshot.weight_lag_days,
        },
    }
    with Session(engine) as session:
        saved = save_universe_snapshot(
            session,
            universe=universe,
            constituents=snapshot.constituents,
            as_of_date=snapshot.trade_date,
            source=snapshot.source,
            source_url=snapshot.source_url,
            status=status,
            error_message=None if snapshot.is_complete else "CSI public endpoint exposes top 10 only",
        )
        snapshot_id = saved.id
        session.commit()
    return {
        "universe_snapshots": 1,
        "universe_constituent_weights": len(snapshot.constituents),
        "snapshot_id": snapshot_id,
    }


def ingest_index_snapshot_failure(
    *,
    index_code: str,
    index_name: str,
    as_of_date: str,
    error_message: str,
    engine=None,
) -> dict[str, int]:
    """Persist an observable provider failure without blocking a later success."""
    engine = init_db(engine)
    with Session(engine) as session:
        saved = save_universe_snapshot(
            session,
            universe={"code": f"INDEX:{index_code}", "name": index_name},
            constituents=[],
            as_of_date=as_of_date,
            source="csindex_official_failure",
            source_url=f"https://www.csindex.com.cn/#/indices/family/detail?indexCode={index_code}",
            status="FAILED",
            error_message=error_message,
        )
        snapshot_id = saved.id
        session.commit()
    return {"failed_universe_snapshots": 1, "failed_snapshot_id": snapshot_id}
