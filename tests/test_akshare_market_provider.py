from __future__ import annotations

import sys
from types import SimpleNamespace

import pandas as pd

from tradingagents.extensions.sector_fund.akshare_market_provider import (
    get_akshare_eastmoney_daily_frame,
    get_akshare_sina_daily_frame,
    get_auto_daily_frame,
)


def _raw():
    return pd.DataFrame(
        {
            "date": ["2026-07-21", "2026-07-22"],
            "open": [10, 11],
            "high": [12, 13],
            "low": [9, 10],
            "close": [11, 12],
            "volume": [100, 200],
            "amount": [1000, 2400],
        }
    )


def test_stock_provider_uses_explicit_amount(monkeypatch):
    calls = []

    def stock(**kwargs):
        calls.append(kwargs)
        return _raw()

    monkeypatch.setitem(sys.modules, "akshare", SimpleNamespace(stock_zh_a_daily=stock))
    result = get_akshare_sina_daily_frame("688981.SS", "2026-07-01", "2026-07-22")
    assert calls == [
        {
            "symbol": "sh688981",
            "start_date": "20260701",
            "end_date": "20260722",
            "adjust": "",
        }
    ]
    assert result["Amount"].tolist() == [1000, 2400]
    assert result["Volume"].tolist() == [100, 200]


def test_target_etf_provider_filters_requested_dates(monkeypatch):
    raw = pd.concat(
        [
            pd.DataFrame({column: [value] for column, value in _raw().iloc[0].items()}),
            _raw(),
        ],
        ignore_index=True,
    )
    raw.loc[0, "date"] = "2026-06-30"
    monkeypatch.setitem(
        sys.modules,
        "akshare",
        SimpleNamespace(fund_etf_hist_sina=lambda **kwargs: raw),
    )
    result = get_akshare_sina_daily_frame("589130.SS", "2026-07-01", "2026-07-21")
    assert list(result.index.strftime("%Y-%m-%d")) == ["2026-07-21"]
    assert result.iloc[0]["Amount"] == 1000


def test_eastmoney_provider_uses_raw_daily_bars(monkeypatch):
    raw = pd.DataFrame(
        {
            "日期": ["2026-07-21", "2026-07-22"],
            "开盘": [10, 11], "最高": [12, 13], "最低": [9, 10],
            "收盘": [11, 12], "成交量": [100, 200], "成交额": [1000, 2400],
        }
    )
    calls = []

    def stock(**kwargs):
        calls.append(kwargs)
        return raw

    monkeypatch.setitem(sys.modules, "akshare", SimpleNamespace(stock_zh_a_hist=stock))
    result = get_akshare_eastmoney_daily_frame("688981.SS", "2026-07-01", "2026-07-22")
    assert calls == [{"symbol": "688981", "period": "daily", "start_date": "20260701", "end_date": "20260722", "adjust": ""}]
    assert result.attrs["market_source"] == "akshare_eastmoney"
    assert result.attrs["price_adjustment"] == "raw"
    assert result["Amount"].tolist() == [1000, 2400]


def test_auto_provider_falls_back_without_splicing(monkeypatch):
    calls = []

    def failed(*_args, **_kwargs):
        calls.append("eastmoney")
        raise ConnectionError("offline")

    def sina(*_args, **_kwargs):
        calls.append("sina")
        result = pd.DataFrame(
            {
                "Open": [10.0], "High": [11.0], "Low": [9.0], "Close": [10.5],
                "Volume": [100.0], "Amount": [105000.0],
            },
            index=pd.DatetimeIndex(["2026-07-22"]),
        )
        result.attrs["market_source"] = "akshare_sina"
        result.attrs["upstream_group"] = "sina"
        return result

    monkeypatch.setattr(
        "tradingagents.extensions.sector_fund.akshare_market_provider.get_akshare_eastmoney_daily_frame",
        failed,
    )
    monkeypatch.setattr(
        "tradingagents.extensions.sector_fund.akshare_market_provider.get_akshare_sina_daily_frame",
        sina,
    )
    result = get_auto_daily_frame("688981.SS", "2026-07-01", "2026-07-22", retries=1)
    assert calls == ["eastmoney", "sina"]
    assert result.attrs["market_source"] == "akshare_sina"
    assert len(result) == 1
