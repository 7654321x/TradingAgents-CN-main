from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from tradingagents.extensions.sector_fund.event_provider import fetch_efunds_events
from tradingagents.extensions.sector_fund.event_store import (
    load_recent_fund_events,
    sync_fund_events,
)
from tradingagents.storage.db import init_db
from tradingagents.storage.models import FundEvent, Instrument

HTML = """
<html><body>
<a href="https://cdn.efunds.com.cn/owch/data/bulletin/20260721/q2.pdf">基金2026年第2季度报告</a>
<a href="https://cdn.efunds.com.cn/owch/data/bulletin/20260721/q2.pdf">基金2026年第2季度报告</a>
<a href="https://cdn.efunds.com.cn/owch/data/bulletin/20260519/info.pdf">基金产品资料概要更新</a>
</body></html>
"""


def test_official_event_provider_extracts_dates_types_and_deduplicates(monkeypatch):
    monkeypatch.setattr(
        "tradingagents.extensions.sector_fund.event_provider.requests.get",
        lambda *args, **kwargs: SimpleNamespace(
            text=HTML, encoding="", raise_for_status=lambda: None
        ),
    )
    events = fetch_efunds_events("020671")
    assert len(events) == 2
    assert events[0].event_date == "2026-07-21"
    assert events[0].event_type == "PERIODIC_REPORT"
    assert events[0].available_at.endswith("23:59:59")
    assert events[0].source_level == "OFFICIAL_FUND_MANAGER"


def _engine():
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
    return engine


def test_event_sync_persists_history_and_skips_repeated_provider_calls(monkeypatch):
    monkeypatch.setattr(
        "tradingagents.extensions.sector_fund.event_provider.requests.get",
        lambda *args, **kwargs: SimpleNamespace(
            text=HTML, encoding="", raise_for_status=lambda: None
        ),
    )
    calls = []

    def provider(*args, **kwargs):
        calls.append(kwargs)
        return fetch_efunds_events(*args, **kwargs)

    engine = _engine()
    now = datetime(2026, 7, 22, 12, tzinfo=timezone.utc)
    first = sync_fund_events("020671", engine=engine, provider=provider, now=now)
    second = sync_fund_events("020671", engine=engine, provider=provider, now=now)
    assert first["inserted"] == 2
    assert second["status"] == "SKIPPED_RECENTLY_SYNCED"
    assert second["provider_call_count"] == 0
    assert len(calls) == 1
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(FundEvent)) == 2
        recent = load_recent_fund_events(session, "020671", "2026-07-22")
        assert len(recent) == 1
        assert recent[0].event_date == "2026-07-21"


def test_forced_resync_uses_dedup_and_does_not_duplicate_history(monkeypatch):
    monkeypatch.setattr(
        "tradingagents.extensions.sector_fund.event_provider.requests.get",
        lambda *args, **kwargs: SimpleNamespace(
            text=HTML, encoding="", raise_for_status=lambda: None
        ),
    )
    engine = _engine()
    sync_fund_events("020671", engine=engine)
    result = sync_fund_events("020671", engine=engine, force=True)
    assert result["inserted"] == 0
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(FundEvent)) == 2


def test_as_of_event_scan_is_bounded_and_bypasses_incremental_skip(monkeypatch):
    monkeypatch.setattr(
        "tradingagents.extensions.sector_fund.event_provider.requests.get",
        lambda *args, **kwargs: SimpleNamespace(
            text=HTML, encoding="", raise_for_status=lambda: None
        ),
    )
    calls = []

    def provider(*args, **kwargs):
        calls.append(kwargs)
        return fetch_efunds_events(*args, **kwargs)

    engine = _engine()
    now = datetime(2026, 7, 23, 12, tzinfo=timezone.utc)
    result = sync_fund_events(
        "020671",
        engine=engine,
        provider=provider,
        now=now,
        scanned_through_date="2026-07-22",
        lookback_days=7,
    )

    assert result["status"] == "SUCCESS"
    assert result["scanned_through_date"] == "2026-07-22"
    assert calls[0]["since_exclusive"] == "2026-07-15"
