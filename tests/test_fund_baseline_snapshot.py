from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tradingagents.extensions.sector_fund import load_fund_holdings_seed
from tradingagents.extensions.sector_fund.baseline import (
    ingest_seed_identity_snapshot,
    save_universe_snapshot,
)
from tradingagents.storage.db import get_engine, init_db
from tradingagents.storage.models import (
    FundMetadataSnapshot,
    UniverseConstituentWeight,
    UniverseSnapshot,
)


def test_seed_baseline_is_idempotent_and_explicitly_fallback():
    engine = init_db(get_engine("sqlite:///:memory:"))
    seed = load_fund_holdings_seed()

    assert ingest_seed_identity_snapshot(seed, as_of_date="2026-07-22", engine=engine) == {
        "fund_metadata_snapshots": 1
    }
    assert ingest_seed_identity_snapshot(seed, as_of_date="2026-07-22", engine=engine) == {
        "fund_metadata_snapshots": 1
    }

    with Session(engine) as session:
        snapshot = session.scalar(select(FundMetadataSnapshot))
        assert snapshot is not None
        assert snapshot.status == "FALLBACK_SEED"
        assert snapshot.is_official is False
        assert snapshot.source == "manual_public_fund_disclosure"
        assert session.scalar(select(func.count()).select_from(FundMetadataSnapshot)) == 1


def test_universe_snapshot_keeps_weight_history_and_is_idempotent():
    engine = init_db(get_engine("sqlite:///:memory:"))
    with Session(engine) as session:
        first = save_universe_snapshot(
            session,
            universe={"code": "INDEX:TEST", "name": "Test Index"},
            constituents=[
                {"symbol": "688001.SS", "name": "A", "rank": 1, "weight_pct": 12.5},
                {"symbol": "688002.SS", "name": "B", "rank": 2, "weight_pct": 8.0},
            ],
            as_of_date="2026-07-22",
            source="test_provider",
        )
        session.commit()
        second = save_universe_snapshot(
            session,
            universe={"code": "INDEX:TEST", "name": "Test Index"},
            constituents=[
                {"symbol": "688001.SS", "name": "A", "rank": 1, "weight_pct": 99.0},
            ],
            as_of_date="2026-07-22",
            source="test_provider",
        )
        session.commit()
        assert first.id == second.id
        assert session.scalar(select(func.count()).select_from(UniverseSnapshot)) == 1
        assert session.scalar(select(func.count()).select_from(UniverseConstituentWeight)) == 2
