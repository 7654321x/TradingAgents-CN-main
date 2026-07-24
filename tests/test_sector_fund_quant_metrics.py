from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from tradingagents.extensions.sector_fund.baseline import save_universe_snapshot
from tradingagents.extensions.sector_fund.mcp_observation_store import save_mcp_observation
from tradingagents.extensions.sector_fund.quant_metrics import (
    COMPLETE,
    INSUFFICIENT_COVERAGE,
    SectorFundQuantService,
    calculate_etf_metrics,
    calculate_sector_metrics,
)
from tradingagents.extensions.sector_fund.scoring import build_scored_report
from tradingagents.storage.db import init_db
from tradingagents.storage.models import Instrument, MarketBarObservation


def _frame(closes, *, amounts=None, volumes=None, end="2026-07-22"):
    index = pd.bdate_range(end=end, periods=len(closes))
    close = pd.Series(closes, index=index, dtype=float)
    return pd.DataFrame(
        {
            "Open": close - 0.2,
            "High": close + 1.0,
            "Low": close - 1.0,
            "Close": close,
            "Volume": volumes if volumes is not None else np.full(len(close), 1000.0),
            **({"Amount": amounts} if amounts is not None else {}),
        },
        index=index,
    )


def test_etf_metrics_do_not_substitute_volume_for_missing_amount():
    result = calculate_etf_metrics("589130.SS", _frame(np.arange(1, 81)), "2026-07-22")
    assert result.sma5 == 78.0
    assert result.sma20 == 70.5
    assert result.sma60 == 50.5
    assert result.rsi14 == 100.0
    assert result.macd_histogram is not None
    assert result.atr14 is not None
    assert result.return_20d_pct == (80 / 60 - 1) * 100
    assert result.amount is None
    assert result.amount_vs_5d_avg is None
    assert result.amount_vs_20d_avg is None


def test_sector_metrics_separate_board_amount_breadth_and_weighted_return():
    constituents = [
        {"symbol": "A.SS", "name": "A", "weight_pct": 60.0, "csi_industry_level4": "集成电路设计", "supply_chain": "芯片设计"},
        {"symbol": "B.SS", "name": "B", "weight_pct": 30.0, "csi_industry_level4": "集成电路制造", "supply_chain": "晶圆制造"},
        {"symbol": "C.SS", "name": "C", "weight_pct": 10.0, "csi_industry_level4": "集成电路设计", "supply_chain": "芯片设计"},
    ]
    frames = {
        "A.SS": _frame([10, 11, 12, 13, 14], amounts=[100, 100, 100, 100, 200]),
        "B.SS": _frame([10, 9, 8, 7, 6], amounts=[200, 200, 200, 200, 100]),
        "C.SS": _frame([10, 10, 10, 10, 10], amounts=[300, 300, 300, 300, 300], volumes=[1, 1, 1, 1, 0]),
    }
    result = calculate_sector_metrics(frames, constituents, "2026-07-22")
    assert result.status == COMPLETE
    assert result.total_amount_available == 600
    assert result.amount_vs_5d_avg == 600 / 600
    assert result.advancers == 1
    assert result.decliners == 1
    assert result.unchanged == 1
    assert result.suspended_or_zero_volume == 1
    assert result.advance_amount_pct == 200 / 600 * 100
    assert result.decline_amount_pct == 100 / 600 * 100
    assert result.index_weighted_return_pct != result.equal_weight_return_pct
    assert result.csi_classification_coverage_pct == 100.0
    assert result.supply_chain_classification_coverage_pct == 100.0
    assert [(row.classification, row.constituent_count) for row in result.csi_level4_groups] == [
        ("集成电路设计", 2),
        ("集成电路制造", 1),
    ]
    assert result.supply_chain_groups[0].classification == "芯片设计"


def test_missing_constituent_marks_coverage_insufficient_and_amount_ratio_unknown():
    constituents = [
        {"symbol": f"{number}.SS", "name": str(number), "weight_pct": 25.0}
        for number in range(4)
    ]
    frames = {item["symbol"]: _frame([10, 11], amounts=[100, 100]) for item in constituents[:3]}
    result = calculate_sector_metrics(frames, constituents, "2026-07-22")
    assert result.status == INSUFFICIENT_COVERAGE
    assert result.count_coverage_pct == 75.0
    assert result.weight_coverage_pct == 75.0
    assert result.amount_count_coverage_pct == 75.0
    assert result.amount_vs_5d_avg is None


