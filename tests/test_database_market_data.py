from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

import tradingagents.dataflows.config as dataflow_config
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.storage.data_service import (
    MARKET_DATA_UNAVAILABLE,
    PROVIDER_ERROR,
    SUCCESS,
    MarketDataService,
    is_final_daily_bar,
)
from tradingagents.storage.db import get_engine, init_db
from tradingagents.storage.models import Instrument, MarketBarObservation


def _frame(start="2024-01-02", rows=60):
    index = pd.bdate_range(start, periods=rows)
    close = pd.Series(range(100, 100 + rows), index=index, dtype=float)
    return pd.DataFrame(
        {
            "Open": close - 1,
            "High": close + 1,
            "Low": close - 2,
            "Close": close,
            "Adj Close": close,
            "Volume": 1000.0,
            "Dividends": 0.0,
            "Stock Splits": 0.0,
        },
        index=index,
    )


def _seed(engine, symbol="688981.SS", frame=None, unfinished_last=False):
    frame = _frame() if frame is None else frame
    with Session(engine) as session:
        instrument = Instrument(
            symbol=symbol,
            local_code=symbol.split(".")[0],
            name=symbol,
            instrument_type="stock",
            exchange="SS",
            currency="CNY",
            timezone="Asia/Shanghai",
        )
        session.add(instrument)
        session.flush()
        now = datetime(2024, 1, 1)
        for number, (idx, row) in enumerate(frame.iterrows()):
            session.add(
                MarketBarObservation(
                    instrument_id=instrument.id,
                    interval="1d",
                    bar_time=idx.to_pydatetime(),
                    market_date=idx.date().isoformat(),
                    open=float(row.Open),
                    high=float(row.High),
                    low=float(row.Low),
                    close=float(row.Close),
                    adjusted_close=float(row["Adj Close"]),
                    volume=float(row.Volume),
                    is_final=not (unfinished_last and number == len(frame) - 1),
                    provider="test",
                    upstream_group="test",
                    available_at=now,
                    fetched_at=now,
                    payload_hash=f"seed-{number}",
                    run_id="test",
                )
            )
        session.commit()


@pytest.fixture
def engine():
    return init_db(get_engine("sqlite://"))


def test_database_only_returns_cached_data_and_never_calls_provider(engine):
    _seed(engine)
    calls = []
    with Session(engine) as session:
        result = MarketDataService(
            session, "database_only", lambda *_: calls.append(1)
        ).daily("688981.SS", "2024-01-01", "2024-03-31")
    assert result.status == SUCCESS
    assert result.source == "database"
    assert result.provider_call_count == 0
    assert len(result.data) == 60
    assert calls == []


def test_database_only_reports_missing_data(engine):
    with Session(engine) as session:
        result = MarketDataService(session, "database_only").daily(
            "MISSING.SS", "2024-01-01", "2024-01-31"
        )
    assert result.status == MARKET_DATA_UNAVAILABLE
    assert result.provider_call_count == 0
    assert result.data.empty


def test_database_first_persists_then_second_call_uses_cache(engine):
    calls = []

    def provider(*_):
        calls.append(1)
        return _frame(rows=20)

    with Session(engine) as session:
        first = MarketDataService(session, "database_first", provider).daily(
            "688981.SS", "2024-01-01", "2024-01-31"
        )
        second = MarketDataService(session, "database_first", provider).daily(
            "688981.SS", "2024-01-01", "2024-01-31"
        )
    assert first.status == SUCCESS
    assert first.source == "database"
    assert first.refreshed is True
    assert first.provider_call_count == 1
    assert second.status == SUCCESS
    assert second.source == "database"
    assert second.provider_call_count == 0
    assert calls == [1]


def test_database_first_uses_cached_data(engine):
    _seed(engine)
    with Session(engine) as session:
        result = MarketDataService(
            session, "database_first", lambda *_: pytest.fail("provider called")
        ).daily("688981.SS", "2024-01-01", "2024-03-31")
    assert result.status == SUCCESS
    assert result.provider_call_count == 0


def test_provider_only_persistence_behavior_and_explicit_failure(engine):
    with Session(engine) as session:
        direct = MarketDataService(
            session, "provider_only", lambda *_: _frame(rows=5)
        ).daily("688981.SS", "2024-01-01", "2024-01-08")
        failed = MarketDataService(
            session,
            "provider_only",
            lambda *_: (_ for _ in ()).throw(ConnectionError("offline")),
        ).daily("688981.SS", "2024-01-01", "2024-01-31")
    assert direct.status == SUCCESS
    assert direct.source == "provider"
    assert direct.provider_call_count == 1
    assert failed.status == PROVIDER_ERROR
    assert "ConnectionError" in failed.message


