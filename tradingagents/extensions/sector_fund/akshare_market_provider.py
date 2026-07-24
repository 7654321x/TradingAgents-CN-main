"""A-share daily-bar providers with deterministic source fallback.

The sector-fund pipeline uses raw (unadjusted) OHLCV only.  Network providers
are used by the explicit sync command; reports and backtests read the database.
"""
from __future__ import annotations

import time
from datetime import timedelta

import pandas as pd

ETF_CODES = {"589130"}
REQUIRED_OHLCV = ("Open", "High", "Low", "Close", "Volume")
SOURCE_ORDER = ("eastmoney", "sina", "yfinance")


def _sina_symbol(symbol: str) -> tuple[str, str]:
    value = str(symbol).strip().upper()
    if value.endswith(".SS"):
        return value[:-3], f"sh{value[:-3]}"
    if value.endswith(".SZ"):
        return value[:-3], f"sz{value[:-3]}"
    raise ValueError(f"unsupported A-share symbol: {symbol}")


def _local_code(symbol: str) -> str:
    value = str(symbol).strip().upper()
    if value.endswith((".SS", ".SZ", ".BJ")):
        return value.rsplit(".", 1)[0]
    raise ValueError(f"unsupported A-share symbol: {symbol}")


def _normalise_frame(raw: pd.DataFrame, rename: dict[str, str], start: str, end: str) -> pd.DataFrame:
    if raw is None or raw.empty:
        return pd.DataFrame()
    missing = set(rename) - set(raw.columns)
    if missing:
        raise ValueError(f"market response missing fields: {sorted(missing)}")
    columns = list(rename.values())
    frame = raw.rename(columns=rename)[columns].copy()
    frame["Date"] = pd.to_datetime(frame["Date"], errors="coerce")
    frame = frame.dropna(subset=["Date"]).set_index("Date").sort_index()
    for column in columns:
        if column != "Date":
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.loc[(frame.index >= pd.Timestamp(start)) & (frame.index <= pd.Timestamp(end))]
    return validate_raw_daily_frame(frame)


def validate_raw_daily_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Validate raw bars without silently repairing a provider response."""
    if frame is None or frame.empty:
        return pd.DataFrame()
    missing = [column for column in REQUIRED_OHLCV if column not in frame.columns]
    if missing:
        raise ValueError(f"daily frame missing OHLCV columns: {missing}")
    data = frame.copy().sort_index()
    if data.index.has_duplicates:
        raise ValueError("daily frame contains duplicate dates")
    if data[list(REQUIRED_OHLCV)].isna().any().any():
        raise ValueError("daily frame contains null OHLCV values")
    if (data["Volume"] < 0).any():
        raise ValueError("daily frame contains negative volume")
    if ((data["Low"] > data[["Open", "Close"]].min(axis=1)) | (data["High"] < data[["Open", "Close"]].max(axis=1))).any():
        raise ValueError("daily frame contains invalid OHLC relationships")
    return data


def _mark_source(frame: pd.DataFrame, source: str) -> pd.DataFrame:
    frame.attrs["market_source"] = source
    frame.attrs["upstream_group"] = source
    frame.attrs["price_adjustment"] = "raw"
    return frame


def get_akshare_eastmoney_daily_frame(symbol: str, start: str, end: str) -> pd.DataFrame:
    """Return raw daily bars from AkShare's Eastmoney adapters."""
    import akshare as ak

    code = _local_code(symbol)
    start_date = pd.Timestamp(start).strftime("%Y%m%d")
    end_date = pd.Timestamp(end).strftime("%Y%m%d")
    if code in ETF_CODES:
        raw = ak.fund_etf_hist_em(
            symbol=code,
            period="daily",
            start_date=start_date,
            end_date=end_date,
            adjust="",
        )
    else:
        raw = ak.stock_zh_a_hist(
            symbol=code,
            period="daily",
            start_date=start_date,
            end_date=end_date,
            adjust="",
        )
    return _mark_source(
        _normalise_frame(
            raw,
            {
                "日期": "Date", "开盘": "Open", "最高": "High", "最低": "Low",
                "收盘": "Close", "成交量": "Volume", "成交额": "Amount",
            },
            start,
            end,
        ),
        "akshare_eastmoney",
    )


