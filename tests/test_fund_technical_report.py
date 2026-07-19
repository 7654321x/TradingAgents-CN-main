from __future__ import annotations

import json
from datetime import datetime
from types import SimpleNamespace

import pandas as pd
import pytest
from sqlalchemy.orm import Session

from tradingagents.analysis.fund_report import (
    REPORT_ALREADY_EXISTS,
    FundHoldingAnalysis,
    FundReportError,
    FundReportService,
    WeightedMetric,
    calculate_trading_return,
    classify_data_quality,
    classify_momentum,
    classify_overall,
    classify_trend,
    weighted_metric,
)
from tradingagents.reports.fund_technical_report import (
    render_fund_technical_report,
    save_fund_report,
)
from tradingagents.storage.db import get_engine, init_db
from tradingagents.storage.models import (
    FundHoldingPosition,
    FundHoldingReport,
    FundInstrumentRelation,
    Instrument,
    MarketBarObservation,
)


SYMBOLS = [
    "688409.SS",
    "688120.SS",
    "688012.SS",
    "002371.SZ",
    "688072.SS",
    "688361.SS",
    "688037.SS",
    "300567.SZ",
    "688652.SS",
    "688082.SS",
]
WEIGHTS = [9.34, 9.22, 9.06, 9.03, 8.90, 8.90, 8.89, 8.87, 7.59, 6.30]


def _seed_fund_database():
    engine = init_db(get_engine("sqlite://"))
    dates = pd.bdate_range("2024-01-02", periods=260)
    with Session(engine) as session:
        fund = Instrument(
            symbol="FUND:017811",
            local_code="017811",
            name="东方人工智能主题混合C",
            instrument_type="fund",
        )
        session.add(fund)
        session.flush()
        old = FundHoldingReport(
            fund_instrument_id=fund.id,
            report_period_end="2025-12-31",
            published_date="2026-01-20",
            holdings_count=1,
        )
        latest = FundHoldingReport(
            fund_instrument_id=fund.id,
            report_period_end="2026-03-31",
            published_date="2026-04-22",
            holdings_count=10,
        )
        session.add_all([old, latest])
        session.flush()
        now = datetime(2025, 1, 1)
        for rank, (symbol, weight) in enumerate(zip(SYMBOLS, WEIGHTS), 1):
            stock = Instrument(
                symbol=symbol,
                local_code=symbol.split(".")[0],
                name=f"股票{rank}",
                instrument_type="stock",
            )
            session.add(stock)
            session.flush()
            session.add(
                FundHoldingPosition(
                    report_id=latest.id,
                    stock_instrument_id=stock.id,
                    rank=rank,
                    weight_pct=weight,
                )
            )
            base = 50.0 + rank
            for row_number, date in enumerate(dates):
                close = base + row_number * (0.05 + rank * 0.001)
                session.add(
                    MarketBarObservation(
                        instrument_id=stock.id,
                        interval="1d",
                        bar_time=date.to_pydatetime(),
                        market_date=date.date().isoformat(),
                        open=close - 0.5,
                        high=close + 1.0,
                        low=close - 1.0,
                        close=close,
                        adjusted_close=close,
                        volume=100000 + row_number,
                        is_final=True,
                        provider="test",
                        upstream_group="test",
                        available_at=now,
                        fetched_at=now,
                        payload_hash=f"{rank}-{row_number}",
                        run_id="test",
                    )
                )
        for symbol in ("600519.SS", "300750.SZ"):
            session.add(
                Instrument(
                    symbol=symbol,
                    local_code=symbol.split(".")[0],
                    name="manual",
                    instrument_type="stock",
                )
            )
        session.commit()
    return engine, dates[-1].date().isoformat()


@pytest.fixture(scope="module")
def analyzed_result():
    engine, analysis_date = _seed_fund_database()
    with Session(engine) as session:
        result = FundReportService(session).analyze("017811", analysis_date)
    return engine, result


def _holding(weight=10.0, *, usable=True, status="SUCCESS", latest="2026-07-17"):
    return FundHoldingAnalysis(
        symbol="X.SS",
        name="X",
        rank=1,
        weight_pct=weight,
        latest_market_date=latest if usable else None,
        latest_close=10.0 if usable else None,
        data_status=status,
        momentum_status="NEUTRAL" if usable else "UNKNOWN",
    )


