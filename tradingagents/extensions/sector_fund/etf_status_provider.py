"""ETF status snapshot from AkShare's available aggregate/spot endpoints."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class EtfStatusSnapshot:
    etf_code: str
    etf_name: str
    observed_date: str
    observed_at: str | None
    nav_date: str | None
    unit_nav: float | None
    market_price: float | None
    iopv: float | None
    discount_rate_pct: float | None
    shares: float | None
    amount: float | None
    circulating_market_cap: float | None
    total_market_cap: float | None
    source: str
    fetched_at: str
    status: str = "SUCCESS"

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def _number(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, str):
        value = value.strip().rstrip("%")
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def fetch_etf_status(etf_code: str) -> EtfStatusSnapshot:
    import akshare as ak

    code = str(etf_code).strip().zfill(6)
    if len(code) != 6 or not code.isdigit():
        raise ValueError(f"invalid ETF code: {etf_code}")
    daily = ak.fund_etf_fund_daily_em()
    spot = ak.fund_etf_spot_em()
    daily_rows = daily.loc[daily["基金代码"].astype(str).str.zfill(6) == code]
    spot_rows = spot.loc[spot["代码"].astype(str).str.zfill(6) == code]
    if len(daily_rows) != 1 or len(spot_rows) != 1:
        raise ValueError(
            f"ETF exact match count mismatch for {code}: daily={len(daily_rows)}, spot={len(spot_rows)}"
        )
    daily_row = daily_rows.iloc[0]
    spot_row = spot_rows.iloc[0]
    date_columns = sorted(
        [column for column in daily.columns if str(column).endswith("-单位净值")], reverse=True
    )
    nav_column = date_columns[0] if date_columns else None
    nav_date = str(nav_column).split("-单位净值")[0] if nav_column else None
    observed_date = pd.Timestamp(spot_row["数据日期"]).date().isoformat()
    observed_at = pd.Timestamp(spot_row["更新时间"]).isoformat() if pd.notna(spot_row["更新时间"]) else None
    return EtfStatusSnapshot(
        etf_code=code,
        etf_name=str(spot_row["名称"]),
        observed_date=observed_date,
        observed_at=observed_at,
        nav_date=nav_date,
        unit_nav=_number(daily_row[nav_column]) if nav_column else None,
        market_price=_number(spot_row["最新价"]),
        iopv=_number(spot_row["IOPV实时估值"]),
        discount_rate_pct=_number(spot_row["基金折价率"]),
        shares=_number(spot_row["最新份额"]),
        amount=_number(spot_row["成交额"]),
        circulating_market_cap=_number(spot_row["流通市值"]),
        total_market_cap=_number(spot_row["总市值"]),
        source="akshare_eastmoney_aggregate_spot",
        fetched_at=datetime.now(timezone.utc).isoformat(),
    )
