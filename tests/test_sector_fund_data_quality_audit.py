from __future__ import annotations

import json

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from tradingagents.extensions.sector_fund.data_observation_store import save_observation
from tradingagents.extensions.sector_fund.data_quality_audit import audit_sector_fund_data
from tradingagents.extensions.sector_fund.mcp_observation_store import save_mcp_observation
from tradingagents.storage.db import init_db
from tradingagents.storage.models import FundDataObservation, Instrument, McpWebObservation


def test_quality_audit_flags_unit_errors_and_mixed_derived_dates_without_deleting_raw_data():
    engine = init_db(create_engine("sqlite+pysqlite:///:memory:"))
    with Session(engine) as session:
        session.add(Instrument(symbol="589130.SS", local_code="589130", name="ETF", instrument_type="etf"))
        session.flush()
        save_mcp_observation(
            session,
            dataset_type="current_daily_market",
            field_name="daily_bar",
            payload={
                "bar": {
                    "Date": "2026-07-23",
                    "Open": 100,
                    "High": 101,
                    "Low": 99,
                    "Close": 100,
                    "Volume": 1_000_000,
                    "Amount": 100,
                }
            },
            source_level="B",
            source="mcp",
            source_url="https://example.test",
            confirmation_status="VERIFIED_WEB_SOURCE",
            applicable_date="2026-07-23",
            instrument_symbol="589130.SS",
        )
        save_observation(
            session,
            dataset_type="market_structure",
            field_name="breadth_extensions",
            value={"latest_market_dates": ["2026-07-17", "2026-07-23"]},
            source_level="B",
            source="derived",
            source_url=None,
            confirmation_status="DERIVED",
            applicable_date="2026-07-23",
        )
        session.commit()

        preview = audit_sector_fund_data(
            session, fund_code="020671", analysis_date="2026-07-23", apply=False
        )
        assert preview.invalid_mcp_ids
        assert preview.invalid_derived_ids
        assert session.scalar(select(McpWebObservation.status)) == "SUCCESS"

        applied = audit_sector_fund_data(
            session, fund_code="020671", analysis_date="2026-07-23", apply=True
        )
        assert applied.applied
        assert session.scalar(select(McpWebObservation.status)) == "INVALIDATED"
        assert session.scalar(select(FundDataObservation.status)) == "INVALIDATED"

        payload = session.scalar(select(McpWebObservation.payload_json))
        assert json.loads(payload)["bar"]["Amount"] == 100