def test_loads_latest_fund_holding_report(analyzed_result):
    engine, result = analyzed_result
    with Session(engine) as session:
        _, report, _ = FundReportService(session)._load_fund("017811")
    assert report.report_period_end == "2026-03-31"
    assert result.published_date == "2026-04-22"


def test_holdings_are_not_hardcoded():
    engine = init_db(get_engine("sqlite://"))
    with Session(engine) as session:
        fund = Instrument(symbol="FUND:020671", local_code="020671", name="F", instrument_type="fund")
        stock = Instrument(symbol="CUSTOM.SS", local_code="CUSTOM", name="Custom", instrument_type="stock")
        session.add_all([fund, stock])
        session.flush()
        report = FundHoldingReport(fund_instrument_id=fund.id, report_period_end="2026-03-31", published_date="2026-04-01", holdings_count=1)
        session.add(report)
        session.flush()
        session.add(FundHoldingPosition(report_id=report.id, stock_instrument_id=stock.id, rank=1, weight_pct=8.0))
        session.commit()
        _, _, rows = FundReportService(session)._load_fund("020671")
    assert [item.symbol for _, item in rows] == ["CUSTOM.SS"]


def test_017811_contains_ten_holdings(analyzed_result):
    _, result = analyzed_result
    assert result.holding_count == 10
    assert [h.symbol for h in result.holdings] == SYMBOLS


def test_manual_test_symbols_are_excluded(analyzed_result):
    _, result = analyzed_result
    assert {h.symbol for h in result.holdings}.isdisjoint({"600519.SS", "300750.SZ"})


def test_return_uses_trading_rows():
    close = pd.Series([100.0, 101.0, 102.0, 110.0], index=pd.to_datetime(["2026-01-02", "2026-01-05", "2026-01-20", "2026-02-01"]))
    assert calculate_trading_return(close, 2) == pytest.approx((110 / 101 - 1) * 100)
    assert calculate_trading_return(close, 4) is None


def test_weighted_metric_uses_valid_weights():
    a = _holding(20)
    b = _holding(10)
    a.rsi14, b.rsi14 = 60.0, 30.0
    metric = weighted_metric([a, b], "rsi14", 30.0)
    assert metric.value == pytest.approx(50.0)


def test_missing_metric_is_not_treated_as_zero():
    a = _holding(20)
    b = _holding(10)
    a.rsi14, b.rsi14 = 60.0, None
    metric = weighted_metric([a, b], "rsi14", 30.0)
    assert metric.value == pytest.approx(60.0)


def test_weight_coverage_is_reported():
    a = _holding(20)
    b = _holding(10)
    a.rsi14, b.rsi14 = 60.0, None
    metric = weighted_metric([a, b], "rsi14", 30.0)
    assert metric.valid_holding_count == 1
    assert metric.valid_weight_pct == pytest.approx(20.0)
    assert metric.missing_weight_pct == pytest.approx(10.0)


def test_top3_and_top5_concentration(analyzed_result):
    _, result = analyzed_result
    assert result.top3_concentration_pct == pytest.approx(sum(sorted(WEIGHTS, reverse=True)[:3]))
    assert result.top5_concentration_pct == pytest.approx(sum(sorted(WEIGHTS, reverse=True)[:5]))


def test_hhi_uses_normalized_top10_weights(analyzed_result):
    _, result = analyzed_result
    expected = sum((weight / sum(WEIGHTS)) ** 2 for weight in WEIGHTS)
    assert result.herfindahl_index == pytest.approx(expected)


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ((120, 110, 100, 90), "STRONG_UPTREND"),
        ((105, 100, 90, None), "UPTREND"),
        ((80, 90, 100, 110), "STRONG_DOWNTREND"),
        ((95, 100, 110, None), "DOWNTREND"),
        ((100, 100, 90, 80), "NEUTRAL"),
    ],
)
def test_trend_classification(values, expected):
    assert classify_trend(*values) == expected


@pytest.mark.parametrize(
    ("rsi", "hist", "expected"),
    [(75, 1, "OVERBOUGHT"), (25, -1, "OVERSOLD"), (60, 1, "BULLISH"), (40, -1, "BEARISH"), (50, 0, "NEUTRAL")],
)
def test_momentum_classification(rsi, hist, expected):
    assert classify_momentum(rsi, hist) == expected


