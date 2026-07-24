from __future__ import annotations

import json
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from tradingagents.extensions.sector_fund.quant_metrics import (
    QuantMetricsResult,
    calculate_etf_metrics,
    calculate_sector_metrics,
)
from tradingagents.extensions.sector_fund.scoring import (
    SCORING_VERSION,
    build_scored_report,
    calculate_core_trend_score,
    calculate_short_term_score,
)
from tradingagents.reports.sector_fund_report import (
    render_sector_fund_markdown,
    save_sector_fund_report,
)


def _frame(closes, amount_multiplier=1.0, with_amount=True):
    index = pd.bdate_range(end="2026-07-21", periods=len(closes))
    close = pd.Series(closes, index=index, dtype=float)
    data = pd.DataFrame(
        {
            "Open": close - 0.1,
            "High": close + 0.3,
            "Low": close - 0.3,
            "Close": close,
            "Volume": np.arange(1, len(close) + 1) * 1000,
        },
        index=index,
    )
    if with_amount:
        data["Amount"] = np.arange(1, len(close) + 1) * 10000 * amount_multiplier
    return data


def _metrics(with_amount=True):
    constituents = [
        {
            "symbol": "A.SS",
            "name": "A",
            "weight_pct": 60.0,
            "csi_industry_level4": "集成电路设计",
            "supply_chain": "芯片设计",
        },
        {
            "symbol": "B.SS",
            "name": "B",
            "weight_pct": 40.0,
            "csi_industry_level4": "半导体设备",
            "supply_chain": "半导体设备",
        },
    ]
    etf_frame = _frame(np.linspace(10, 20, 80), with_amount=with_amount)
    stock_frames = {
        "A.SS": _frame(np.linspace(10, 18, 80), 2, with_amount),
        "B.SS": _frame(np.linspace(10, 16, 80), 3, with_amount),
    }
    etf = calculate_etf_metrics("589130.SS", etf_frame, "2026-07-22")
    sector = calculate_sector_metrics(stock_frames, constituents, etf.market_date)
    return QuantMetricsResult(
        schema_version="sector_fund_quant_v1",
        fund_code="020671",
        target_etf_symbol="589130.SS",
        requested_analysis_date="2026-07-22",
        market_date=etf.market_date,
        universe_code="INDEX:000685",
        weight_snapshot_date="2026-06-30",
        weight_source="csindex_official",
        etf_source="akshare_sina",
        etf=etf,
        sector=sector,
    )


def _full_context():
    return {
        "event_scan_status": "COMPLETE",
        "etf_status": {
            "shares_change_status": "AVAILABLE",
            "shares_change_pct": 1.2,
            "discount_rate_pct": 0.2,
        },
        "recent_events_7d": [
            {"source_level": "A", "confirmation_status": "CONFIRMED", "title": "官方公告"}
        ],
        "extended_observations": {
            "financial": [{"status": "SUCCESS"} for _ in range(10)],
            "fund_flow": [{"status": "SUCCESS"} for _ in range(10)],
            "industry_cycle": [{"status": "SUCCESS"} for _ in range(3)],
            "intraday": [{"status": "SUCCESS"} for _ in range(10)],
        },
    }


def test_scores_are_bounded_versioned_and_reproducible():
    metrics = _metrics()
    first = build_scored_report(metrics, _full_context())
    second = build_scored_report(metrics, _full_context())
    assert first.scoring_version == SCORING_VERSION
    assert first.input_hash == second.input_hash
    assert first.to_dict() == second.to_dict()
    assert 0 <= first.core_trend.score <= 100
    assert 0 <= first.short_term.score <= 100
    assert first.core_trend.label in {
        "STRONG_TREND_OVERHEATED",
        "STRONG_TREND",
        "TREND_REPAIR",
        "RANGE_BOUND",
        "SLIGHTLY_WEAK",
        "WEAK_DOWNWARD",
        "INSUFFICIENT_DATA",
    }
    assert first.probability_output["status"] == "NOT_AVAILABLE"
    assert first.historical_adjustment["status"] == "NOT_APPLIED"


