"""Point-in-time backtest engine for the deterministic sector-fund pipeline."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from tradingagents.storage.models import (
    Instrument,
    SectorFundBacktestRun,
    SectorFundBacktestSample,
    Universe,
    UniverseConstituentWeight,
    UniverseSnapshot,
)

from .quant_metrics import QuantMetricsResult, calculate_etf_metrics, calculate_sector_metrics
from .scoring import SCORING_VERSION, build_scored_report

FEATURE_VERSION = "sector_fund_quant_v1"
PROBABILITY_CONFIG = {
    "window": "EXPANDING",
    "minimum_total_prior_samples": 30,
    "score_bin_width": 10,
    "minimum_prior_samples_in_bin": 10,
    "laplace_alpha": 1.0,
    "calibration_metric": "MULTICLASS_BRIER_SCORE",
}


@dataclass(frozen=True)
class LabelPolicy:
    version: str
    up_1d_pct: float
    down_1d_pct: float
    up_3d_pct: float
    down_3d_pct: float

    def __post_init__(self):
        if self.down_1d_pct >= self.up_1d_pct or self.down_3d_pct >= self.up_3d_pct:
            raise ValueError("down thresholds must be lower than up thresholds")


DEFAULT_LABEL_POLICY = LabelPolicy(
    version="sector_fund_labels_v1",
    up_1d_pct=1.0,
    down_1d_pct=-1.0,
    up_3d_pct=2.0,
    down_3d_pct=-2.0,
)


@dataclass(frozen=True)
class BacktestSampleResult:
    analysis_date: str
    weight_snapshot_id: int
    weight_snapshot_date: str
    core_score: float | None
    short_score: float | None
    forward_1d_pct: float
    forward_3d_pct: float
    label_1d: str
    label_3d: str
    score_bin: int | None
    probability_1d: dict[str, float] | None
    probability_3d: dict[str, float] | None
    brier_1d: float | None
    brier_3d: float | None
    feature: dict[str, Any]


@dataclass(frozen=True)
class BacktestResult:
    run_id: str
    input_hash: str
    fund_code: str
    requested_end_date: str
    sample_start_date: str | None
    sample_end_date: str | None
    sample_count: int
    status: str
    label_policy: dict[str, Any]
    horizon_1d: dict[str, Any]
    horizon_3d: dict[str, Any]
    samples: tuple[BacktestSampleResult, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _label(value: float, up: float, down: float) -> str:
    if value > up:
        return "UP"
    if value < down:
        return "DOWN"
    return "SIDEWAYS"


def _summary(samples: list[BacktestSampleResult], horizon: int, minimum_samples: int) -> dict[str, Any]:
    returns = np.array([getattr(sample, f"forward_{horizon}d_pct") for sample in samples], dtype=float)
    labels = [getattr(sample, f"label_{horizon}d") for sample in samples]
    counts = {name: labels.count(name) for name in ("UP", "SIDEWAYS", "DOWN")}
    enough = len(samples) >= minimum_samples
    briers = [getattr(sample, f"brier_{horizon}d") for sample in samples]
    briers = [value for value in briers if value is not None]
    predictions = [
        sample for sample in samples if getattr(sample, f"probability_{horizon}d") is not None
    ]
    correct = 0
    for sample in predictions:
        probabilities = getattr(sample, f"probability_{horizon}d")
        predicted = max(probabilities, key=probabilities.get)
        correct += predicted == getattr(sample, f"label_{horizon}d")
    return {
        "sample_count": len(samples),
        "label_counts": counts,
        "label_probabilities": (
            {name: count / len(samples) for name, count in counts.items()} if enough and len(samples) else None
        ),
        "probability_status": "AVAILABLE" if enough else "INSUFFICIENT_SAMPLE",
        "mean_return_pct": float(returns.mean()) if len(returns) else None,
        "median_return_pct": float(np.median(returns)) if len(returns) else None,
        "p10_return_pct": float(np.quantile(returns, 0.10)) if len(returns) else None,
        "p90_return_pct": float(np.quantile(returns, 0.90)) if len(returns) else None,
        "worst_return_pct": float(returns.min()) if len(returns) else None,
        "walk_forward_prediction_count": len(predictions),
        "direction_accuracy": correct / len(predictions) if predictions else None,
        "calibration_error": float(np.mean(briers)) if briers else None,
        "calibration_status": "AVAILABLE" if briers else "INSUFFICIENT_WALK_FORWARD_SAMPLES",
    }


def _score_bin(sample: BacktestSampleResult) -> int | None:
    values = [value for value in (sample.core_score, sample.short_score) if value is not None]
    if not values:
        return None
    score = float(np.mean(values))
    width = int(PROBABILITY_CONFIG["score_bin_width"])
    return min(int(score // width) * width, 100 - width)


def _probabilities(prior: list[BacktestSampleResult], horizon: int) -> dict[str, float]:
    alpha = float(PROBABILITY_CONFIG["laplace_alpha"])
    labels = [getattr(sample, f"label_{horizon}d") for sample in prior]
    denominator = len(labels) + alpha * 3
    return {
        name: (labels.count(name) + alpha) / denominator
        for name in ("UP", "SIDEWAYS", "DOWN")
    }


def _brier(probabilities: dict[str, float], actual: str) -> float:
    return float(
        sum((probability - (1.0 if name == actual else 0.0)) ** 2 for name, probability in probabilities.items())
    )


def _apply_walk_forward_probabilities(
    samples: list[BacktestSampleResult],
) -> list[BacktestSampleResult]:
    output: list[BacktestSampleResult] = []
    minimum_total = int(PROBABILITY_CONFIG["minimum_total_prior_samples"])
    minimum_bin = int(PROBABILITY_CONFIG["minimum_prior_samples_in_bin"])
    for sample in samples:
        current_bin = _score_bin(sample)
        eligible = [prior for prior in output if prior.score_bin == current_bin]
        probability_1d = probability_3d = None
        brier_1d = brier_3d = None
        if current_bin is not None and len(output) >= minimum_total and len(eligible) >= minimum_bin:
            probability_1d = _probabilities(eligible, 1)
            probability_3d = _probabilities(eligible, 3)
            brier_1d = _brier(probability_1d, sample.label_1d)
            brier_3d = _brier(probability_3d, sample.label_3d)
        output.append(
            replace(
                sample,
                score_bin=current_bin,
                probability_1d=probability_1d,
                probability_3d=probability_3d,
                brier_1d=brier_1d,
                brier_3d=brier_3d,
            )
        )
    return output


def _frame_fingerprint(frame: pd.DataFrame) -> list[list[Any]]:
    if frame is None or frame.empty:
        return []
    data = frame.copy().sort_index()
    columns = [column for column in ("Close", "Amount", "Volume") if column in data.columns]
    return [
        [pd.Timestamp(index).isoformat(), *[None if pd.isna(row[column]) else float(row[column]) for column in columns]]
        for index, row in data[columns].iterrows()
    ]


def run_point_in_time_backtest(
    session: Session,
    *,
    fund_code: str,
    etf_symbol: str,
    index_code: str,
    end_date: str,
    frame_loader: Callable[[str, str, str], pd.DataFrame],
    label_policy: LabelPolicy,
    minimum_probability_samples: int = 30,
    minimum_history_rows: int = 60,
) -> BacktestResult:
    """Run once-loaded history through daily point-in-time snapshots.

    ``frame_loader`` is called once per symbol, never once per sample date.
    """
    snapshots = session.execute(
        select(UniverseSnapshot, Universe)
        .join(Universe, Universe.id == UniverseSnapshot.universe_id)
        .where(
            Universe.code == f"INDEX:{index_code}",
            UniverseSnapshot.status == "SUCCESS",
            UniverseSnapshot.as_of_date <= end_date,
        )
        .order_by(UniverseSnapshot.as_of_date, UniverseSnapshot.id)
    ).all()
    if not snapshots:
        raise ValueError("no point-in-time universe snapshot available")
    snapshot_constituents: dict[int, list[dict[str, Any]]] = {}
    symbols = {etf_symbol}
    for snapshot, _ in snapshots:
        rows = session.execute(
            select(UniverseConstituentWeight, Instrument)
            .join(Instrument, Instrument.id == UniverseConstituentWeight.instrument_id)
            .where(UniverseConstituentWeight.snapshot_id == snapshot.id)
            .order_by(UniverseConstituentWeight.rank)
        ).all()
        constituents = [
            {
                "symbol": instrument.symbol,
                "name": instrument.name or instrument.symbol,
                "weight_pct": weight.weight_pct,
                "rank": weight.rank,
            }
            for weight, instrument in rows
        ]
        if not constituents:
            raise ValueError(f"universe snapshot {snapshot.id} has no constituents")
        snapshot_constituents[snapshot.id] = constituents
        symbols.update(item["symbol"] for item in constituents)
    earliest_snapshot_date = min(snapshot.as_of_date for snapshot, _ in snapshots)
    load_start = (pd.Timestamp(earliest_snapshot_date) - pd.Timedelta(days=400)).date().isoformat()
    frames = {symbol: frame_loader(symbol, load_start, end_date) for symbol in sorted(symbols)}
    etf_frame = frames.get(etf_symbol, pd.DataFrame()).copy()
    if etf_frame.empty or "Close" not in etf_frame.columns:
        raise ValueError("ETF history is unavailable")
    etf_frame.index = pd.to_datetime(etf_frame.index)
    etf_frame = etf_frame.sort_index().loc[lambda x: x.index <= pd.Timestamp(end_date)]
    dates = [pd.Timestamp(value) for value in etf_frame.index.normalize().unique()]
    snapshot_by_date = [(pd.Timestamp(snapshot.as_of_date), snapshot) for snapshot, _ in snapshots]
    samples: list[BacktestSampleResult] = []
    for position, date in enumerate(dates):
        if date < pd.Timestamp(earliest_snapshot_date) or position < minimum_history_rows - 1:
            continue
        if position + 3 >= len(dates):
            continue
        eligible = [snapshot for valid_from, snapshot in snapshot_by_date if valid_from <= date]
        if not eligible:
            continue
        snapshot = eligible[-1]
        constituents = snapshot_constituents[snapshot.id]
        date_string = date.date().isoformat()
        etf_metrics = calculate_etf_metrics(etf_symbol, etf_frame.loc[:date], date_string)
        sector_metrics = calculate_sector_metrics(frames, constituents, date_string)
        if sector_metrics.status != "COMPLETE":
            continue
        metrics = QuantMetricsResult(
            schema_version=FEATURE_VERSION,
            fund_code=fund_code,
            target_etf_symbol=etf_symbol,
            requested_analysis_date=date_string,
            market_date=date_string,
            universe_code=f"INDEX:{index_code}",
            weight_snapshot_date=snapshot.as_of_date,
            weight_source=snapshot.source,
            etf_source="backtest_frame_loader",
            etf=etf_metrics,
            sector=sector_metrics,
        )
        # Backtests retain partial historical factors for research only.  Live
        # reports always use the default strict coverage gate.
        scored = build_scored_report(metrics, for_backtest_feature_generation=True)
        close_now = float(etf_frame.loc[etf_frame.index.normalize() == date, "Close"].iloc[-1])
        close_1d = float(etf_frame.loc[etf_frame.index.normalize() == dates[position + 1], "Close"].iloc[-1])
        close_3d = float(etf_frame.loc[etf_frame.index.normalize() == dates[position + 3], "Close"].iloc[-1])
        forward_1d = (close_1d / close_now - 1) * 100
        forward_3d = (close_3d / close_now - 1) * 100
        feature = {
            "metrics": metrics.to_dict(),
            "core_trend": asdict(scored.core_trend),
            "short_term": asdict(scored.short_term),
            "input_cutoff": date_string,
            "future_fields_in_feature": False,
        }
        samples.append(
            BacktestSampleResult(
                analysis_date=date_string,
                weight_snapshot_id=snapshot.id,
                weight_snapshot_date=snapshot.as_of_date,
                core_score=scored.core_trend.score,
                short_score=scored.short_term.score,
                forward_1d_pct=forward_1d,
                forward_3d_pct=forward_3d,
                label_1d=_label(forward_1d, label_policy.up_1d_pct, label_policy.down_1d_pct),
                label_3d=_label(forward_3d, label_policy.up_3d_pct, label_policy.down_3d_pct),
                score_bin=None,
                probability_1d=None,
                probability_3d=None,
                brier_1d=None,
                brier_3d=None,
                feature=feature,
            )
        )
    samples = _apply_walk_forward_probabilities(samples)
    fingerprint = {
        "fund_code": fund_code,
        "end_date": end_date,
        "label_policy": asdict(label_policy),
        "probability_config": PROBABILITY_CONFIG,
        "snapshots": [
            {
                "id": snapshot.id,
                "date": snapshot.as_of_date,
                "constituents": snapshot_constituents[snapshot.id],
            }
            for snapshot, _ in snapshots
        ],
        "frames": {symbol: _frame_fingerprint(frame) for symbol, frame in sorted(frames.items())},
    }
    canonical = json.dumps(fingerprint, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    input_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    run_id = hashlib.sha256(f"backtest\n{input_hash}".encode()).hexdigest()
    status = "SUCCESS" if len(samples) >= minimum_probability_samples else "INSUFFICIENT_SAMPLE"
    return BacktestResult(
        run_id=run_id,
        input_hash=input_hash,
        fund_code=fund_code,
        requested_end_date=end_date,
        sample_start_date=samples[0].analysis_date if samples else None,
        sample_end_date=samples[-1].analysis_date if samples else None,
        sample_count=len(samples),
        status=status,
        label_policy=asdict(label_policy),
        horizon_1d=_summary(samples, 1, minimum_probability_samples),
        horizon_3d=_summary(samples, 3, minimum_probability_samples),
        samples=tuple(samples),
    )


def persist_backtest_result(session: Session, result: BacktestResult) -> dict[str, int | str]:
    existing = session.get(SectorFundBacktestRun, result.run_id)
    if existing is not None:
        return {"runs_inserted": 0, "samples_inserted": 0, "run_id": result.run_id}
    config = {
        "feature_version": FEATURE_VERSION,
        "scoring_version": SCORING_VERSION,
        "label_policy": result.label_policy,
        "minimum_probability_samples": 30,
        "probability_config": PROBABILITY_CONFIG,
    }
    session.add(
        SectorFundBacktestRun(
            run_id=result.run_id,
            fund_code=result.fund_code,
            requested_end_date=result.requested_end_date,
            feature_version=FEATURE_VERSION,
            scoring_version=SCORING_VERSION,
            label_version=str(result.label_policy["version"]),
            sample_start_date=result.sample_start_date,
            sample_end_date=result.sample_end_date,
            sample_count=result.sample_count,
            status=result.status,
            input_hash=result.input_hash,
            config_json=json.dumps(config, ensure_ascii=False, sort_keys=True),
            result_json=json.dumps(
                {
                    "horizon_1d": result.horizon_1d,
                    "horizon_3d": result.horizon_3d,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
        )
    )
    for sample in result.samples:
        session.add(
            SectorFundBacktestSample(
                run_id=result.run_id,
                analysis_date=sample.analysis_date,
                weight_snapshot_id=sample.weight_snapshot_id,
                weight_snapshot_date=sample.weight_snapshot_date,
                core_score=sample.core_score,
                short_score=sample.short_score,
                forward_1d_pct=sample.forward_1d_pct,
                forward_3d_pct=sample.forward_3d_pct,
                label_1d=sample.label_1d,
                label_3d=sample.label_3d,
                prediction_json=json.dumps(
                    {
                        "score_bin": sample.score_bin,
                        "probability_1d": sample.probability_1d,
                        "probability_3d": sample.probability_3d,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                brier_1d=sample.brier_1d,
                brier_3d=sample.brier_3d,
                feature_json=json.dumps(sample.feature, ensure_ascii=False, sort_keys=True),
            )
        )
    session.commit()
    return {"runs_inserted": 1, "samples_inserted": len(result.samples), "run_id": result.run_id}