def _persist_frame(session, symbol, frame):
    instrument = Instrument(symbol=symbol, local_code=symbol[:6], name=symbol, instrument_type="stock")
    session.add(instrument)
    session.flush()
    for idx, row in frame.iterrows():
        timestamp = pd.Timestamp(idx).to_pydatetime()
        session.add(
            MarketBarObservation(
                instrument_id=instrument.id,
                interval="1d",
                bar_time=timestamp,
                market_date=timestamp.date().isoformat(),
                open=float(row["Open"]),
                high=float(row["High"]),
                low=float(row["Low"]),
                close=float(row["Close"]),
                volume=float(row["Volume"]),
                amount=float(row["Amount"]),
                is_final=True,
                provider="test",
                upstream_group="test",
                available_at=datetime(2026, 7, 22),
                fetched_at=datetime(2026, 7, 22),
                payload_hash=f"{symbol}-{timestamp.date()}",
                run_id="test",
            )
        )


def test_service_selects_only_snapshot_at_or_before_analysis_date():
    engine = init_db(create_engine("sqlite+pysqlite:///:memory:"))
    symbols = ["688001.SS", "688002.SS"]
    etf_frame = _frame(np.arange(1, 81), amounts=np.arange(100, 180))
    stock_frames = {
        symbols[0]: _frame(np.arange(10, 90), amounts=np.arange(200, 280)),
        symbols[1]: _frame(np.arange(20, 100), amounts=np.arange(300, 380)),
    }
    with Session(engine) as session:
        _persist_frame(session, "589130.SS", etf_frame)
        for symbol, frame in stock_frames.items():
            _persist_frame(session, symbol, frame)
        save_universe_snapshot(
            session,
            universe={"code": "INDEX:000685", "name": "科创芯片"},
            constituents=[
                {"symbol": symbols[0], "name": "A", "weight_pct": 60, "rank": 1},
                {"symbol": symbols[1], "name": "B", "weight_pct": 40, "rank": 2},
            ],
            as_of_date="2026-06-30",
            source="csindex_official",
            status="SUCCESS",
        )
        save_universe_snapshot(
            session,
            universe={"code": "INDEX:000685", "name": "科创芯片"},
            constituents=[{"symbol": "FUTURE.SS", "weight_pct": 100, "rank": 1}],
            as_of_date="2026-08-01",
            source="csindex_official",
            status="SUCCESS",
        )
        session.commit()
        result = SectorFundQuantService(session).analyze(
            fund_code="020671",
            target_etf_symbol="589130.SS",
            index_code="000685",
            analysis_date="2026-07-22",
        )
        assert result.weight_snapshot_date == "2026-06-30"
        assert result.market_date == "2026-07-22"
        assert result.sector.expected_count == 2
        assert {item.symbol for item in result.sector.constituents} == set(symbols)


def test_current_day_mcp_mode_uses_isolated_web_bar_not_market_bar_cache():
    engine = init_db(create_engine("sqlite+pysqlite:///:memory:"))
    symbols = ["688001.SS"]
    analysis_date = pd.Timestamp.now(tz="Asia/Shanghai").date().isoformat()
    etf_frame = _frame(np.arange(1, 81), amounts=np.arange(100, 180), end=analysis_date)
    stock_frame = _frame(np.arange(10, 90), amounts=np.arange(200, 280), end=analysis_date)
    with Session(engine) as session:
        _persist_frame(session, "589130.SS", etf_frame)
        _persist_frame(session, symbols[0], stock_frame)
        save_universe_snapshot(
            session, universe={"code": "INDEX:000685", "name": "科创芯片"},
            constituents=[{"symbol": symbols[0], "name": "A", "weight_pct": 100, "rank": 1}],
            as_of_date="2026-06-30", source="csindex_official", status="SUCCESS",
        )
        assert save_mcp_observation(
            session, dataset_type="current_daily_market", field_name="daily_bar",
            payload={"bar": {"Date": analysis_date, "Open": 179, "High": 181, "Low": 178, "Close": 180, "Volume": 1000, "Amount": 180000}},
            source_level="B", source="mcp_web_resolver", source_url="https://quote.eastmoney.com/test",
            confirmation_status="VERIFIED_WEB_SOURCE", applicable_date=analysis_date, instrument_symbol="589130.SS",
        )
        session.commit()
        result = SectorFundQuantService(session).analyze(
            fund_code="020671", target_etf_symbol="589130.SS", index_code="000685",
            analysis_date=analysis_date, mcp_current_day_only=True,
        )
    assert result.etf.close == 180
    assert result.etf_source == "mcp_web_observation"


