from __future__ import annotations

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from tradingagents.extensions.sector_fund.baseline import ingest_official_nav_history
from tradingagents.extensions.sector_fund.efunds_provider import EFundsNavObservation
from tradingagents.storage.db import init_db
from tradingagents.storage.models import FundNavObservation, Instrument


def test_nav_history_is_idempotent_and_keeps_dates():
    engine = init_db(create_engine("sqlite+pysqlite:///:memory:"))
    with Session(engine) as session:
        session.add(
            Instrument(
                symbol="FUND:020671",
                local_code="020671",
                name="020671",
                instrument_type="fund",
            )
        )
        session.commit()
    rows = tuple(
        EFundsNavObservation(
            fund_code="020671",
            nav_date=date,
            unit_nav=unit,
            cumulative_nav=unit,
            daily_change_pct=change,
            source_url="https://www.efunds.com.cn/fund/020671.shtml",
            fetched_at="2026-07-22T12:00:00+00:00",
        )
        for date, unit, change in (("2026-07-22", 3.9167, -1.98), ("2026-07-21", 3.9959, 12.61))
    )
    assert ingest_official_nav_history(rows, engine=engine)["fund_nav_observations_inserted"] == 2
    assert ingest_official_nav_history(rows, engine=engine)["fund_nav_observations_inserted"] == 0
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(FundNavObservation)) == 2
        latest = session.scalar(
            select(FundNavObservation).order_by(FundNavObservation.nav_date.desc())
        )
        assert latest.unit_nav == 3.9167
        assert latest.status == "SUCCESS"
