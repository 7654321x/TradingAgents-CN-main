import logging
import os
import time
from typing import Annotated

import pandas as pd
import yfinance as yf
from stockstats import wrap
from yfinance.exceptions import YFRateLimitError

from .config import get_config
from .symbol_utils import NoMarketDataError, normalize_symbol
from .utils import safe_ticker_component

logger = logging.getLogger(__name__)

# A vendor's latest OHLCV row this many calendar days before the requested date
# is treated as stale. Generous enough to span long holiday weekends, tight
# enough to catch the year-old frames yfinance occasionally returns (#1021).
MAX_OHLCV_STALE_DAYS = 10


def yf_retry(func, max_retries=3, base_delay=2.0):
    """Execute a yfinance call with exponential backoff on rate limits.

    yfinance raises YFRateLimitError on HTTP 429 responses but does not
    retry them internally. This wrapper adds retry logic specifically
    for rate limits. Other exceptions propagate immediately.
    """
    for attempt in range(max_retries + 1):
        try:
            return func()
        except YFRateLimitError:
            if attempt < max_retries:
                delay = base_delay * (2 ** attempt)
                logger.warning(f"Yahoo Finance rate limited, retrying in {delay:.0f}s (attempt {attempt + 1}/{max_retries})")
                time.sleep(delay)
            else:
                raise


def _ensure_date_column(data: pd.DataFrame) -> pd.DataFrame:
    """Normalize the date column to ``Date``.

    Some yfinance builds leave the index unnamed (so ``reset_index()`` yields
    ``index``) or use ``Datetime`` for intraday data. Rename the first
    date-like column so indicators don't silently drop when it isn't ``Date``.
    """
    if "Date" in data.columns:
        return data
    for candidate in ("index", "Datetime", "date"):
        if candidate in data.columns:
            return data.rename(columns={candidate: "Date"})
    return data


def _clean_dataframe(data: pd.DataFrame) -> pd.DataFrame:
    """Normalize a stock DataFrame for stockstats: parse dates, drop invalid rows, fill price gaps."""
    data = _ensure_date_column(data)
    data["Date"] = pd.to_datetime(data["Date"], errors="coerce")
    data = data.dropna(subset=["Date"])

    price_cols = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in data.columns]
    data[price_cols] = data[price_cols].apply(pd.to_numeric, errors="coerce")
    data = data.dropna(subset=["Close"])
    data[price_cols] = data[price_cols].ffill().bfill()

    return data


def _coerce_ohlcv_dates(data: pd.DataFrame) -> pd.Series:
    """Return parsed dates from an OHLCV frame, whether Date is a column or the index."""
    if "Date" in data.columns:
        return pd.to_datetime(data["Date"], errors="coerce").dropna()
    # yfinance keeps the dates in the index (a DatetimeIndex, sometimes unnamed).
    if isinstance(data.index, pd.DatetimeIndex):
        return pd.Series(pd.to_datetime(data.index, errors="coerce")).dropna()
    # Fallback: expose the index and look for any date-like column.
    df = data.reset_index()
    for col in ("Date", "Datetime", "date", "index"):
        if col in df.columns:
            parsed = pd.to_datetime(df[col], errors="coerce").dropna()
            if not parsed.empty:
                return parsed
    return pd.Series(dtype="datetime64[ns]")


def _assert_ohlcv_not_stale(
    data: pd.DataFrame,
    curr_date: str,
    symbol: str,
    canonical: str | None = None,
    *,
    max_stale_days: int = MAX_OHLCV_STALE_DAYS,
) -> None:
    """Reject OHLCV whose latest row is far older than curr_date.

    Raises NoMarketDataError (with a stale-specific detail) so the router treats
    it like any other "no usable data from this vendor" — try the next vendor,
    then emit one clear unavailable signal. Empty frames are left to the
    caller's existing no-data handling; this guards only the dangerous case of
    present-but-stale rows (a vendor returning a year-old frame that would
    otherwise feed wrong prices to the agent, #1021).
    """
    if data is None or data.empty:
        return
    requested = pd.to_datetime(curr_date, errors="coerce")
    if pd.isna(requested):
        return
    requested = requested.normalize()
    dates = _coerce_ohlcv_dates(data)
    if dates.empty:
        return
    latest = dates.max().normalize()
    stale_days = (requested - latest).days
    if stale_days > max_stale_days:
        raise NoMarketDataError(
            symbol,
            canonical,
            f"latest row is {latest.date()}, {stale_days} days before the "
            f"requested {requested.date()} (stale) — refusing to use it",
        )


