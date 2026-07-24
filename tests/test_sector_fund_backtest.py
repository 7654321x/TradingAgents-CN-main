from __future__ import annotations

import json

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from tradingagents.extensions.sector_fund.backtest import (
    LabelPolicy,
    persist_backtest_result,
    run_point_in_time_backtest,
)
from tradingagents.extensions.sector_fund.baseline import save_universe_snapshot
from tradingagents.storage.db import init_db
from tradingagents.storage.models import SectorFundBacktestRun, SectorFundBacktestSample


def _frame(start, periods, base, slope=0.1):
    index = pd.bdate_range(start=start, periods=periods)
    close = base + np.arange(periods) * slope
    return pd.DataFrame(
        {
            "Open": close - 0.1,
            "High": close + 0.3,
            "Low": close - 0.3,
            "Close": close,
            "Volume": np.full(periods, 1000.0),
            "Amount": np.full(periods, 100000.0),
        },
        index=index,
    )


def _setup():
    engine = init_db(create_engine("sqlite+pysqlite:///:memory:"))
    with Session(engine) as session:
        first = save_universe_snapshot(
            session,
            universe={"code": "INDEX:000685", "name": "index"},
            constituents=[
                {"symbol": "A.SS", "name": "A", "weight_pct": 60, "rank": 1},
                {"symbol": "B.SS", "name": "B", "weight_pct": 40, "rank": 2},
            ],
            as_of_date="2026-01-01",
            source="official",
            status="SUCCESS",
        )
        second = save_universe_snapshot(
            session,
            universe={"code": "INDEX:000685", "name": "index"},
            constituents=[{"symbol": "C.SS", "name": "C", "weight_pct": 100, "rank": 1}],
            as_of_date="2026-03-01",
            source="official",
            status="SUCCESS",
        )
        session.commit()
        ids = (first.id, second.id)
    frames = {
        "589130.SS": _frame("2025-10-01", 150, 10),
        "A.SS": _frame("2025-10-01", 150, 20),
        "B.SS": _frame("2025-10-01", 150, 30),
        "C.SS": _frame("2025-10-01", 150, 40),
    }
    return engine, ids, frames


POLICY = LabelPolicy(
    version="test_labels_v1",
    up_1d_pct=0.5,
    down_1d_pct=-0.5,
    up_3d_pct=1.0,
    down_3d_pct=-1.0,
)


def test_backtest_selects_only_snapshot_effective_on_analysis_date():
    engine, (first_id, second_id), frames = _setup()
    calls = []

    def loader(symbol, start, end):
        calls.append(symbol)
        return frames[symbol]

    with Session(engine) as session:
        result = run_point_in_time_backtest(
            session,
            fund_code="020671",
            etf_symbol="589130.SS",
            index_code="000685",
            end_date="2026-04-20",
            frame_loader=loader,
            label_policy=POLICY,
        )
    assert len(calls) == len(set(calls)) == 4
    assert result.sample_count > 0
    assert all(sample.weight_snapshot_date <= sample.analysis_date for sample in result.samples)
    assert all(
        sample.weight_snapshot_id == first_id
        for sample in result.samples
        if sample.analysis_date < "2026-03-01"
    )
    assert all(
        sample.weight_snapshot_id == second_id
        for sample in result.samples
        if sample.analysis_date >= "2026-03-01"
    )
    assert all(sample.feature["future_fields_in_feature"] is False for sample in result.samples)
    predicted = [sample for sample in result.samples if sample.probability_1d is not None]
    assert predicted
    assert result.horizon_1d["calibration_status"] == "AVAILABLE"
    assert result.horizon_1d["calibration_error"] is not None
    assert all(abs(sum(sample.probability_1d.values()) - 1) < 1e-12 for sample in predicted)
    assert all(sample.probability_1d["DOWN"] > 0 for sample in predicted)  # Laplace smoothing


def test_future_price_change_does_not_change_earlier_feature():
    engine, _, frames = _setup()

    def loader(symbol, start, end):
        return frames[symbol].copy()

    with Session(engine) as session:
        baseline = run_point_in_time_backtest(
            session,
            fund_code="020671",
            etf_symbol="589130.SS",
            index_code="000685",
            end_date="2026-04-20",
            frame_loader=loader,
            label_policy=POLICY,
        )
    cutoff = pd.Timestamp(baseline.samples[0].analysis_date) + pd.Timedelta(days=20)
    changed = {symbol: frame.copy() for symbol, frame in frames.items()}
    for frame in changed.values():
        frame.loc[frame.index > cutoff, "Close"] *= 10

    def changed_loader(symbol, start, end):
        return changed[symbol]

    with Session(engine) as session:
        modified = run_point_in_time_backtest(
            session,
            fund_code="020671",
            etf_symbol="589130.SS",
            index_code="000685",
            end_date="2026-04-20",
            frame_loader=changed_loader,
            label_policy=POLICY,
        )
    before = {sample.analysis_date: sample.feature for sample in baseline.samples if pd.Timestamp(sample.analysis_date) < cutoff - pd.Timedelta(days=5)}
    after = {sample.analysis_date: sample.feature for sample in modified.samples if sample.analysis_date in before}
    assert before == after


def test_insufficient_samples_suppresses_probabilities_and_persistence_is_idempotent():
    engine, _, frames = _setup()
    with Session(engine) as session:
        result = run_point_in_time_backtest(
            session,
            fund_code="020671",
            etf_symbol="589130.SS",
            index_code="000685",
            end_date="2026-02-15",
            frame_loader=lambda symbol, start, end: frames[symbol],
            label_policy=POLICY,
            minimum_probability_samples=30,
        )
        assert result.status == "INSUFFICIENT_SAMPLE"
        assert result.horizon_1d["label_probabilities"] is None
        assert result.horizon_3d["label_probabilities"] is None
        first = persist_backtest_result(session, result)
        second = persist_backtest_result(session, result)
        assert first["runs_inserted"] == 1
        assert second["runs_inserted"] == 0
        assert session.scalar(select(func.count()).select_from(SectorFundBacktestRun)) == 1
        assert session.scalar(select(func.count()).select_from(SectorFundBacktestSample)) == result.sample_count
        sample = session.scalar(select(SectorFundBacktestSample))
        if sample:
            feature = json.loads(sample.feature_json)
            assert feature["future_fields_in_feature"] is False
