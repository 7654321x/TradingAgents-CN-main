from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, timezone

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from .market import clean_ticker_frame
from .models import Instrument, MarketBarObservation
from .repository import MarketBarRepository


SUCCESS = "SUCCESS"
MARKET_DATA_UNAVAILABLE = "MARKET_DATA_UNAVAILABLE"
DATABASE_RANGE_INCOMPLETE = "DATABASE_RANGE_INCOMPLETE"
PROVIDER_ERROR = "PROVIDER_ERROR"


@dataclass
class MarketDataResult:
    symbol: str
    interval: str
    data: pd.DataFrame
    source: str
    status: str
    refreshed: bool
    provider_call_count: int
    requested_start: date | datetime | str
    requested_end: date | datetime | str
    first_bar: date | datetime | None
    latest_bar: date | datetime | None
    message: str | None = None


class MarketDataService:
    """Small orchestration layer for daily bars.

    A provider callback must return an OHLCV DataFrame indexed by market date.
    Provider data is always cleaned before it is returned or persisted.
    """

    MODES = {"database_only", "database_first", "provider_only"}

    def __init__(
        self,
        session: Session,
        mode: str = "database_only",
        provider=None,
        *,
        include_unfinished_daily_bar: bool = False,
        persist_provider_results: bool = False,
    ):
        if mode not in self.MODES:
            raise ValueError(f"Unsupported market data mode: {mode}")
        self.session = session
        self.repo = MarketBarRepository(session)
        self.mode = mode
        self.provider = provider
        self.include_unfinished_daily_bar = include_unfinished_daily_bar
        self.persist_provider_results = persist_provider_results

    def _result(
        self,
        symbol,
        start,
        end,
        frame,
        *,
        source,
        status,
        refreshed=False,
        provider_call_count=0,
        message=None,
    ) -> MarketDataResult:
        first = frame.index[0].date() if not frame.empty else None
        latest = frame.index[-1].date() if not frame.empty else None
        return MarketDataResult(
            symbol=symbol,
            interval="1d",
            data=frame,
            source=source,
            status=status,
            refreshed=refreshed,
            provider_call_count=provider_call_count,
            requested_start=start,
            requested_end=end,
            first_bar=first,
            latest_bar=latest,
            message=message,
        )

    def _database_frame(self, symbol, start, end) -> pd.DataFrame:
        return self.repo.get_latest_daily_bars(
            symbol,
            start,
            end,
            include_unfinished=self.include_unfinished_daily_bar,
        )

    @staticmethod
    def _covers_requested_end(frame: pd.DataFrame, end) -> bool:
        """Detect an obviously stale tail without pretending to be a calendar.

        Ten calendar days accommodates weekends and long exchange holidays.
        The start boundary is intentionally not enforced because an instrument
        may have listed after the requested start date.
        """
        if frame.empty:
            return False
        return frame.index[-1].normalize() >= pd.Timestamp(end).normalize() - pd.Timedelta(days=10)

    @staticmethod
    def _clean_provider_frame(frame: pd.DataFrame, start, end) -> pd.DataFrame:
        if frame is None or frame.empty:
            return pd.DataFrame()
        data = frame.copy()
        if "Date" in data.columns:
            data = data.set_index("Date")
        data.index = pd.to_datetime(data.index, errors="coerce")
        data = data.loc[~data.index.isna()]
        if data.index.tz is not None:
            data.index = data.index.tz_localize(None)
        data, _ = clean_ticker_frame(data, "1d")
        start_ts = pd.Timestamp(start).normalize()
        end_ts = pd.Timestamp(end).normalize()
        return data.loc[(data.index.normalize() >= start_ts) & (data.index.normalize() <= end_ts)].sort_index()

    def _persist_daily(self, symbol: str, frame: pd.DataFrame) -> None:
        instrument = self.session.scalar(select(Instrument).where(Instrument.symbol == symbol))
        if instrument is None:
            suffix = "SS" if symbol.endswith(".SS") else "SZ" if symbol.endswith(".SZ") else None
            instrument = Instrument(
                symbol=symbol,
                local_code=symbol.rsplit(".", 1)[0],
                name=symbol,
                instrument_type="stock",
                exchange=suffix,
                currency="CNY" if suffix else None,
                timezone="Asia/Shanghai" if suffix else None,
            )
            self.session.add(instrument)
            self.session.flush()

        fetched_at = datetime.now(timezone.utc).replace(tzinfo=None)
        today = datetime.now().date()
        for idx, row in frame.iterrows():
            market_date = pd.Timestamp(idx).date()
            payload = {
                key: None if pd.isna(value) else str(value)
                for key, value in row.items()
            }
            payload_hash = hashlib.sha256(
                json.dumps(payload, sort_keys=True).encode("utf-8")
            ).hexdigest()
            bar_time = datetime.combine(market_date, datetime.min.time())
            exists = self.session.scalar(
                select(MarketBarObservation.id).where(
                    MarketBarObservation.instrument_id == instrument.id,
                    MarketBarObservation.interval == "1d",
                    MarketBarObservation.market_date == market_date.isoformat(),
                    MarketBarObservation.provider == "yfinance",
                    MarketBarObservation.payload_hash == payload_hash,
                )
            )
            if exists:
                continue

            def number(column):
                value = row.get(column)
                return float(value) if value is not None and pd.notna(value) else None

            self.session.add(
                MarketBarObservation(
                    instrument_id=instrument.id,
                    interval="1d",
                    bar_time=bar_time,
                    market_date=market_date.isoformat(),
                    open=number("Open"),
                    high=number("High"),
                    low=number("Low"),
                    close=number("Close"),
                    adjusted_close=number("Adj Close"),
                    volume=number("Volume"),
                    dividends=number("Dividends"),
                    stock_splits=number("Stock Splits"),
                    capital_gains=number("Capital Gains"),
                    is_final=market_date < today,
                    provider="yfinance",
                    upstream_group="yahoo_finance",
                    source_event_time=bar_time,
                    available_at=fetched_at,
                    fetched_at=fetched_at,
                    payload_hash=payload_hash,
                    run_id="market-data-service",
                )
            )
        self.session.commit()

    def _call_provider(self, symbol, start, end):
        if self.provider is None:
            raise RuntimeError("No market data provider configured")
        return self._clean_provider_frame(self.provider(symbol, start, end), start, end)

    def daily(self, symbol, start, end) -> MarketDataResult:
        if self.mode != "provider_only":
            cached = self._database_frame(symbol, start, end)
            if self._covers_requested_end(cached, end):
                return self._result(
                    symbol, start, end, cached, source="database", status=SUCCESS
                )
            if self.mode == "database_only":
                status = (
                    MARKET_DATA_UNAVAILABLE if cached.empty else DATABASE_RANGE_INCOMPLETE
                )
                return self._result(
                    symbol,
                    start,
                    end,
                    cached,
                    source="database",
                    status=status,
                    message=(
                        "No final daily bars found in the database"
                        if cached.empty
                        else "Latest final daily bar is clearly before the requested end"
                    ),
                )

        try:
            provider_frame = self._call_provider(symbol, start, end)
        except Exception as exc:
            return self._result(
                symbol,
                start,
                end,
                pd.DataFrame(),
                source="provider",
                status=PROVIDER_ERROR,
                provider_call_count=1,
                message=f"{type(exc).__name__}: {exc}",
            )

        if provider_frame.empty:
            return self._result(
                symbol,
                start,
                end,
                provider_frame,
                source="provider",
                status=MARKET_DATA_UNAVAILABLE,
                provider_call_count=1,
                message="Provider returned no valid daily bars",
            )

        should_persist = self.mode == "database_first" or self.persist_provider_results
        if not should_persist:
            return self._result(
                symbol,
                start,
                end,
                provider_frame,
                source="provider",
                status=SUCCESS,
                provider_call_count=1,
            )

        try:
            self._persist_daily(symbol, provider_frame)
            persisted = self._database_frame(symbol, start, end)
        except Exception as exc:
            self.session.rollback()
            return self._result(
                symbol,
                start,
                end,
                pd.DataFrame(),
                source="database",
                status=PROVIDER_ERROR,
                refreshed=True,
                provider_call_count=1,
                message=f"Persistence failed: {type(exc).__name__}: {exc}",
            )

        if not self._covers_requested_end(persisted, end):
            return self._result(
                symbol,
                start,
                end,
                persisted,
                source="database",
                status=DATABASE_RANGE_INCOMPLETE,
                refreshed=True,
                provider_call_count=1,
                message="Provider data was persisted but no final daily bars were readable",
            )
        return self._result(
            symbol,
            start,
            end,
            persisted,
            source="database",
            status=SUCCESS,
            refreshed=True,
            provider_call_count=1,
        )