def get_yfinance_raw_daily_frame(symbol: str, start: str, end: str) -> pd.DataFrame:
    """Return Yahoo raw bars with auto-adjustment explicitly disabled."""
    import yfinance as yf

    end_inclusive = (pd.Timestamp(end) + timedelta(days=1)).strftime("%Y-%m-%d")
    raw = yf.Ticker(symbol).history(
        start=pd.Timestamp(start).strftime("%Y-%m-%d"),
        end=end_inclusive,
        auto_adjust=False,
        actions=False,
        timeout=20,
    )
    if raw is None or raw.empty:
        return pd.DataFrame()
    if raw.index.tz is not None:
        raw = raw.copy()
        raw.index = raw.index.tz_localize(None)
    raw = raw.reset_index().rename(columns={raw.index.name or "index": "Date"})
    if "Date" not in raw.columns:
        raw = raw.rename(columns={raw.columns[0]: "Date"})
    return _mark_source(
        _normalise_frame(
            raw,
            {
                "Date": "Date", "Open": "Open", "High": "High", "Low": "Low",
                "Close": "Close", "Volume": "Volume",
            },
            start,
            end,
        ),
        "yfinance",
    )


def get_akshare_sina_daily_frame(symbol: str, start: str, end: str) -> pd.DataFrame:
    """Return raw OHLC plus exchange volume/amount from Sina.

    Sina's ETF and stock endpoints both expose an explicit amount field.  No
    close*volume approximation is performed.
    """
    import akshare as ak

    local_code, sina_symbol = _sina_symbol(symbol)
    start_date = pd.Timestamp(start).strftime("%Y%m%d")
    end_date = pd.Timestamp(end).strftime("%Y%m%d")
    if local_code in ETF_CODES:
        raw = ak.fund_etf_hist_sina(symbol=sina_symbol)
        if raw is not None and not raw.empty:
            dates = pd.to_datetime(raw["date"], errors="coerce")
            raw = raw.loc[(dates >= pd.Timestamp(start)) & (dates <= pd.Timestamp(end))].copy()
    else:
        raw = ak.stock_zh_a_daily(
            symbol=sina_symbol,
            start_date=start_date,
            end_date=end_date,
            adjust="",
        )
    return _mark_source(
        _normalise_frame(
            raw,
            {
                "date": "Date", "open": "Open", "high": "High", "low": "Low",
                "close": "Close", "volume": "Volume", "amount": "Amount",
            },
            start,
            end,
        ),
        "akshare_sina",
    )


def get_auto_daily_frame(symbol: str, start: str, end: str, *, retries: int = 2) -> pd.DataFrame:
    """Fetch one complete raw frame using the approved fallback order.

    A successful frame is never date-spliced with another provider.  Attempt
    details are retained in DataFrame attrs for persistence/audit output.
    """
    providers = (
        ("eastmoney", get_akshare_eastmoney_daily_frame),
        ("sina", get_akshare_sina_daily_frame),
        ("yfinance", get_yfinance_raw_daily_frame),
    )
    failures: list[str] = []
    for name, provider in providers:
        for attempt in range(1, retries + 1):
            try:
                frame = provider(symbol, start, end)
                if frame.empty:
                    raise ValueError("provider returned no usable rows")
                # The sector-fund report treats amount as an independent
                # market field.  Yahoo does not provide a reliable A-share
                # turnover amount, so a price-only frame must not be accepted
                # as a complete historical source.
                if "Amount" not in frame.columns or frame["Amount"].isna().any():
                    raise ValueError("provider returned no complete turnover amount")
                frame.attrs["market_attempts"] = failures.copy()
                return frame
            except Exception as exc:
                failures.append(f"{name}#{attempt}:{type(exc).__name__}:{exc}")
                if attempt < retries:
                    time.sleep(0.2 * attempt)
    raise RuntimeError("all market providers failed: " + " | ".join(failures))
