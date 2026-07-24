"""Persist and load point-in-time industry and supply-chain classifications."""
from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from tradingagents.storage.db import init_db
from tradingagents.storage.models import Instrument, InstrumentClassificationSnapshot

CSI_SCHEME = "CSI_CICS_V1"
CHAIN_SCHEME = "SEMICONDUCTOR_CHAIN_V1"


def _utc_naive(value: str | None = None) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00")) if value else datetime.now(timezone.utc)
    return parsed.astimezone(timezone.utc).replace(tzinfo=None)


def ingest_classification_snapshots(classifications: Iterable, *, engine=None) -> dict[str, int]:
    engine = init_db(engine)
    inserted = 0
    with Session(engine) as session:
        for classification in classifications:
            payload = classification.to_dict()
            instrument = session.scalar(
                select(Instrument).where(Instrument.local_code == classification.security_code)
            )
            if instrument is None:
                raise ValueError(f"instrument not found for classification: {classification.security_code}")
            rows = (
                (
                    CSI_SCHEME,
                    classification.source,
                    {
                        "level1": {"code": classification.cics1_code, "name": classification.cics1_name},
                        "level2": {"code": classification.cics2_code, "name": classification.cics2_name},
                        "level3": {"code": classification.cics3_code, "name": classification.cics3_name},
                        "level4": {"code": classification.cics4_code, "name": classification.cics4_name},
                    },
                ),
                (
                    CHAIN_SCHEME,
                    "derived_from_csindex_cics4",
                    {
                        "category": classification.supply_chain,
                        "rule_version": classification.supply_chain_rule,
                        "input_cics4_code": classification.cics4_code,
                        "input_cics4_name": classification.cics4_name,
                    },
                ),
            )
            for scheme, source, body in rows:
                existing = session.scalar(
                    select(InstrumentClassificationSnapshot).where(
                        InstrumentClassificationSnapshot.instrument_id == instrument.id,
                        InstrumentClassificationSnapshot.as_of_date == classification.as_of_date,
                        InstrumentClassificationSnapshot.scheme == scheme,
                        InstrumentClassificationSnapshot.source == source,
                    )
                )
                if existing is not None:
                    continue
                session.add(
                    InstrumentClassificationSnapshot(
                        instrument_id=instrument.id,
                        as_of_date=classification.as_of_date,
                        scheme=scheme,
                        source=source,
                        source_url=classification.source_url,
                        fetched_at=_utc_naive(payload.get("fetched_at")),
                        status=(
                            "SUCCESS"
                            if scheme == CSI_SCHEME or classification.supply_chain != "未分类"
                            else "PARTIAL"
                        ),
                        classification_json=json.dumps(body, ensure_ascii=False, sort_keys=True),
                    )
                )
                inserted += 1
        session.commit()
    return {"classification_snapshots_inserted": inserted}


def load_latest_classifications(
    session: Session, instrument_ids: Iterable[int], as_of_date: str
) -> dict[int, dict[str, object]]:
    ids = tuple(instrument_ids)
    if not ids:
        return {}
    rows = session.scalars(
        select(InstrumentClassificationSnapshot)
        .where(
            InstrumentClassificationSnapshot.instrument_id.in_(ids),
            InstrumentClassificationSnapshot.as_of_date <= as_of_date,
        )
        .order_by(
            InstrumentClassificationSnapshot.instrument_id,
            InstrumentClassificationSnapshot.scheme,
            InstrumentClassificationSnapshot.as_of_date.desc(),
            InstrumentClassificationSnapshot.id.desc(),
        )
    ).all()
    latest: dict[tuple[int, str], InstrumentClassificationSnapshot] = {}
    for row in rows:
        latest.setdefault((row.instrument_id, row.scheme), row)
    result: dict[int, dict[str, object]] = {}
    for (instrument_id, scheme), row in latest.items():
        result.setdefault(instrument_id, {})[scheme] = {
            "as_of_date": row.as_of_date,
            "source": row.source,
            "status": row.status,
            "value": json.loads(row.classification_json or "{}"),
        }
    return result
