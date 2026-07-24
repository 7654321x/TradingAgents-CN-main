from __future__ import annotations

from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from tradingagents.extensions.sector_fund.fund_context import load_fund_context
from tradingagents.storage.db import init_db
from tradingagents.storage.models import (
    EtfStatusObservation,
    FundEvent,
    FundNavObservation,
    Instrument,
)


def test_fund_context_reads_database_only():
    engine = init_db(create_engine("sqlite+pysqlite:///:memory:"))
    with Session(engine) as session:
        fund = Instrument(symbol="FUND:020671", local_code="020671", name="fund", instrument_type="fund")
        etf = Instrument(symbol="589130.SS", local_code="589130", name="etf", instrument_type="etf")
        session.add_all([fund, etf])
        session.flush()
        for day, nav in (("2026-07-21", 3.9), ("2026-07-22", 4.0)):
            session.add(
                FundNavObservation(
                    fund_instrument_id=fund.id,
                    nav_date=day,
                    unit_nav=nav,
                    cumulative_nav=nav,
                    daily_change_pct=1,
                    source="efunds_official",
                    fetched_at=datetime(2026, 7, 22),
                    available_at=datetime(2026, 7, 22),
                    status="SUCCESS",
                )
            )
        session.add(
            EtfStatusObservation(
                etf_instrument_id=etf.id,
                observed_date="2026-07-22",
                observed_at=datetime(2026, 7, 22, 8),
                nav_date="2026-07-22",
                unit_nav=1.55,
                market_price=1.54,
                shares=100,
                source="akshare",
                fetched_at=datetime(2026, 7, 22),
                status="SUCCESS",
            )
        )
        session.add(
            EtfStatusObservation(
                etf_instrument_id=etf.id,
                observed_date="2026-07-21",
                observed_at=datetime(2026, 7, 21, 8),
                nav_date="2026-07-21",
                unit_nav=1.50,
                market_price=1.49,
                shares=80,
                source="akshare",
                fetched_at=datetime(2026, 7, 21),
                status="SUCCESS",
            )
        )
        session.add(
            FundEvent(
                fund_instrument_id=fund.id,
                event_date="2026-07-21",
                available_at=datetime(2026, 7, 21, 23, 59, 59),
                title="季度报告",
                url="https://example.test/q2.pdf",
                source="efunds_official",
                source_level="OFFICIAL_FUND_MANAGER",
                event_type="PERIODIC_REPORT",
                confirmation_status="CONFIRMED",
                already_reflected_status="UNKNOWN",
                content_hash="a" * 64,
                dedup_key="b" * 64,
                fetched_at=datetime(2026, 7, 22),
            )
        )
        session.commit()
        context = load_fund_context(
            session,
            fund_code="020671",
            etf_code="589130",
            analysis_date="2026-07-22",
            market_date="2026-07-22",
        )
    assert context["load_mode"] == "DATABASE_ONLY"
    assert context["network_call_count"] == 0
    assert context["official_nav"]["unit_nav"] == 4.0
    assert context["etf_status"]["shares"] == 100
    assert context["etf_status"]["shares_change_pct"] == 25.0
    assert len(context["recent_events_7d"]) == 1
    assert context["recent_events_7d"][0]["market_reflection_status"] == "MARKET_PERIOD_AFTER_EVENT_EXISTS"


def test_fund_context_does_not_calculate_share_change_from_same_day_snapshots():
    engine = init_db(create_engine("sqlite+pysqlite:///:memory:"))
    with Session(engine) as session:
        fund = Instrument(symbol="FUND:020671", local_code="020671", name="fund", instrument_type="fund")
        etf = Instrument(symbol="589130.SS", local_code="589130", name="etf", instrument_type="etf")
        session.add_all([fund, etf])
        session.flush()
        for hour, shares in ((9, 100), (14, 120)):
            session.add(
                EtfStatusObservation(
                    etf_instrument_id=etf.id,
                    observed_date="2026-07-22",
                    observed_at=datetime(2026, 7, 22, hour),
                    nav_date="2026-07-21",
                    unit_nav=1.5,
                    market_price=1.5,
                    shares=shares,
                    source="akshare",
                    fetched_at=datetime(2026, 7, 22, hour),
                    status="SUCCESS",
                )
            )
        session.commit()
        context = load_fund_context(
            session,
            fund_code="020671",
            etf_code="589130",
            analysis_date="2026-07-22",
            market_date="2026-07-22",
        )

    assert context["etf_status"]["shares"] == 120
    assert context["etf_status"]["shares_change_pct"] is None
    assert context["etf_status"]["shares_change_status"] == "INSUFFICIENT_HISTORY"