def test_data_quality_good():
    holdings = [_holding() for _ in range(10)]
    assert classify_data_quality(holdings, 100.0) == "GOOD"


def test_data_quality_partial():
    holdings = [_holding() for _ in range(7)] + [_holding(10, usable=False, status="FAILED") for _ in range(3)]
    assert classify_data_quality(holdings, 100.0) == "PARTIAL"


def test_data_quality_poor():
    holdings = [_holding() for _ in range(6)] + [_holding(10, usable=False, status="FAILED") for _ in range(4)]
    assert classify_data_quality(holdings, 100.0) == "POOR"


def test_single_holding_failure_does_not_abort_report(analyzed_result):
    engine, original = analyzed_result

    class OneFailureService(FundReportService):
        def _analyze_holding(self, position, stock, analysis_date):
            if position.rank == 1:
                return FundHoldingAnalysis(stock.symbol, stock.name, position.rank, position.weight_pct, data_status="FAILED", error_message="forced")
            return super()._analyze_holding(position, stock, analysis_date)

    with Session(engine) as session:
        result = OneFailureService(session).analyze("017811", original.analysis_date)
    assert result.holding_count == 10
    assert result.failed_count == 1
    assert result.successful_count == 9


def test_poor_data_blocks_overall_technical_status():
    metric = WeightedMetric(70.0, 7, 70.0, 30.0)
    hist = WeightedMetric(1.0, 7, 70.0, 30.0)
    assert classify_overall("POOR", metric, metric, metric, metric, metric, hist) == "INSUFFICIENT_DATA"


def test_report_contains_required_disclaimer(analyzed_result):
    text = render_fund_technical_report(analyzed_result[1])
    assert "本报告基于定期披露的前十大持仓，不代表基金当前完整持仓" in text
    assert "不是基金真实收益归因" in text
    assert "本报告不构成投资建议" in text


def test_report_contains_holding_table(analyzed_result):
    text = render_fund_technical_report(analyzed_result[1])
    assert "| 排名 | 代码 | 名称 |" in text
    assert all(symbol in text for symbol in SYMBOLS)


def test_report_contains_data_quality(analyzed_result):
    text = render_fund_technical_report(analyzed_result[1])
    assert "## 数据质量摘要" in text
    assert "数据质量状态：**GOOD**" in text


def test_report_contains_methodology(analyzed_result):
    text = render_fund_technical_report(analyzed_result[1])
    assert "## 方法说明" in text
    assert "缺失值不按 0 处理" in text
    assert "交易行" in text


def test_report_does_not_contain_buy_or_sell_advice(analyzed_result):
    text = render_fund_technical_report(analyzed_result[1])
    assert "买入" not in text
    assert "卖出" not in text


def test_json_and_markdown_use_same_result(analyzed_result, tmp_path):
    result = analyzed_result[1]
    json_path, markdown_path = save_fund_report(result, tmp_path)
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    markdown = markdown_path.read_text(encoding="utf-8")
    assert payload == result.to_dict()
    assert payload["fund"]["fund_code"] in markdown
    assert f"{payload['data_quality']['analyzed_weight_pct']:.2f}%" in markdown


def test_existing_report_requires_overwrite(analyzed_result, tmp_path):
    result = analyzed_result[1]
    save_fund_report(result, tmp_path)
    with pytest.raises(FundReportError) as exc:
        save_fund_report(result, tmp_path)
    assert exc.value.code == REPORT_ALREADY_EXISTS
    json_path, markdown_path = save_fund_report(result, tmp_path, overwrite=True)
    assert json_path.exists() and markdown_path.exists()


ACTIVE_025500 = [
    "001309.SZ", "301308.SZ", "688525.SS", "603986.SS", "300475.SZ",
    "300223.SZ", "688766.SS", "688416.SS", "688627.SS", "688008.SS",
]
ACTIVE_025500_WEIGHTS = [9.66, 9.03, 8.81, 8.80, 8.76, 7.97, 7.61, 6.14, 5.25, 5.00]
DIRECT_020671 = [
    "688521.SS", "688256.SS", "688072.SS", "688981.SS", "688041.SS",
    "688008.SS", "688012.SS", "688795.SS", "688234.SS", "688220.SS",
]
DIRECT_020671_WEIGHTS = [0.84, 0.33, 0.27, 0.26, 0.25, 0.21, 0.19, 0.19, 0.16, 0.13]


