from __future__ import annotations

import sys
from types import SimpleNamespace

import pandas as pd
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from tradingagents.extensions.sector_fund.baseline import ingest_etf_status_snapshot
from tradingagents.extensions.sector_fund.etf_status_provider import fetch_etf_status
from tradingagents.storage.db import init_db
from tradingagents.storage.models import EtfStatusObservation, Instrument


def _install_fake_akshare(monkeypatch):
    daily = pd.DataFrame(
        {
            "基金代码": ["589130"],
            "基金简称": ["科创芯片ETF易方达"],
            "2026-07-22-单位净值": [1.5516],
            "2026-07-21-单位净值": [1.5849],
        }
    )
    spot = pd.DataFrame(
        {
            "代码": ["589130"],
            "名称": ["科创芯片ETF易方达"],
            "最新价": [1.546],
            "IOPV实时估值": [1.551],
            "基金折价率": [0.32],
            "最新份额": [3020780000.0],
            "成交额": [400524143.0],
            "流通市值": [4670125880.0],
            "总市值": [4670125880.0],
            "数据日期": ["2026-07-22"],
            "更新时间": ["2026-07-22 16:11:36+08:00"],
        }
    )
    monkeypatch.setitem(
        sys.modules,
        "akshare",
        SimpleNamespace(
            fund_etf_fund_daily_em=lambda: daily,
            fund_etf_spot_em=lambda: spot,
        ),
    )


def test_etf_status_merges_akshare_nav_and_spot_fields(monkeypatch):
    _install_fake_akshare(monkeypatch)
    result = fetch_etf_status("589130")
    assert result.observed_date == "2026-07-22"
    assert result.nav_date == "2026-07-22"
    assert result.unit_nav == 1.5516
    assert result.market_price == 1.546
    assert result.iopv == 1.551
    assert result.discount_rate_pct == 0.32
    assert result.shares == 3020780000.0


def test_etf_status_snapshot_is_idempotent(monkeypatch):
    _install_fake_akshare(monkeypatch)
    engine = init_db(create_engine("sqlite+pysqlite:///:memory:"))
    snapshot = fetch_etf_status("589130")
    first = ingest_etf_status_snapshot(snapshot, engine=engine)
    second = ingest_etf_status_snapshot(snapshot, engine=engine)
    assert first["etf_status_observations_inserted"] == 1
    assert second["etf_status_observations_inserted"] == 0
    with Session(engine) as session:
        row = session.scalar(select(EtfStatusObservation))
        instrument = session.get(Instrument, row.etf_instrument_id)
        assert instrument.symbol == "589130.SS"
        assert row.shares == 3020780000.0