def test_provider_only_can_persist_then_reread(engine):
    with Session(engine) as session:
        result = MarketDataService(
            session,
            "provider_only",
            lambda *_: _frame(rows=5),
            persist_provider_results=True,
        ).daily("688981.SS", "2024-01-01", "2024-01-08")
    assert result.status == SUCCESS
    assert result.source == "database"
    assert result.refreshed is True
    assert result.provider_call_count == 1
    assert len(result.data) == 5


def test_persistence_keeps_provider_provenance(engine):
    def eastmoney_provider(*_):
        frame = _frame(rows=5)
        frame.attrs["market_source"] = "akshare_eastmoney"
        frame.attrs["upstream_group"] = "eastmoney"
        return frame

    with Session(engine) as session:
        result = MarketDataService(
            session,
            "provider_only",
            eastmoney_provider,
            persist_provider_results=True,
        ).daily("688981.SS", "2024-01-01", "2024-01-08")
        stored = session.scalars(select(MarketBarObservation)).all()
    assert result.status == SUCCESS
    assert result.provider_name == "akshare_eastmoney"
    assert {row.provider for row in stored} == {"akshare_eastmoney"}


def test_explicit_sync_can_require_historical_range_coverage(engine):
    _seed(engine, frame=_frame(start="2024-01-15", rows=10))
    calls = []
    with Session(engine) as session:
        result = MarketDataService(
            session,
            "database_first",
            lambda *_: (calls.append(1) or _frame(start="2024-01-02", rows=22)),
            require_requested_start=True,
        ).daily("688981.SS", "2024-01-02", "2024-01-31")
    assert result.status == SUCCESS
    assert calls == [1]


def test_strict_end_coverage_refreshes_a_stale_tail_inside_holiday_grace(engine):
    _seed(engine, frame=_frame(start="2024-01-02", rows=10))
    calls = []
    with Session(engine) as session:
        result = MarketDataService(
            session,
            "database_first",
            lambda *_: (calls.append(1) or _frame(start="2024-01-02", rows=22)),
            strict_requested_end=True,
        ).daily("688981.SS", "2024-01-02", "2024-01-31")

    assert result.status == SUCCESS
    assert calls == [1]


def test_turnover_requirement_refreshes_price_only_cache(engine):
    price_only = _frame(start="2024-01-02", rows=22)
    _seed(engine, frame=price_only)
    calls = []
    provider_frame = _frame(start="2024-01-02", rows=22)
    provider_frame["Amount"] = provider_frame["Close"] * provider_frame["Volume"] * 100
    with Session(engine) as session:
        result = MarketDataService(
            session,
            "database_first",
            lambda *_: (calls.append(1) or provider_frame),
            strict_requested_end=True,
            require_turnover_amount=True,
        ).daily("688981.SS", "2024-01-02", "2024-01-31")

    assert result.status == SUCCESS
    assert calls == [1]
    assert result.data["Amount"].notna().all()


def test_daily_repository_prefers_complete_amount_when_providers_use_different_bar_times(engine):
    price_only = _frame(start="2024-01-02", rows=22)
    _seed(engine, frame=price_only)
    amount_frame = _frame(start="2024-01-02", rows=22)
    amount_frame["Amount"] = amount_frame["Close"] * amount_frame["Volume"] * 100
    with Session(engine) as session:
        result = MarketDataService(
            session,
            "database_first",
            lambda *_: amount_frame,
            strict_requested_end=True,
            require_turnover_amount=True,
        ).daily("688981.SS", "2024-01-02", "2024-01-31")

    assert result.status == SUCCESS
    assert len(result.data) == 22
    assert result.data["Amount"].notna().all()


def test_late_listing_is_usable_after_minimum_history(engine):
    source = _frame(start="2024-01-15", rows=10)
    _seed(engine, frame=source)
    with Session(engine) as session:
        result = MarketDataService(
            session,
            "database_only",
            require_requested_start=True,
            minimum_rows_if_start_missing=10,
        ).daily("688981.SS", "2024-01-02", "2024-01-31")
    assert result.status == SUCCESS
    assert result.provider_call_count == 0


def test_same_day_daily_bar_becomes_final_after_shanghai_cutoff():
    day = date(2026, 7, 22)
    timezone = ZoneInfo("Asia/Shanghai")
    assert not is_final_daily_bar(day, now=datetime(2026, 7, 22, 15, 59, tzinfo=timezone))
    assert is_final_daily_bar(day, now=datetime(2026, 7, 22, 16, 0, tzinfo=timezone))
    assert not is_final_daily_bar(date(2026, 7, 23), now=datetime(2026, 7, 22, 20, 0, tzinfo=timezone))