def test_close_mode_rejects_unconfirmed_current_bar_and_blocks_scores():
    engine = init_db(create_engine("sqlite+pysqlite:///:memory:"))
    analysis_date = pd.Timestamp.now(tz="Asia/Shanghai").date().isoformat()
    historical_end = (pd.Timestamp(analysis_date) - pd.offsets.BDay(1)).date().isoformat()
    etf_frame = _frame(np.arange(1, 81), amounts=np.arange(100, 180), end=historical_end)
    stock_frame = _frame(np.arange(10, 90), amounts=np.arange(200, 280), end=historical_end)
    with Session(engine) as session:
        _persist_frame(session, "589130.SS", etf_frame)
        _persist_frame(session, "688001.SS", stock_frame)
        save_universe_snapshot(
            session,
            universe={"code": "INDEX:000685", "name": "科创芯片"},
            constituents=[{"symbol": "688001.SS", "name": "A", "weight_pct": 100, "rank": 1}],
            as_of_date="2026-06-30",
            source="csindex_official",
            status="SUCCESS",
        )
        save_mcp_observation(
            session,
            dataset_type="current_daily_market",
            field_name="daily_bar",
            payload={
                "bar": {
                    "Date": analysis_date,
                    "Open": 180,
                    "High": 181,
                    "Low": 179,
                    "Close": 180,
                    "Volume": 1000,
                    "Amount": 180000,
                },
                "trading_status": None,
            },
            source_level="B",
            source="mcp_web_resolver",
            source_url="https://quote.eastmoney.com/test",
            confirmation_status="VERIFIED_WEB_SOURCE",
            applicable_date=analysis_date,
            instrument_symbol="589130.SS",
        )
        session.commit()
        result = SectorFundQuantService(session).analyze(
            fund_code="020671",
            target_etf_symbol="589130.SS",
            index_code="000685",
            analysis_date=analysis_date,
            mcp_current_day_only=True,
            analysis_mode="close",
        )

    report = build_scored_report(result)
    assert result.etf.market_date == historical_end
    assert result.data_quality_status == "SCORE_BLOCKED_BY_DATA_QUALITY"
    assert "CLOSE_CONFIRMATION_REQUIRED" in result.data_quality_reasons
    assert report.core_trend.score is None
    assert report.short_term.score is None


def test_current_bar_with_stale_historical_base_is_not_used_for_intraday_return():
    engine = init_db(create_engine("sqlite+pysqlite:///:memory:"))
    analysis_date = pd.Timestamp.now(tz="Asia/Shanghai").date().isoformat()
    stale_end = (pd.Timestamp(analysis_date) - pd.Timedelta(days=6)).date().isoformat()
    etf_frame = _frame(np.arange(1, 81), amounts=np.arange(100, 180), end=stale_end)
    stock_frame = _frame(np.arange(10, 90), amounts=np.arange(200, 280), end=stale_end)
    with Session(engine) as session:
        _persist_frame(session, "589130.SS", etf_frame)
        _persist_frame(session, "688001.SS", stock_frame)
        save_universe_snapshot(
            session,
            universe={"code": "INDEX:000685", "name": "科创芯片"},
            constituents=[{"symbol": "688001.SS", "name": "A", "weight_pct": 100, "rank": 1}],
            as_of_date="2026-06-30",
            source="csindex_official",
            status="SUCCESS",
        )
        for symbol in ("589130.SS", "688001.SS"):
            save_mcp_observation(
                session,
                dataset_type="current_daily_market",
                field_name="daily_bar",
                payload={
                    "bar": {
                        "Date": analysis_date,
                        "Open": 180,
                        "High": 181,
                        "Low": 179,
                        "Close": 180,
                        "Volume": 1000,
                        "Amount": 180000,
                    },
                    "trading_status": "已收盘",
                },
                source_level="B",
                source="mcp_web_resolver",
                source_url="https://quote.eastmoney.com/test",
                confirmation_status="VERIFIED_WEB_SOURCE",
                applicable_date=analysis_date,
                instrument_symbol=symbol,
            )
        session.commit()
        result = SectorFundQuantService(session).analyze(
            fund_code="020671",
            target_etf_symbol="589130.SS",
            index_code="000685",
            analysis_date=analysis_date,
            mcp_current_day_only=True,
            analysis_mode="intraday",
        )

    assert result.etf.market_date == etf_frame.index[-1].date().isoformat()
    assert "HISTORICAL_BASE_GAP" in result.data_quality_reasons
    assert build_scored_report(result).core_trend.score is None