class _SyntheticFundReportService(FundReportService):
    """Avoid market/network access while testing fund-type orchestration."""

    def _analyze_holding(self, position, stock, analysis_date):
        proxy = stock.instrument_type == "etf"
        latest = 120.0 if proxy else 80.0
        item = FundHoldingAnalysis(
            symbol=stock.symbol,
            name=stock.name or stock.symbol,
            rank=position.rank,
            weight_pct=float(position.weight_pct or 0.0),
            daily_row_count=260,
            first_market_date="2025-01-01",
            latest_market_date=analysis_date,
            latest_close=latest,
            return_5d_pct=5.0 if proxy else -5.0,
            return_20d_pct=10.0 if proxy else -10.0,
            return_60d_pct=20.0 if proxy else -20.0,
            sma20=110.0 if proxy else 90.0,
            sma50=100.0,
            sma200=90.0 if proxy else 110.0,
            ema10=115.0 if proxy else 85.0,
            rsi14=60.0 if proxy else 40.0,
            macd=2.0 if proxy else -2.0,
            macd_signal=1.0 if proxy else -1.0,
            macd_histogram=1.0 if proxy else -1.0,
            atr14=3.0,
            atr_pct=2.5 if proxy else 3.75,
            boll_upper=125.0,
            boll_middle=110.0,
            boll_lower=95.0,
            price_vs_sma20_pct=(latest / (110.0 if proxy else 90.0) - 1) * 100,
            price_vs_sma50_pct=(latest / 100.0 - 1) * 100,
            price_vs_sma200_pct=(latest / (90.0 if proxy else 110.0) - 1) * 100,
            trend_status="STRONG_UPTREND" if proxy else "STRONG_DOWNTREND",
            momentum_status="BULLISH" if proxy else "BEARISH",
            data_status="SUCCESS",
            source="database",
            provider_call_count=0,
        )
        item.holding_return_contribution_proxy = item.weight_pct / 100 * item.return_20d_pct
        return item


def _seed_three_fund_metadata():
    engine = init_db(get_engine("sqlite://"))
    definitions = [
        ("017811", "东方人工智能主题混合C", SYMBOLS, WEIGHTS),
        ("025500", "东方阿尔法科技智选混合发起C", ACTIVE_025500, ACTIVE_025500_WEIGHTS),
        ("020671", "易方达上证科创板芯片ETF联接发起式C", DIRECT_020671, DIRECT_020671_WEIGHTS),
    ]
    with Session(engine) as session:
        instruments = {}

        def stock(symbol):
            if symbol not in instruments:
                instruments[symbol] = Instrument(
                    symbol=symbol,
                    local_code=symbol.split(".")[0],
                    name=symbol,
                    instrument_type="stock",
                )
                session.add(instruments[symbol])
                session.flush()
            return instruments[symbol]

        funds = {}
        for code, name, symbols, weights in definitions:
            fund = Instrument(symbol=f"FUND:{code}", local_code=code, name=name, instrument_type="fund")
            session.add(fund)
            session.flush()
            funds[code] = fund
            report = FundHoldingReport(
                fund_instrument_id=fund.id,
                report_period_end="2026-03-31",
                published_date="2026-04-22",
                holdings_count=10,
            )
            session.add(report)
            session.flush()
            for rank, (symbol, weight) in enumerate(zip(symbols, weights), 1):
                instrument = stock(symbol)
                session.add(FundHoldingPosition(report_id=report.id, stock_instrument_id=instrument.id, rank=rank, weight_pct=weight))
        proxy = Instrument(symbol="589130.SS", local_code="589130", name="易方达上证科创板芯片ETF", instrument_type="etf")
        session.add(proxy)
        session.flush()
        session.add(
            FundInstrumentRelation(
                fund_instrument_id=funds["020671"].id,
                related_instrument_id=proxy.id,
                relationship_type="target_etf",
                weight_pct=90.23,
                report_period_end="2026-03-31",
                published_date="2026-04-22",
            )
        )
        session.commit()
    return engine


@pytest.fixture(scope="module")
def three_fund_results():
    engine = _seed_three_fund_metadata()
    with Session(engine) as session:
        service = _SyntheticFundReportService(session)
        results = {code: service.analyze(code, "2026-07-17") for code in ("017811", "025500", "020671")}
    return engine, results