def test_repository_prefers_complete_amount_row_over_later_incomplete_row(engine):
    source = _frame(rows=5)
    _seed(engine, frame=source)
    latest_date = source.index[-1]
    with Session(engine) as session:
        instrument = session.scalar(select(Instrument).where(Instrument.symbol == "688981.SS"))
        session.add(
            MarketBarObservation(
                instrument_id=instrument.id,
                interval="1d",
                bar_time=latest_date.to_pydatetime(),
                market_date=latest_date.date().isoformat(),
                open=1.0,
                high=2.0,
                low=0.5,
                close=1.5,
                volume=100.0,
                amount=150.0,
                is_final=True,
                provider="akshare_eastmoney",
                upstream_group="eastmoney",
                available_at=datetime(2023, 1, 1),
                fetched_at=datetime(2023, 1, 1),
                payload_hash="complete-amount-row",
                run_id="test",
            )
        )
        session.commit()
        result = MarketDataService(session, "database_only").daily(
            "688981.SS", "2024-01-02", "2024-01-08"
        )
    assert result.data.loc[latest_date, "Amount"] == 150.0
    assert result.data.loc[latest_date, "Close"] == 1.5


def test_repository_excludes_future_and_unfinished_daily(engine):
    _seed(engine, frame=_frame(rows=5), unfinished_last=True)
    with Session(engine) as session:
        result = MarketDataService(session, "database_only").daily(
            "688981.SS", "2024-01-02", "2024-01-05"
        )
    assert result.data.index.max() == pd.Timestamp("2024-01-05")
    assert pd.Timestamp("2024-01-08") not in result.data.index


def test_get_stock_data_uses_database_and_keeps_csv_format(tmp_path, monkeypatch):
    db_path = tmp_path / "market.db"
    monkeypatch.setenv("TRADINGAGENTS_DATABASE_URL", f"sqlite:///{db_path.as_posix()}")
    local_engine = init_db(get_engine())
    _seed(local_engine, frame=_frame(rows=5), unfinished_last=True)
    monkeypatch.setattr(dataflow_config, "_config", deepcopy(DEFAULT_CONFIG))

    from tradingagents.dataflows.y_finance import get_database_stock_data

    monkeypatch.setattr(
        "tradingagents.dataflows.y_finance._get_yfinance_daily_frame",
        lambda *_: pytest.fail("Yahoo must not be called in database_only mode"),
    )

    output = get_database_stock_data("688981.SS", "2024-01-02", "2024-01-08")
    assert output.startswith("# Stock data for 688981.SS")
    assert "# Total records: 4" in output
    assert "\n2024-01-08," not in output
    assert "Open,High,Low,Close" in output


def test_indicator_reads_database_respects_date_and_matches_stockstats(
    tmp_path, monkeypatch
):
    db_path = tmp_path / "market.db"
    monkeypatch.setenv("TRADINGAGENTS_DATABASE_URL", f"sqlite:///{db_path.as_posix()}")
    local_engine = init_db(get_engine())
    source = _frame(rows=60)
    _seed(local_engine, frame=source)
    monkeypatch.setattr(dataflow_config, "_config", deepcopy(DEFAULT_CONFIG))

    from stockstats import wrap
    from tradingagents.dataflows.stockstats_utils import StockstatsUtils, load_ohlcv

    cutoff = source.index[39].strftime("%Y-%m-%d")
    loaded = load_ohlcv("688981.SS", cutoff)
    actual = StockstatsUtils.get_stock_stats("688981.SS", "close_20_sma", cutoff)
    expected_frame = wrap(source.iloc[:40].reset_index().rename(columns={"index": "Date"}))
    expected_frame["close_20_sma"]
    assert loaded["Date"].max() == pd.Timestamp(cutoff)
    assert actual == pytest.approx(expected_frame["close_20_sma"].iloc[-1])


def test_indicator_uses_previous_trading_day_and_reports_insufficient_history(
    tmp_path, monkeypatch
):
    db_path = tmp_path / "market.db"
    monkeypatch.setenv("TRADINGAGENTS_DATABASE_URL", f"sqlite:///{db_path.as_posix()}")
    local_engine = init_db(get_engine())
    source = _frame(rows=10)
    _seed(local_engine, frame=source)
    monkeypatch.setattr(dataflow_config, "_config", deepcopy(DEFAULT_CONFIG))

    from tradingagents.dataflows.stockstats_utils import StockstatsUtils

    weekend = (source.index[-1] + pd.Timedelta(days=2)).strftime("%Y-%m-%d")
    value = StockstatsUtils.get_stock_stats("688981.SS", "close_5_sma", weekend)
    insufficient = StockstatsUtils.get_stock_stats(
        "688981.SS", "close_20_sma", weekend
    )
    assert isinstance(value, (int, float))
    assert str(insufficient).startswith("INSUFFICIENT_HISTORY")
    assert "available_rows=10" in insufficient