def load_ohlcv(symbol: str, curr_date: str) -> pd.DataFrame:
    """Fetch OHLCV data with caching, filtered to prevent look-ahead bias.

    Downloads 5 years of data up to today and caches per symbol. On
    subsequent calls the cache is reused. Rows after curr_date are
    filtered out so backtests never see future prices.
    """
    # Resolve broker/forex symbols (XAUUSD+ -> GC=F) to Yahoo's convention,
    # then reject values that would escape the cache directory when
    # interpolated into the cache filename (e.g. ``../../tmp/x``).
    canonical = normalize_symbol(symbol)
    safe_symbol = safe_ticker_component(canonical)

    config = get_config()
    curr_date_dt = pd.to_datetime(curr_date)

    market_config = config.get("market_data", {})
    mode = market_config.get("mode", "database_only")
    if mode != "provider_only":
        # Import lazily: y_finance imports this module for the existing
        # stockstats adapter, so importing its provider at module load would
        # introduce a cycle.
        from sqlalchemy.orm import Session

        from tradingagents.storage.data_service import MarketDataService, SUCCESS
        from tradingagents.storage.db import get_engine

        provider = None
        if mode == "database_first":
            from .y_finance import _get_yfinance_daily_frame

            provider = _get_yfinance_daily_frame
        start_for_indicators = (
            curr_date_dt - pd.DateOffset(years=5)
        ).strftime("%Y-%m-%d")
        with Session(get_engine()) as session:
            result = MarketDataService(
                session,
                mode=mode,
                provider=provider,
                include_unfinished_daily_bar=market_config.get(
                    "include_unfinished_daily_bar", False
                ),
                persist_provider_results=market_config.get(
                    "persist_provider_results", False
                ),
            ).daily(symbol, start_for_indicators, curr_date_dt.strftime("%Y-%m-%d"))
        if result.status == SUCCESS:
            data = result.data.reset_index().rename(columns={"index": "Date"})
            data = _clean_dataframe(data)
            return data[data["Date"] <= curr_date_dt]
        if mode == "database_only":
            canonical = normalize_symbol(symbol)
            raise NoMarketDataError(
                symbol,
                canonical,
                f"{result.status}: {result.message}; mode={mode}",
            )
        if result.status == "PROVIDER_ERROR":
            raise NoMarketDataError(symbol, normalize_symbol(symbol), result.message or result.status)

    # Cache uses a fixed window (5y to today) so one file per symbol.
    today_date = pd.Timestamp.today()
    start_date = today_date - pd.DateOffset(years=5)
    start_str = start_date.strftime("%Y-%m-%d")
    # yfinance ``end`` is EXCLUSIVE; request tomorrow so today's row is included
    # when curr_date is the current day (#986). Look-ahead is still prevented by
    # the curr_date filter below.
    end_str = (today_date + pd.Timedelta(days=1)).strftime("%Y-%m-%d")

    os.makedirs(config["data_cache_dir"], exist_ok=True)
    data_file = os.path.join(
        config["data_cache_dir"],
        f"{safe_symbol}-YFin-data-{start_str}-{end_str}.csv",
    )

    # A cached file may be empty if a prior fetch failed (unknown symbol,
    # transient rate limit). Treat an empty/columnless cache as a miss and
    # re-fetch rather than serving the poisoned file forever.
    data = None
    if os.path.exists(data_file):
        cached = pd.read_csv(data_file, on_bad_lines="skip", encoding="utf-8")
        if not cached.empty and "Close" in cached.columns:
            data = cached

    if data is None:
        downloaded = yf_retry(lambda: yf.download(
            canonical,
            start=start_str,
            end=end_str,
            multi_level_index=False,
            progress=False,
            auto_adjust=True,
        ))
        downloaded = _ensure_date_column(downloaded.reset_index())
        # Only cache real data — never persist an empty frame.
        if downloaded.empty or "Close" not in downloaded.columns:
            raise NoMarketDataError(
                symbol, canonical, "Yahoo Finance returned no rows"
            )
        downloaded.to_csv(data_file, index=False, encoding="utf-8")
        data = downloaded

    data = _clean_dataframe(data)

    # Filter to curr_date to prevent look-ahead bias in backtesting
    data = data[data["Date"] <= curr_date_dt]

    # Reject a stale frame (latest row far older than curr_date) rather than
    # feeding year-old prices into indicators (#1021).
    _assert_ohlcv_not_stale(data, curr_date, symbol, canonical)

    return data


def filter_financials_by_date(data: pd.DataFrame, curr_date: str) -> pd.DataFrame:
    """Drop financial statement columns (fiscal period timestamps) after curr_date.

    yfinance financial statements use fiscal period end dates as columns.
    Columns after curr_date represent future data and are removed to
    prevent look-ahead bias.
    """
    if not curr_date or data.empty:
        return data
    cutoff = pd.Timestamp(curr_date)
    mask = pd.to_datetime(data.columns, errors="coerce") <= cutoff
    return data.loc[:, mask]


class StockstatsUtils:
    @staticmethod
    def get_stock_stats(
        symbol: Annotated[str, "ticker symbol for the company"],
        indicator: Annotated[
            str, "quantitative indicators based off of the stock data for the company"
        ],
        curr_date: Annotated[
            str, "curr date for retrieving stock price data, YYYY-mm-dd"
        ],
    ):
        data = load_ohlcv(symbol, curr_date)
        required_rows = _required_indicator_rows(indicator)
        if len(data) < required_rows:
            first = data["Date"].iloc[0].strftime("%Y-%m-%d") if len(data) else None
            latest = data["Date"].iloc[-1].strftime("%Y-%m-%d") if len(data) else None
            return (
                f"INSUFFICIENT_HISTORY: indicator={indicator}, "
                f"required_rows={required_rows}, available_rows={len(data)}, "
                f"first_market_date={first}, latest_market_date={latest}"
            )
        df = wrap(data)
        df["Date"] = df["Date"].dt.strftime("%Y-%m-%d")
        curr_date_str = pd.to_datetime(curr_date).strftime("%Y-%m-%d")

        df[indicator]  # trigger stockstats to calculate the indicator
        matching_rows = df[df["Date"] <= curr_date_str].tail(1)

        if not matching_rows.empty:
            indicator_value = matching_rows[indicator].values[0]
            return indicator_value
        else:
            return "N/A: No trading day on or before requested date"


def _required_indicator_rows(indicator: str) -> int:
    """Conservative minimum history needed by the existing stockstats formulas."""
    if "_200_" in indicator:
        return 200
    if "_50_" in indicator:
        return 50
    if "_20_" in indicator or indicator.startswith("boll"):
        return 20
    if indicator.startswith("macd"):
        return 35
    if indicator.startswith(("rsi", "atr", "mfi")):
        return 14
    if "_10_" in indicator:
        return 10
    return 1