def test_025500_report_generates(three_fund_results, tmp_path):
    result = three_fund_results[1]["025500"]
    json_path, markdown_path = save_fund_report(result, tmp_path / "025500")
    assert json_path.exists() and markdown_path.exists()


def test_025500_loads_holdings_dynamically(three_fund_results):
    assert [h.symbol for h in three_fund_results[1]["025500"].holdings] == ACTIVE_025500


def test_025500_contains_ten_holdings(three_fund_results):
    assert three_fund_results[1]["025500"].holding_count == 10


def test_025500_weight_is_77_03(three_fund_results):
    assert three_fund_results[1]["025500"].top10_weight_pct == pytest.approx(77.03)


def test_025500_excludes_manual_test_symbols(three_fund_results):
    symbols = {h.symbol for h in three_fund_results[1]["025500"].holdings}
    assert symbols.isdisjoint({"600519.SS", "300750.SZ"})


def test_etf_feeder_detected(three_fund_results):
    assert three_fund_results[1]["020671"].fund_type == "etf_feeder"


def test_020671_loads_target_etf_relation(three_fund_results):
    proxy = three_fund_results[1]["020671"].proxy_analysis
    assert proxy is not None and proxy.relationship_type == "target_etf"


def test_020671_target_etf_is_589130(three_fund_results):
    assert three_fund_results[1]["020671"].proxy_analysis.symbol == "589130.SS"


def test_020671_proxy_weight_is_90_23(three_fund_results):
    assert three_fund_results[1]["020671"].proxy_analysis.weight_pct == pytest.approx(90.23)


def test_020671_direct_holding_weight_is_2_83(three_fund_results):
    assert three_fund_results[1]["020671"].top10_weight_pct == pytest.approx(2.83)


def test_etf_feeder_does_not_use_active_equity_aggregation(three_fund_results):
    result = three_fund_results[1]["020671"]
    assert result.overall_technical_status == result.proxy_analysis.technical_status == "BULLISH"
    assert result.bearish_weight_pct.value == pytest.approx(2.83)
    assert result.to_dict()["direct_holdings_analysis"]["scope"] == "direct_disclosed_stocks_only"


def test_etf_feeder_report_contains_proxy_section(three_fund_results):
    text = render_fund_technical_report(three_fund_results[1]["020671"])
    assert "## 目标 ETF 技术代理" in text and "589130.SS" in text


def test_etf_feeder_report_contains_direct_holdings_section(three_fund_results):
    text = render_fund_technical_report(three_fund_results[1]["020671"])
    assert "## 直接股票披露摘要" in text and "## 直接股票明细" in text


def test_etf_feeder_report_contains_required_disclaimer(three_fund_results):
    text = render_fund_technical_report(three_fund_results[1]["020671"])
    for phrase in ("本基金为 ETF 联接基金", "目标 ETF 是本报告的主要技术分析代理", "不代表基金主要持仓结构", "不构成投资建议"):
        assert phrase in text
    for forbidden in ("基金真实技术状态", "基金净值趋势", "基金投资评级"):
        assert forbidden not in text


def test_existing_017811_report_logic_unchanged(three_fund_results):
    result = three_fund_results[1]["017811"]
    assert result.fund_type == "active_equity"
    assert result.proxy_analysis is None
    assert "## 基于公开持仓的技术数据报告" in render_fund_technical_report(result)


def test_batch_report_failure_does_not_abort_other_funds(monkeypatch, capsys):
    from tradingagents.storage import cli

    calls = []
    result = SimpleNamespace(
        fund_type="active_equity",
        holding_count=10,
        successful_count=10,
        data_quality_status="GOOD",
    )

    def fake_run(engine, code, *args, **kwargs):
        calls.append(code)
        if code == "BAD":
            raise FundReportError("FUND_NOT_FOUND", code)
        return result, f"{code}.json", f"{code}.md"

    monkeypatch.setattr(cli, "_run_fund_report", fake_run)
    args = SimpleNamespace(fund_codes=["017811", "BAD", "025500"], analysis_date="2026-07-17", mode="database_only", overwrite=False)
    assert cli._generate_fund_reports(args, object()) == 1
    output = capsys.readouterr().out
    assert calls == ["017811", "BAD", "025500"]
    assert "017811\tactive_equity\tSUCCESS" in output
    assert "BAD\tunknown\tFAILED" in output
    assert "025500\tactive_equity\tSUCCESS" in output
