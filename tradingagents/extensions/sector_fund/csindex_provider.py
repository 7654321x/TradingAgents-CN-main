"""Official CSI index metadata and published top-weight constituents."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
from typing import Any

import pandas as pd
import requests

BASE_URL = "https://www.csindex.com.cn/csindex-home"
MATERIAL_BASE_URL = "https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/file/autofile"


@dataclass(frozen=True)
class CSIIndexSnapshot:
    index_code: str
    index_name: str
    trade_date: str
    membership_trade_date: str
    weight_lag_days: int
    expected_constituent_count: int
    constituents: tuple[dict[str, Any], ...]
    coverage: str
    source_url: str
    fetched_at: str
    source: str = "csindex_official"

    @property
    def is_complete(self) -> bool:
        return len(self.constituents) == self.expected_constituent_count


def _get_json(session: requests.Session, path: str, *, timeout: float) -> dict[str, Any]:
    url = f"{BASE_URL}{path}"
    response = session.get(url, headers={"User-Agent": "TradingAgents/1.0"}, timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    if payload.get("code") != "200" or not payload.get("success"):
        raise ValueError(f"CSI endpoint failed for {path}: {payload.get('msg')}")
    if not isinstance(payload.get("data"), dict):
        raise ValueError(f"CSI endpoint returned no data for {path}")
    return payload["data"]


def _get_excel(session: requests.Session, url: str, *, timeout: float) -> pd.DataFrame:
    response = session.get(url, headers={"User-Agent": "TradingAgents/1.0"}, timeout=timeout)
    response.raise_for_status()
    frame = pd.read_excel(BytesIO(response.content))
    if frame.empty:
        raise ValueError(f"CSI material is empty: {url}")
    return frame


def fetch_csindex_snapshot(
    index_code: str,
    *,
    timeout: float = 20.0,
    session: requests.Session | None = None,
) -> CSIIndexSnapshot:
    """Fetch verified identity and the official full closing-weight workbook."""
    code = str(index_code).strip()
    if len(code) != 6 or not code.isdigit():
        raise ValueError(f"invalid CSI index code: {index_code}")
    http = session or requests.Session()
    basic = _get_json(http, f"/indexInfo/index-basic-info/{code}", timeout=timeout)
    feature = _get_json(http, f"/indexInfo/index-feature/{code}", timeout=timeout)
    if str(basic.get("indexCode")) != code or str(feature.get("indexCode")) != code:
        raise ValueError(f"CSI response identity mismatch for {code}")
    weights_url = f"{MATERIAL_BASE_URL}/closeweight/{code}closeweight.xls"
    frame = _get_excel(http, weights_url, timeout=timeout)
    required = {
        "日期Date",
        "指数代码 Index Code",
        "成份券代码Constituent Code",
        "成份券名称Constituent Name",
        "权重(%)weight",
    }
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"CSI closing-weight workbook missing columns: {sorted(missing)}")
    workbook_codes = {str(value).zfill(6) for value in frame["指数代码 Index Code"].tolist()}
    if workbook_codes != {code}:
        raise ValueError(f"CSI workbook identity mismatch: {sorted(workbook_codes)}")
    if frame["成份券代码Constituent Code"].duplicated().any():
        raise ValueError("CSI workbook contains duplicate constituent codes")
    rows = frame.to_dict("records")
    constituents = tuple(
        {
            "symbol": f"{str(row['成份券代码Constituent Code']).zfill(6)}.SS",
            "local_code": str(row["成份券代码Constituent Code"]).zfill(6),
            "name": row.get("成份券名称Constituent Name"),
            "exchange": "SSE",
            "currency": "CNY",
            "instrument_type": "stock",
            "rank": rank,
            "weight_pct": float(row["权重(%)weight"]),
        }
        for rank, row in enumerate(
            sorted(rows, key=lambda item: float(item["权重(%)weight"]), reverse=True), start=1
        )
    )
    expected = int(float(feature["consNum"]))
    raw_dates = {str(value) for value in frame["日期Date"].tolist()}
    if len(raw_dates) != 1:
        raise ValueError(f"CSI workbook contains mixed dates: {sorted(raw_dates)}")
    trade_date = raw_dates.pop()
    if len(trade_date) == 8 and trade_date.isdigit():
        trade_date = f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]}"
    membership_trade_date = str(feature["tradeDate"])
    if len(membership_trade_date) == 8 and membership_trade_date.isdigit():
        membership_trade_date = (
            f"{membership_trade_date[:4]}-{membership_trade_date[4:6]}-{membership_trade_date[6:]}"
        )
    weight_lag_days = (
        pd.Timestamp(membership_trade_date) - pd.Timestamp(trade_date)
    ).days
    if weight_lag_days < 0:
        raise ValueError("CSI weight workbook date is newer than membership feature date")
    weight_sum = sum(item["weight_pct"] for item in constituents)
    if len(constituents) != expected:
        raise ValueError(f"CSI constituent count mismatch: expected {expected}, received {len(constituents)}")
    if not 99.0 <= weight_sum <= 101.0:
        raise ValueError(f"CSI constituent weights sum to {weight_sum:.4f}, expected about 100")
    return CSIIndexSnapshot(
        index_code=code,
        index_name=str(basic["indexFullNameCn"]),
        trade_date=trade_date,
        membership_trade_date=membership_trade_date,
        weight_lag_days=weight_lag_days,
        expected_constituent_count=expected,
        constituents=constituents,
        coverage="FULL",
        source_url=weights_url,
        fetched_at=datetime.now(timezone.utc).isoformat(),
    )
