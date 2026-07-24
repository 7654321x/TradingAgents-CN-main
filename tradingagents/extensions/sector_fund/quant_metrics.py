"""Deterministic ETF and full-index breadth/turnover metrics.

This layer calculates facts only.  It deliberately contains no score,
forecast probability, recommendation, or LLM call.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from tradingagents.extensions.sector_fund.classification import (
    CHAIN_SCHEME,
    CSI_SCHEME,
    load_latest_classifications,
)
from tradingagents.extensions.sector_fund.mcp_observation_store import load_current_daily_bar
from tradingagents.storage.data_service import SUCCESS, MarketDataService
from tradingagents.storage.models import (
    Instrument,
    Universe,
    UniverseConstituentWeight,
    UniverseSnapshot,
)

INSUFFICIENT_COVERAGE = "INSUFFICIENT_COVERAGE"
COMPLETE = "COMPLETE"


def _number(value: Any) -> float | None:
    if value is None or pd.isna(value) or not np.isfinite(float(value)):
        return None
    return float(value)


def _return(close: pd.Series, periods: int) -> float | None:
    values = close.dropna()
    if len(values) <= periods or values.iloc[-periods - 1] == 0:
        return None
    return float((values.iloc[-1] / values.iloc[-periods - 1] - 1.0) * 100.0)


def _latest(series: pd.Series) -> float | None:
    return _number(series.iloc[-1]) if len(series) else None


def _normalize(frame: pd.DataFrame, analysis_date: str) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()
    data = frame.copy()
    data.index = pd.to_datetime(data.index, errors="coerce")
    data = data.loc[~data.index.isna()]
    if data.index.tz is not None:
        data.index = data.index.tz_localize(None)
    data = data.loc[data.index.normalize() <= pd.Timestamp(analysis_date).normalize()]
    return data[~data.index.duplicated(keep="last")].sort_index()


@dataclass(frozen=True)
class ETFMetrics:
    symbol: str
    market_date: str
    row_count: int
    close: float
    sma5: float | None
    sma10: float | None
    sma20: float | None
    sma60: float | None
    rsi14: float | None
    macd: float | None
    macd_signal: float | None
    macd_histogram: float | None
    macd_histogram_change: float | None
    atr14: float | None
    atr_pct: float | None
    return_1d_pct: float | None
    return_3d_pct: float | None
    return_5d_pct: float | None
    return_10d_pct: float | None
    return_20d_pct: float | None
    drawdown_20d_pct: float | None
    amount: float | None
    amount_vs_5d_avg: float | None
    amount_vs_20d_avg: float | None
    price_vs_sma5_pct: float | None
    price_vs_sma10_pct: float | None
    price_vs_sma20_pct: float | None
    price_vs_sma60_pct: float | None


@dataclass(frozen=True)
class ConstituentContribution:
    symbol: str
    name: str
    weight_pct: float
    return_1d_pct: float | None
    weighted_contribution_pct: float | None
    amount: float | None
    direction: str
    csi_industry_level1: str
    csi_industry_level2: str
    csi_industry_level3: str
    csi_industry_level4: str
    supply_chain: str


@dataclass(frozen=True)
class ClassificationGroupMetrics:
    classification: str
    constituent_count: int
    price_available_count: int
    amount_available_count: int
    index_weight_pct: float
    total_amount_available: float | None
    advancers: int
    decliners: int
    unchanged: int
    equal_weight_return_pct: float | None
    index_weighted_contribution_pct: float | None


@dataclass(frozen=True)
class SectorMetrics:
    market_date: str
    expected_count: int
    price_available_count: int
    amount_available_count: int
    count_coverage_pct: float
    weight_coverage_pct: float
    amount_count_coverage_pct: float
    csi_classification_coverage_pct: float
    supply_chain_classification_coverage_pct: float
    status: str
    total_amount_available: float | None
    amount_vs_5d_avg: float | None
    amount_vs_20d_avg: float | None
    advancers: int
    decliners: int
    unchanged: int
    suspended_or_zero_volume: int
    advance_amount_pct: float | None
    decline_amount_pct: float | None
    equal_weight_return_pct: float | None
    index_weighted_return_pct: float | None
    top10_weighted_contribution_pct: float | None
    csi_level4_groups: tuple[ClassificationGroupMetrics, ...] = field(default_factory=tuple)
    supply_chain_groups: tuple[ClassificationGroupMetrics, ...] = field(default_factory=tuple)
    constituents: tuple[ConstituentContribution, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class QuantMetricsResult:
    schema_version: str
    fund_code: str
    target_etf_symbol: str
    requested_analysis_date: str
    market_date: str
    universe_code: str
    weight_snapshot_date: str
    weight_source: str
    etf_source: str
    etf: ETFMetrics
    sector: SectorMetrics
    data_quality_status: str = COMPLETE
    data_quality_reasons: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def calculate_etf_metrics(symbol: str, frame: pd.DataFrame, analysis_date: str) -> ETFMetrics:
    data = _normalize(frame, analysis_date)
    required = {"High", "Low", "Close"}
    if data.empty or not required.issubset(data.columns):
        raise ValueError(f"{symbol}: valid High/Low/Close history is required")
    close = pd.to_numeric(data["Close"], errors="coerce")
    high = pd.to_numeric(data["High"], errors="coerce")
    low = pd.to_numeric(data["Low"], errors="coerce")
    if close.dropna().empty:
        raise ValueError(f"{symbol}: close history is empty")
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - 100 / (1 + rs)
    rsi = rsi.where(loss.ne(0), 100.0)
    ema12 = close.ewm(span=12, adjust=False, min_periods=12).mean()
    ema26 = close.ewm(span=26, adjust=False, min_periods=26).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False, min_periods=9).mean()
    previous_close = close.shift(1)
    true_range = pd.concat(
        [(high - low).abs(), (high - previous_close).abs(), (low - previous_close).abs()], axis=1
    ).max(axis=1)
    atr = true_range.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    amount = (
        pd.to_numeric(data["Amount"], errors="coerce")
        if "Amount" in data.columns
        else pd.Series(np.nan, index=data.index)
    )
    amount_latest = _latest(amount)

    def amount_ratio(window: int) -> float | None:
        average = _latest(amount.rolling(window, min_periods=window).mean())
        return amount_latest / average if amount_latest is not None and average not in {None, 0} else None

    trailing20 = close.dropna().iloc[-20:]
    drawdown = (
        float((trailing20.iloc[-1] / trailing20.max() - 1) * 100)
        if len(trailing20) == 20 and trailing20.max() != 0
        else None
    )
    sma5 = _latest(close.rolling(5, min_periods=5).mean())
    sma10 = _latest(close.rolling(10, min_periods=10).mean())
    sma20 = _latest(close.rolling(20, min_periods=20).mean())
    sma60 = _latest(close.rolling(60, min_periods=60).mean())
    latest_close = float(close.dropna().iloc[-1])

    def price_vs(value: float | None) -> float | None:
        return (latest_close / value - 1) * 100 if value not in {None, 0} else None

    latest_atr = _latest(atr)
    return ETFMetrics(
        symbol=symbol,
        market_date=data.index[-1].date().isoformat(),
        row_count=len(data),
        close=latest_close,
        sma5=sma5,
        sma10=sma10,
        sma20=sma20,
        sma60=sma60,
        rsi14=_latest(rsi),
        macd=_latest(macd),
        macd_signal=_latest(signal),
        macd_histogram=_latest(macd - signal),
        macd_histogram_change=_latest((macd - signal).diff()),
        atr14=latest_atr,
        atr_pct=latest_atr / latest_close * 100 if latest_atr is not None and latest_close else None,
        return_1d_pct=_return(close, 1),
        return_3d_pct=_return(close, 3),
        return_5d_pct=_return(close, 5),
        return_10d_pct=_return(close, 10),
        return_20d_pct=_return(close, 20),
        drawdown_20d_pct=drawdown,
        amount=amount_latest,
        amount_vs_5d_avg=amount_ratio(5),
        amount_vs_20d_avg=amount_ratio(20),
        price_vs_sma5_pct=price_vs(sma5),
        price_vs_sma10_pct=price_vs(sma10),
        price_vs_sma20_pct=price_vs(sma20),
        price_vs_sma60_pct=price_vs(sma60),
    )


def calculate_sector_metrics(
    frames: Mapping[str, pd.DataFrame],
    constituents: list[dict[str, Any]],
    market_date: str,
    *,
    minimum_count_coverage_pct: float = 80.0,
    minimum_weight_coverage_pct: float = 80.0,
) -> SectorMetrics:
    date = pd.Timestamp(market_date).normalize()
    records: list[ConstituentContribution] = []
    daily_amounts: dict[pd.Timestamp, list[float]] = {}
    weight_available = 0.0
    amount_count = 0
    suspended = 0
    for item in constituents:
        symbol = item["symbol"]
        data = _normalize(frames.get(symbol, pd.DataFrame()), market_date)
        close = pd.to_numeric(data.get("Close"), errors="coerce") if not data.empty and "Close" in data else pd.Series(dtype=float)
        current_rows = data.loc[data.index.normalize() == date] if not data.empty else pd.DataFrame()
        current_close = _number(current_rows["Close"].iloc[-1]) if not current_rows.empty and "Close" in current_rows else None
        previous = (
            close.loc[close.index.normalize() < date].dropna()
            if isinstance(close.index, pd.DatetimeIndex)
            else pd.Series(dtype=float)
        )
        return_1d = (
            (current_close / float(previous.iloc[-1]) - 1) * 100
            if current_close is not None and len(previous) and previous.iloc[-1] != 0
            else None
        )
        amount = _number(current_rows["Amount"].iloc[-1]) if not current_rows.empty and "Amount" in current_rows else None
        volume = _number(current_rows["Volume"].iloc[-1]) if not current_rows.empty and "Volume" in current_rows else None
        if return_1d is None:
            direction = "MISSING"
        elif return_1d > 0:
            direction = "UP"
        elif return_1d < 0:
            direction = "DOWN"
        else:
            direction = "UNCHANGED"
        weight = float(item["weight_pct"])
        if return_1d is not None:
            weight_available += weight
        if amount is not None:
            amount_count += 1
        if volume == 0:
            suspended += 1
        records.append(
            ConstituentContribution(
                symbol=symbol,
                name=item.get("name") or symbol,
                weight_pct=weight,
                return_1d_pct=return_1d,
                weighted_contribution_pct=return_1d * weight / 100 if return_1d is not None else None,
                amount=amount,
                direction=direction,
                csi_industry_level1=item.get("csi_industry_level1") or "未分类",
                csi_industry_level2=item.get("csi_industry_level2") or "未分类",
                csi_industry_level3=item.get("csi_industry_level3") or "未分类",
                csi_industry_level4=item.get("csi_industry_level4") or "未分类",
                supply_chain=item.get("supply_chain") or "未分类",
            )
        )
        if not data.empty and "Amount" in data:
            for idx, value in pd.to_numeric(data["Amount"], errors="coerce").items():
                if pd.notna(value):
                    daily_amounts.setdefault(pd.Timestamp(idx).normalize(), []).append(float(value))

    valid = [record for record in records if record.return_1d_pct is not None]
    count_coverage = len(valid) / len(constituents) * 100 if constituents else 0.0
    status = (
        COMPLETE
        if count_coverage >= minimum_count_coverage_pct
        and weight_available >= minimum_weight_coverage_pct
        else INSUFFICIENT_COVERAGE
    )
    amounts_today = [record.amount for record in records if record.amount is not None]
    total_amount = sum(amounts_today) if amounts_today else None
    total_by_date = pd.Series(
        {key: sum(values) for key, values in daily_amounts.items() if len(values) == len(constituents)},
        dtype=float,
    ).sort_index()

    def board_amount_ratio(window: int) -> float | None:
        if total_amount is None or amount_count != len(constituents):
            return None
        history = total_by_date.loc[total_by_date.index <= date]
        if len(history) < window:
            return None
        average = history.iloc[-window:].mean()
        return float(total_amount / average) if average else None

    up_amount = sum(record.amount or 0 for record in records if record.direction == "UP")
    down_amount = sum(record.amount or 0 for record in records if record.direction == "DOWN")
    weighted = sum(record.weighted_contribution_pct or 0 for record in valid)
    top10 = sorted(records, key=lambda record: record.weight_pct, reverse=True)[:10]

    def group_metrics(attribute: str) -> tuple[ClassificationGroupMetrics, ...]:
        grouped: dict[str, list[ConstituentContribution]] = {}
        for record in records:
            grouped.setdefault(getattr(record, attribute), []).append(record)
        output = []
        for name, group in grouped.items():
            price_rows = [row for row in group if row.return_1d_pct is not None]
            amount_rows = [row for row in group if row.amount is not None]
            output.append(
                ClassificationGroupMetrics(
                    classification=name,
                    constituent_count=len(group),
                    price_available_count=len(price_rows),
                    amount_available_count=len(amount_rows),
                    index_weight_pct=sum(row.weight_pct for row in group),
                    total_amount_available=sum(row.amount for row in amount_rows) if amount_rows else None,
                    advancers=sum(row.direction == "UP" for row in group),
                    decliners=sum(row.direction == "DOWN" for row in group),
                    unchanged=sum(row.direction == "UNCHANGED" for row in group),
                    equal_weight_return_pct=(
                        float(np.mean([row.return_1d_pct for row in price_rows])) if price_rows else None
                    ),
                    index_weighted_contribution_pct=(
                        sum(row.weighted_contribution_pct or 0 for row in price_rows)
                        if price_rows
                        else None
                    ),
                )
            )
        return tuple(sorted(output, key=lambda row: (-row.index_weight_pct, row.classification)))

    return SectorMetrics(
        market_date=market_date,
        expected_count=len(constituents),
        price_available_count=len(valid),
        amount_available_count=amount_count,
        count_coverage_pct=count_coverage,
        weight_coverage_pct=weight_available,
        amount_count_coverage_pct=amount_count / len(constituents) * 100 if constituents else 0.0,
        csi_classification_coverage_pct=(
            sum(record.csi_industry_level4 != "未分类" for record in records) / len(constituents) * 100
            if constituents
            else 0.0
        ),
        supply_chain_classification_coverage_pct=(
            sum(record.supply_chain != "未分类" for record in records) / len(constituents) * 100
            if constituents
            else 0.0
        ),
        status=status,
        total_amount_available=total_amount,
        amount_vs_5d_avg=board_amount_ratio(5),
        amount_vs_20d_avg=board_amount_ratio(20),
        advancers=sum(record.direction == "UP" for record in records),
        decliners=sum(record.direction == "DOWN" for record in records),
        unchanged=sum(record.direction == "UNCHANGED" for record in records),
        suspended_or_zero_volume=suspended,
        advance_amount_pct=up_amount / total_amount * 100 if total_amount else None,
        decline_amount_pct=down_amount / total_amount * 100 if total_amount else None,
        equal_weight_return_pct=float(np.mean([record.return_1d_pct for record in valid])) if valid else None,
        index_weighted_return_pct=weighted if valid else None,
        top10_weighted_contribution_pct=sum(record.weighted_contribution_pct or 0 for record in top10)
        if top10
        else None,
        csi_level4_groups=group_metrics("csi_industry_level4"),
        supply_chain_groups=group_metrics("supply_chain"),
        constituents=tuple(records),
    )


class SectorFundQuantService:
    def __init__(self, session: Session, mode: str = "database_only", provider=None):
        self.session = session
        self.mode = mode
        self.provider = provider

    def _latest_full_snapshot(self, index_code: str, analysis_date: str):
        return self.session.execute(
            select(UniverseSnapshot, Universe)
            .join(Universe, Universe.id == UniverseSnapshot.universe_id)
            .where(
                Universe.code == f"INDEX:{index_code}",
                UniverseSnapshot.as_of_date <= analysis_date,
                UniverseSnapshot.status == "SUCCESS",
            )
            .order_by(UniverseSnapshot.as_of_date.desc(), UniverseSnapshot.id.desc())
        ).first()

    def _append_current_mcp_bar(
        self,
        frame: pd.DataFrame,
        *,
        symbol: str,
        analysis_date: str,
        require_close_confirmation: bool,
    ) -> tuple[pd.DataFrame, bool, str | None]:
        """Overlay a current-day MCP bar in memory only.

        The raw document remains in ``mcp_web_observation``.  No MCP data is
        inserted into the historical AKShare market-bar table.
        """
        bar = load_current_daily_bar(
            self.session,
            instrument_symbol=symbol,
            analysis_date=analysis_date,
            require_close_confirmation=require_close_confirmation,
        )
        if not bar:
            reason = (
                "CLOSE_CONFIRMATION_REQUIRED"
                if require_close_confirmation
                else "CURRENT_BAR_UNAVAILABLE"
            )
            return frame, False, reason
        current = pd.DataFrame([bar])
        if "Date" not in current.columns:
            return frame, False, "CURRENT_BAR_INVALID"
        current["Date"] = pd.to_datetime(current["Date"], errors="coerce")
        if current["Date"].isna().any():
            return frame, False, "CURRENT_BAR_INVALID"
        current = current.set_index("Date")
        historical = _normalize(frame, analysis_date)
        prior = historical.loc[historical.index.normalize() < pd.Timestamp(analysis_date).normalize()]
        if prior.empty:
            return frame, False, "HISTORICAL_BASE_GAP"
        # A normal weekend creates at most a three-calendar-day gap.  A
        # longer gap must be backfilled from the historical provider before a
        # current snapshot can be interpreted as a one-day observation.
        gap_days = (pd.Timestamp(analysis_date).date() - prior.index[-1].date()).days
        if gap_days > 4:
            return frame, False, "HISTORICAL_BASE_GAP"
        combined = pd.concat([frame, current])
        return combined.loc[~combined.index.duplicated(keep="last")].sort_index(), True, None

    def analyze(
        self,
        *,
        fund_code: str,
        target_etf_symbol: str,
        index_code: str,
        analysis_date: str,
        mcp_current_day_only: bool = False,
        analysis_mode: str = "intraday",
    ) -> QuantMetricsResult:
        snapshot_row = self._latest_full_snapshot(index_code, analysis_date)
        if snapshot_row is None:
            raise ValueError(f"no complete index snapshot at or before {analysis_date}")
        snapshot, universe = snapshot_row
        rows = self.session.execute(
            select(UniverseConstituentWeight, Instrument)
            .join(Instrument, Instrument.id == UniverseConstituentWeight.instrument_id)
            .where(UniverseConstituentWeight.snapshot_id == snapshot.id)
            .order_by(UniverseConstituentWeight.rank)
        ).all()
        classification_map = load_latest_classifications(
            self.session, [instrument.id for _, instrument in rows], analysis_date
        )
        constituents = []
        for weight, instrument in rows:
            schemes = classification_map.get(instrument.id, {})
            csi = schemes.get(CSI_SCHEME, {}).get("value", {})
            chain = schemes.get(CHAIN_SCHEME, {}).get("value", {})
            constituents.append({
                "symbol": instrument.symbol,
                "name": instrument.name,
                "weight_pct": weight.weight_pct,
                "rank": weight.rank,
                "csi_industry_level1": csi.get("level1", {}).get("name"),
                "csi_industry_level2": csi.get("level2", {}).get("name"),
                "csi_industry_level3": csi.get("level3", {}).get("name"),
                "csi_industry_level4": csi.get("level4", {}).get("name"),
                "supply_chain": chain.get("category"),
            })
        if not constituents:
            raise ValueError("selected complete index snapshot has no constituents")
        requested_day = pd.Timestamp(analysis_date).date()
        today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
        current_day_requested = mcp_current_day_only and requested_day == today
        database_end = (today - timedelta(days=1)).isoformat() if current_day_requested else analysis_date
        start = (pd.Timestamp(database_end).date() - timedelta(days=400)).isoformat()
        market = MarketDataService(self.session, mode=self.mode, provider=self.provider)
        etf_result = market.daily(target_etf_symbol, start, database_end)
        if etf_result.status != SUCCESS or etf_result.data.empty:
            raise ValueError(f"target ETF unavailable: {etf_result.status}: {etf_result.message}")
        etf_frame = etf_result.data
        etf_uses_mcp = False
        quality_reasons: list[str] = []
        if current_day_requested:
            etf_frame, etf_uses_mcp, etf_reason = self._append_current_mcp_bar(
                etf_frame,
                symbol=target_etf_symbol,
                analysis_date=analysis_date,
                require_close_confirmation=analysis_mode in {"close", "nav_confirmed"},
            )
            if etf_reason:
                quality_reasons.append(etf_reason)
        etf = calculate_etf_metrics(target_etf_symbol, etf_frame, analysis_date)
        frames: dict[str, pd.DataFrame] = {}
        for item in constituents:
            result = market.daily(item["symbol"], start, database_end)
            frame = result.data if result.status == SUCCESS else pd.DataFrame()
            if current_day_requested:
                frame, _, reason = self._append_current_mcp_bar(
                    frame,
                    symbol=item["symbol"],
                    analysis_date=analysis_date,
                    require_close_confirmation=analysis_mode in {"close", "nav_confirmed"},
                )
                if reason and reason not in quality_reasons:
                    quality_reasons.append(reason)
            frames[item["symbol"]] = frame
        sector = calculate_sector_metrics(frames, constituents, etf.market_date)
        if current_day_requested and not etf_uses_mcp:
            quality_reasons.append("SCORE_BLOCKED_BY_DATA_QUALITY")
        if current_day_requested and sector.status != COMPLETE:
            quality_reasons.append("SECTOR_COVERAGE_INSUFFICIENT")
        return QuantMetricsResult(
            schema_version="sector_fund_quant_v1",
            fund_code=fund_code,
            target_etf_symbol=target_etf_symbol,
            requested_analysis_date=analysis_date,
            market_date=etf.market_date,
            universe_code=universe.code,
            weight_snapshot_date=snapshot.as_of_date,
            weight_source=snapshot.source,
            etf_source="mcp_web_observation" if etf_uses_mcp else etf_result.source,
            etf=etf,
            sector=sector,
            data_quality_status=(
                COMPLETE if not quality_reasons else "SCORE_BLOCKED_BY_DATA_QUALITY"
            ),
            data_quality_reasons=tuple(dict.fromkeys(quality_reasons)),
        )