def test_missing_amount_is_not_scored_as_zero_and_reduces_coverage():
    complete = calculate_core_trend_score(_metrics(True))
    missing = calculate_core_trend_score(_metrics(False))
    volume = next(item for item in missing.dimensions if item.dimension == "funds_and_turnover")
    assert volume.coverage_pct < 100
    assert any(rule.status == "MISSING" for rule in volume.rules)
    assert missing.scoring_coverage_pct < complete.scoring_coverage_pct
    assert missing.score is not None


def test_short_score_contains_confirmed_weight_dimensions():
    result = calculate_short_term_score(_metrics())
    assert {item.dimension: item.max_score for item in result.dimensions} == {
        "daily_kline_and_close_position": 25,
        "price_volume_and_etf_support": 25,
        "core_weight_tail_performance": 20,
        "breadth_and_diffusion": 15,
        "external_and_after_market_events": 15,
    }


def test_v2_scores_use_confirmed_context_and_preserve_missing_modules():
    metrics = _metrics()
    context = _full_context()
    core = calculate_core_trend_score(metrics, context)
    short = calculate_short_term_score(metrics, context)
    assert {item.dimension: item.max_score for item in core.dimensions} == {
        "price_structure": 25,
        "funds_and_turnover": 20,
        "industry_chain_breadth": 20,
        "core_weight_performance": 15,
        "fundamentals_and_cycle": 10,
        "events_and_policy": 10,
    }
    assert core.scoring_coverage_pct == 100
    assert short.scoring_coverage_pct == 100


def test_report_withholds_total_below_minimum_coverage():
    report = build_scored_report(_metrics())
    assert report.core_trend.score is None
    assert report.short_term.score is None
    assert report.core_trend.label == "INSUFFICIENT_DATA"
    assert report.core_trend.scoring_coverage_pct < 80


def test_backtest_feature_mode_keeps_partial_factors_outside_live_reports():
    live = build_scored_report(_metrics())
    research = build_scored_report(_metrics(), for_backtest_feature_generation=True)
    assert live.core_trend.score is None
    assert research.core_trend.score is not None
    assert research.core_trend.scoring_coverage_pct < 80


def test_conflict_detection_keeps_etf_and_sector_signals_separate():
    metrics = _metrics()
    etf = replace(metrics.etf, return_1d_pct=2.0, amount_vs_20d_avg=1.2)
    sector = replace(metrics.sector, index_weighted_return_pct=-1.0, amount_vs_20d_avg=0.8)
    report = build_scored_report(replace(metrics, etf=etf, sector=sector))
    assert "ETF_UP_SECTOR_NOT_UP" in report.conflicts
    assert "ETF_VOLUME_UP_SECTOR_VOLUME_DOWN" in report.conflicts


def test_json_and_markdown_share_scores_and_overwrite_is_protected(tmp_path):
    report = build_scored_report(_metrics(), _full_context())
    markdown = render_sector_fund_markdown(report)
    assert f"{report.core_trend.score:.2f}" in markdown
    assert f"{report.short_term.score:.2f}" in markdown
    assert "状态：未应用（NOT_APPLIED）" in markdown
    assert "概率输出：暂不可用（NOT_AVAILABLE）" in markdown
    paths = save_sector_fund_report(report, tmp_path / "report")
    payload = json.loads(paths["json"].read_text(encoding="utf-8"))
    assert payload["core_trend"]["score"] == report.core_trend.score
    assert paths["markdown"].read_text(encoding="utf-8") == markdown
    with pytest.raises(FileExistsError):
        save_sector_fund_report(report, tmp_path / "report")


def test_markdown_uses_the_fixed_fifteen_section_contract():
    markdown = render_sector_fund_markdown(build_scored_report(_metrics(), _full_context()))
    headings = [line for line in markdown.splitlines() if line.startswith("## ")]
    assert headings == [
        "## 1. 数据截止时间",
        "## 2. 数据源健康和缺失情况",
        "## 3. 基金正式净值或盘中估值",
        "## 4. 当日市场摘要",
        "## 5. 核心趋势评分",
        "## 6. 历史行情修正",
        "## 7. 短线强弱评分",
        "## 8. 六个核心模块明细",
        "## 9. 近7天重大消息",
        "## 10. 历史相似行情",
        "## 11. 未来1—3日情景",
        "## 12. 场外基金、场内ETF和核心股票工具判断",
        "## 13. 主要风险信号",
        "## 14. 下一交易日重点观察指标",
        "## 15. 数据冲突、缺失及总体置信度",
    ]
