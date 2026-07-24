from __future__ import annotations

import sys
from datetime import datetime
from types import SimpleNamespace

import pandas as pd
from sqlalchemy.orm import Session

from tradingagents.extensions.sector_fund.akshare_enrichment import (
    fetch_financial_indicators,
    fetch_industry_cycle_board,
    normalize_financial_indicator,
)
from tradingagents.extensions.sector_fund.analysis_enrichment import (
    breadth_extensions,
    daily_price_structure,
    intraday_tail_metrics,
)
from tradingagents.extensions.sector_fund.company_fundamental_extractor import (
    extract_company_fundamental_facts,
)
from tradingagents.extensions.sector_fund.daily_sync import (
    _retry_fetch,
    _store_company_event_discovery,
    _store_web_discovery,
)
from tradingagents.extensions.sector_fund.data_observation_store import (
    latest_observations,
    save_observation,
)
from tradingagents.extensions.sector_fund.firecrawl_resolver import FirecrawlEastmoneyResolver
from tradingagents.extensions.sector_fund.firecrawl_search import FirecrawlSearchDocumentResolver
from tradingagents.extensions.sector_fund.industry_cycle_extractor import (
    extract_industry_cycle_facts,
)
from tradingagents.extensions.sector_fund.mcp_observation_store import (
    latest_mcp_observations,
    save_mcp_observation,
)
from tradingagents.extensions.sector_fund.web_fallback import (
    current_bar_frame,
    resolve_current_daily_bar,
    resolve_structured_fallback,
)
from tradingagents.storage.db import get_engine, init_db
from tradingagents.storage.models import FundDataObservation, Instrument, McpWebObservation


def _frame(rows=70):
    index = pd.bdate_range("2026-04-01", periods=rows)
    close = pd.Series(range(100, 100 + rows), index=index, dtype=float)
    return pd.DataFrame({"Open": close - 1, "High": close + 2, "Low": close - 2, "Close": close, "Volume": 1000.0, "Amount": 10000.0}, index=index)


def test_structure_and_breadth_are_derived_without_predictions():
    frame = _frame()
    structure = daily_price_structure(frame)
    breadth = breadth_extensions({"A.SS": frame}, [{"symbol": "A.SS", "weight_pct": 100}], frame.index[-1].date().isoformat(), 0.1)
    assert structure["status"] == "SUCCESS"
    assert structure["support_20d"] is not None
    assert breadth["available_count"] == 1
    assert breadth["return_median_pct"] is not None


def test_breadth_excludes_constituents_without_the_requested_market_date():
    current = _frame()
    stale = current.iloc[:-2]
    analysis_date = current.index[-1].date().isoformat()

    breadth = breadth_extensions(
        {"A.SS": current, "B.SS": stale},
        [{"symbol": "A.SS", "weight_pct": 50}, {"symbol": "B.SS", "weight_pct": 50}],
        analysis_date,
        0.1,
    )

    assert breadth["status"] == "INSUFFICIENT_COVERAGE"
    assert breadth["available_count"] == 1
    assert breadth["stale_symbols"] == ["B.SS"]


def test_intraday_tail_is_only_a_descriptive_metric():
    index = pd.date_range("2026-07-22 14:30", periods=7, freq="5min")
    frame = pd.DataFrame({"Open": [10] * 7, "High": [11] * 7, "Low": [9] * 7, "Close": [10.5] * 7, "Amount": [100] * 7}, index=index)
    result = intraday_tail_metrics(frame, as_of=datetime(2026, 7, 22, 15, 0))
    assert result["status"] == "SUCCESS"
    assert result["tail_30m_amount"] == 700.0


def test_observation_store_deduplicates_and_records_source_metadata():
    engine = init_db(get_engine("sqlite://"))
    with Session(engine) as session:
        observed_at = datetime(2026, 7, 22, 12)
        assert save_observation(session, dataset_type="fund_flow", field_name="main", value={"x": 1}, source_level="B", source="akshare", source_url="https://example.com", confirmation_status="THIRD_PARTY", applicable_date="2026-07-22", available_at=observed_at, fetched_at=observed_at)
        assert not save_observation(session, dataset_type="fund_flow", field_name="main", value={"x": 1}, source_level="B", source="akshare", source_url="https://example.com", confirmation_status="THIRD_PARTY", applicable_date="2026-07-22", available_at=observed_at, fetched_at=observed_at)
        session.commit()
        rows = latest_observations(
            session,
            dataset_type="fund_flow",
            analysis_date="2026-07-23",
            fund_code="020671",
        )
    assert rows[0]["source_level"] == "B"


def test_observation_store_records_provider_failure_for_a_specific_security():
    engine = init_db(get_engine("sqlite://"))
    with Session(engine) as session:
        session.add(Instrument(symbol="688001.SS", local_code="688001", name="测试", instrument_type="stock"))
        session.flush()
        assert save_observation(
            session,
            dataset_type="fund_flow",
            field_name="individual_main_flow",
            value={"status": "FAILED"},
            source_level="B",
            source="akshare_eastmoney",
            source_url=None,
            confirmation_status="UNAVAILABLE",
            applicable_date="2026-07-22",
            instrument_symbol="688001.SS",
            status="FAILED",
            error_message="TimeoutError: provider timeout",
        )
        session.commit()
        row = session.query(FundDataObservation).one()

    assert row.status == "FAILED"
    assert row.error_message == "TimeoutError: provider timeout"


def test_observation_lookup_is_scoped_to_fund_and_available_time():
    engine = init_db(get_engine("sqlite://"))
    with Session(engine) as session:
        observed_at = datetime(2026, 7, 22, 12)
        for code, value in (("020671", 1), ("999999", 2)):
            save_observation(
                session,
                dataset_type="news_lead",
                field_name="headline",
                value={"value": value},
                source_level="C",
                source="test",
                source_url="https://example.test",
                confirmation_status="MEDIA_REPORTED_NOT_OFFICIALLY_CONFIRMED",
                applicable_date="2026-07-22",
                fund_code=code,
                available_at=observed_at,
                fetched_at=observed_at,
            )
        session.commit()
        rows = latest_observations(
            session,
            dataset_type="news_lead",
            analysis_date="2026-07-23",
            fund_code="020671",
        )

    assert [item["value"] for item in rows] == [{"value": 1}]


def test_observation_lookup_returns_the_security_symbol_for_coverage_audits():
    engine = init_db(get_engine("sqlite://"))
    with Session(engine) as session:
        session.add(Instrument(symbol="688001.SS", local_code="688001", name="测试", instrument_type="stock"))
        session.flush()
        timestamp = datetime(2026, 7, 22, 12)
        save_observation(
            session,
            dataset_type="financial",
            field_name="latest_financial_indicator",
            value={"value": 1},
            source_level="B",
            source="akshare",
            source_url=None,
            confirmation_status="THIRD_PARTY",
            applicable_date="2026-07-22",
            instrument_symbol="688001.SS",
            available_at=timestamp,
            fetched_at=timestamp,
        )
        session.commit()
        rows = latest_observations(
            session, dataset_type="financial", analysis_date="2026-07-23", fund_code="020671"
        )
    assert rows[0]["instrument_symbol"] == "688001.SS"


def test_web_fallback_only_admits_structured_a_or_b_sources():
    class Resolver:
        def resolve(self, query, allowed_domains):
            return [
                {"source_level": "C", "source_url": "https://media.example", "payload": {"x": 1}},
                {"source_level": "A", "source_url": "https://official.example", "payload": {"x": 2}},
            ]

    result = resolve_structured_fallback(Resolver(), query="test", allowed_domains=("official.example",))
    assert result.status == "SUCCESS"
    assert result.source_level == "A"


def test_financial_adapter_maps_internal_shanghai_suffix(monkeypatch):
    seen = {}
    monkeypatch.setitem(sys.modules, "akshare", SimpleNamespace(stock_financial_analysis_indicator_em=lambda **kwargs: seen.update(kwargs) or pd.DataFrame()))
    fetch_financial_indicators("688981.SS")
    assert seen["symbol"] == "688981.SH"


def test_financial_normalizer_maps_known_aliases_and_preserves_missing_fields():
    normalized = normalize_financial_indicator(
        {
            "REPORT_DATE": "2026-03-31",
            "NOTICE_DATE": "2026-04-28",
            "TOTAL_OPERATE_INCOME": "120.5",
            "PARENT_NETPROFIT": "20.1",
            "GROSS_PROFIT_MARGIN": "48.2",
            "RD_EXPENSE": "10",
        }
    )
    assert normalized["report_date"] == "2026-03-31"
    assert normalized["metrics"]["revenue"] == 120.5
    assert normalized["metrics"]["net_profit"] == 20.1
    assert normalized["metrics"]["gross_margin_pct"] == 48.2
    assert normalized["metrics"]["inventory"] is None
    assert normalized["available_metric_count"] == 4


def test_industry_cycle_board_adapter_returns_dated_market_proxy(monkeypatch):
    class Adapter:
        @staticmethod
        def stock_board_industry_name_em():
            return pd.DataFrame({"板块名称": ["半导体", "汽车"]})

        @staticmethod
        def stock_board_industry_hist_em(**kwargs):
            dates = pd.bdate_range("2026-06-01", periods=25)
            return pd.DataFrame({"日期": dates, "收盘": range(100, 125), "成交额": [1000] * 25})

    monkeypatch.setitem(sys.modules, "akshare", Adapter())
    result = fetch_industry_cycle_board("半导体", "2026-06-01", "2026-07-22")
    assert result["status"] == "SUCCESS"
    assert result["board_name"] == "半导体"
    assert result["market_date"] == "2026-07-03"
    assert result["return_20d_pct"] is not None


def test_mcp_documents_use_a_dedicated_table_not_akshare_or_derived_observations():
    engine = init_db(get_engine("sqlite://"))
    with Session(engine) as session:
        assert save_mcp_observation(
            session, dataset_type="current_daily_market", field_name="daily_bar",
            payload={"bar": {"Date": "2026-07-22", "Open": 1, "High": 2, "Low": 1, "Close": 1.5, "Volume": 100}},
            source_level="B", source="mcp_web_resolver", source_url="https://quote.eastmoney.com/test",
            confirmation_status="VERIFIED_WEB_SOURCE", applicable_date="2026-07-22",
            available_at=datetime(2026, 7, 22, 12), fetched_at=datetime(2026, 7, 22, 12),
        )
        session.commit()
        assert session.query(McpWebObservation).count() == 1
        assert session.query(FundDataObservation).count() == 0
        rows = latest_mcp_observations(
            session,
            dataset_type="current_daily_market",
            analysis_date="2026-07-23",
            fund_code="020671",
        )
    assert rows[0]["source_url"] == "https://quote.eastmoney.com/test"


def test_mcp_lookup_prevents_future_document_from_entering_historic_report():
    engine = init_db(get_engine("sqlite://"))
    with Session(engine) as session:
        assert save_mcp_observation(
            session,
            dataset_type="industry_cycle_web_discovery",
            field_name="original_page_document",
            payload={"source_document": {"markdown": "future"}},
            source_level="A",
            source="firecrawl_search",
            source_url="https://www.stats.gov.cn/test",
            confirmation_status="DISCOVERED_REQUIRES_STRUCTURED_VALIDATION",
            applicable_date="2026-07-22",
        )
        session.flush()
        row = session.query(McpWebObservation).one()
        row.available_at = datetime(2026, 7, 23)
        session.commit()
        rows = latest_mcp_observations(
            session,
            dataset_type="industry_cycle_web_discovery",
            analysis_date="2026-07-22",
            fund_code="020671",
        )
    assert rows == []


def test_firecrawl_search_resolver_keeps_only_allowed_original_documents():
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "success": True,
                "data": [
                    {
                        "url": "https://www.stats.gov.cn/data.html",
                        "markdown": "# 集成电路产量\n2026年数据",
                        "metadata": {"sourceURL": "https://www.stats.gov.cn/data.html"},
                    },
                    {"url": "https://untrusted.example/data", "markdown": "untrusted"},
                    {"url": "https://www.stats.gov.cn/empty", "markdown": ""},
                ],
            }

    class Session:
        def post(self, *args, **kwargs):
            return Response()

    resolver = FirecrawlSearchDocumentResolver(
        api_key="test",
        session=Session(),
        official_domains=("stats.gov.cn",),
    )
    rows = resolver.resolve("集成电路产量", ("stats.gov.cn", "eastmoney.com"))
    assert len(rows) == 1
    assert rows[0]["source_level"] == "A"
    assert rows[0]["payload"]["source_document"]["markdown"].startswith("# 集成电路")


def test_firecrawl_search_resolver_preserves_c_level_as_lead_only():
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "success": True,
                "data": [{"url": "https://www.stcn.com/article", "markdown": "媒体报道"}],
            }

    class Session:
        def post(self, *args, **kwargs):
            return Response()

    resolver = FirecrawlSearchDocumentResolver(
        api_key="test", session=Session(), lead_domains=("stcn.com",)
    )
    rows = resolver.resolve("半导体", ("stcn.com",))
    assert rows[0]["source_level"] == "C"


def test_industry_cycle_extractor_requires_value_period_publication_date_and_evidence():
    payload = {
        "source_document": {
            "markdown": "发布时间：2026年7月18日\n2026年1—6月，全国集成电路产量为2395.0亿块，同比增长。",
            "metadata": {"sourceURL": "https://www.stats.gov.cn/data.html"},
        }
    }
    facts = extract_industry_cycle_facts(
        source_url="https://www.stats.gov.cn/data.html", source_level="A", payload=payload
    )
    assert len(facts) == 1
    assert facts[0].metric_name == "integrated_circuit_output"
    assert facts[0].value == 2395.0
    assert facts[0].period == "2026年1—6月"
    assert facts[0].published_date == "2026-07-18"


def test_industry_cycle_extractor_rejects_undated_or_c_level_documents():
    payload = {"source_document": {"markdown": "2026年1—6月集成电路产量2395亿块", "metadata": {}}}
    assert extract_industry_cycle_facts(
        source_url="https://www.stats.gov.cn/data.html", source_level="A", payload=payload
    ) == ()
    assert extract_industry_cycle_facts(
        source_url="https://example.media/data.html", source_level="C", payload=payload
    ) == ()


def test_industry_cycle_extractor_reads_miit_output_trade_and_industry_metrics():
    payload = {
        "source_document": {
            "markdown": (
                "发布时间：2026-06-30 18:45\n"
                "2026年1-5月，规模以上电子信息制造业增加值同比增长14.6%。"
                "集成电路产量2286亿块，同比增长25.4%。"
                "出口集成电路1478亿个，同比增长8.7%。"
                "电子信息制造业实现营业收入7.52万亿元，同比增长17.1%。"
            ),
            "metadata": {},
        }
    }
    facts = extract_industry_cycle_facts(
        source_url="https://www.miit.gov.cn/example", source_level="A", payload=payload
    )
    by_metric = {item.metric_name: item for item in facts}
    assert by_metric["integrated_circuit_output"].value == 2286
    assert by_metric["integrated_circuit_exports"].unit == "亿个"
    assert by_metric["electronic_information_value_added_yoy"].value == 14.6
    assert by_metric["electronic_information_revenue"].unit == "万亿元"


def test_retry_fetch_retries_empty_and_transient_provider_results():
    calls = []

    def fetch():
        calls.append(len(calls))
        if len(calls) == 1:
            return pd.DataFrame()
        return pd.DataFrame({"value": [1]})

    result = _retry_fetch(fetch)
    assert len(calls) == 2
    assert result.iloc[0]["value"] == 1


def test_company_fundamental_extractor_requires_dated_periodic_original_evidence():
    payload = {
        "source_document": {
            "markdown": (
                "发布时间：2026年4月28日\n"
                "2026年一季度，公司实现营业收入120.5亿元，归母净利润20.1亿元，毛利率48.2%。"
            ),
            "metadata": {},
        }
    }
    facts = extract_company_fundamental_facts(
        source_url="https://www.cninfo.com.cn/example", source_level="A", payload=payload
    )
    by_metric = {fact.metric_name: fact for fact in facts}
    assert by_metric["revenue"].value == 120.5
    assert by_metric["net_profit"].unit == "亿元"
    assert by_metric["gross_margin_pct"].value == 48.2
    assert by_metric["revenue"].report_period == "2026年一季度"


def test_company_fundamental_extractor_rejects_missing_report_period():
    payload = {
        "source_document": {
            "markdown": "发布时间：2026年4月28日\n公司实现营业收入120.5亿元。",
            "metadata": {},
        }
    }
    assert extract_company_fundamental_facts(
        source_url="https://www.cninfo.com.cn/example", source_level="A", payload=payload
    ) == ()


def test_company_event_discovery_stores_c_level_only_as_news_lead():
    class Resolver:
        last_error = None

        def resolve(self, query, allowed_domains):
            return [
                {
                    "source_level": "C",
                    "source_url": "https://www.stcn.com/article",
                    "payload": {
                        "source_document": {
                            "markdown": "媒体报道正文",
                            "metadata": {"title": "媒体标题"},
                        }
                    },
                }
            ]

    engine = init_db(get_engine("sqlite://"))
    with Session(engine) as session:
        inserted = _store_company_event_discovery(
            session,
            fund_code="020671",
            analysis_date="2026-07-22",
            query="测试公告",
            resolver=Resolver(),
        )
        session.commit()
        raw = session.query(McpWebObservation).one()
        lead = session.query(FundDataObservation).one()

    assert inserted == 2
    assert raw.confirmation_status == "MEDIA_LEAD_ONLY"
    assert lead.dataset_type == "news_lead"
    assert lead.source_level == "C"


def test_financial_web_discovery_persists_raw_page_and_only_validated_facts(monkeypatch):
    class Resolver:
        last_error = None

        def resolve(self, query, allowed_domains):
            return [
                {
                    "source_level": "A",
                    "source_url": "https://www.cninfo.com.cn/example",
                    "payload": {
                        "source_document": {
                            "markdown": (
                                "发布时间：2026年4月28日\n"
                                "2026年一季度，公司实现营业收入120.5亿元，归母净利润20.1亿元。"
                            ),
                            "metadata": {},
                        }
                    },
                }
            ]

    monkeypatch.setattr(
        "tradingagents.extensions.sector_fund.daily_sync.build_firecrawl_search_resolver_from_env",
        lambda **kwargs: Resolver(),
    )
    engine = init_db(get_engine("sqlite://"))
    with Session(engine) as session:
        session.add(Instrument(symbol="688001.SS", local_code="688001", name="测试", instrument_type="stock"))
        session.flush()
        inserted = _store_web_discovery(
            session,
            dataset_type="financial_web_discovery",
            query="测试财务公告",
            analysis_date="2026-07-22",
            instrument_symbol="688001.SS",
        )
        session.commit()
        raw_count = session.query(McpWebObservation).count()
        facts = session.query(FundDataObservation).all()

    assert inserted == 3
    assert raw_count == 1
    assert {fact.field_name for fact in facts} == {"web_revenue", "web_net_profit"}
    assert all(fact.confirmation_status == "VERIFIED_STRUCTURED_ORIGINAL_PAGE" for fact in facts)


def test_current_daily_bar_requires_allowed_original_page_and_valid_ohlcv():
    class Resolver:
        def resolve(self, query, allowed_domains):
            return [{
                "source_level": "B", "source_url": "https://quote.eastmoney.com/589130.html",
                "payload": {"bar": {"Date": "2026-07-22", "Open": "1.00", "High": "1.03", "Low": "0.98", "Close": "1.02", "Volume": "100", "Amount": "102"}},
            }]

    result = resolve_current_daily_bar(
        Resolver(), symbol="589130.SS", analysis_date="2026-07-22", allowed_domains=("eastmoney.com",)
    )
    assert result.status == "SUCCESS"
    assert current_bar_frame(result).iloc[0]["Close"] == 1.02


def test_current_daily_bar_rejects_unlisted_domain():
    class Resolver:
        def resolve(self, query, allowed_domains):
            return [{
                "source_level": "B", "source_url": "https://untrusted.example/589130.html",
                "payload": {"bar": {"Date": "2026-07-22", "Open": 1, "High": 2, "Low": 1, "Close": 1.5, "Volume": 100}},
            }]

    result = resolve_current_daily_bar(
        Resolver(), symbol="589130.SS", analysis_date="2026-07-22", allowed_domains=("eastmoney.com",)
    )
    assert result.status == "UNAVAILABLE_FROM_ALLOWED_WEB_SOURCES"


def test_firecrawl_resolver_retries_fresh_page_after_invalid_quote_response():
    class Response:
        def __init__(self, body):
            self.body = body

        def raise_for_status(self):
            return None

        def json(self):
            return self.body

    class Session:
        def __init__(self):
            self.calls = []
            self.responses = [
                {"success": True, "data": {"json": {"open": 1.0}, "markdown": ""}},
                {"success": True, "data": {
                    "json": {"name": "测试ETF", "open": 1.0, "high": 1.2, "low": 0.9, "close_or_latest_price": 1.1, "volume": 100, "amount": 11000, "trading_status": "闭市"},
                    "markdown": "行情指标 2026-07-22 16:20:00 闭市",
                    "metadata": {"sourceURL": "https://quote.eastmoney.com/sh589130.html"},
                }},
            ]

        def post(self, url, **kwargs):
            self.calls.append((url, kwargs))
            return Response(self.responses.pop(0))

    session = Session()
    resolver = FirecrawlEastmoneyResolver(api_key="test", session=session, retries_per_url=2)
    rows = resolver.resolve("589130.SS 2026-07-22 日线 开盘 最高 最低 收盘 成交量 成交额", ("eastmoney.com",))
    assert len(session.calls) == 2
    assert rows[0]["payload"]["bar"]["Close"] == 1.1
    assert rows[0]["payload"]["trading_status"] == "闭市"
    assert len(rows[0]["payload"]["fetch_attempts"]) == 1
    assert resolver._urls("589130", "SS")[-1] == "https://stockpage.10jqka.com.cn/589130/"


def test_firecrawl_quote_normalizes_chinese_amount_unit_and_rejects_lost_unit():
    valid = FirecrawlEastmoneyResolver._bar(
        {
            "open": 100,
            "high": 110,
            "low": 99,
            "close_or_latest_price": 105,
            "volume_raw": "100万",
            "amount_raw": "105亿",
        },
        "2026-07-22",
    )
    invalid = FirecrawlEastmoneyResolver._bar(
        {
            "open": 100,
            "high": 110,
            "low": 99,
            "close_or_latest_price": 105,
            "volume": 1_000_000,
            "amount": 105,
        },
        "2026-07-22",
    )

    assert valid is not None
    assert valid["Amount"] == 10_500_000_000
    assert invalid is None


def test_firecrawl_resolver_tries_fallback_page_when_primary_lacks_close_status():
    class Response:
        def __init__(self, body):
            self.body = body

        def raise_for_status(self):
            return None

        def json(self):
            return self.body

    class Session:
        def __init__(self):
            self.calls = []
            no_status = {
                "success": True,
                "data": {
                    "json": {
                        "open": 1.0, "high": 1.2, "low": 0.9,
                        "close_or_latest_price": 1.1, "volume": 100, "amount": 11000,
                    },
                    "markdown": "行情指标 2026-07-22 16:20:00",
                },
            }
            closed = {
                "success": True,
                "data": {
                    "json": {
                        "open": 1.0, "high": 1.2, "low": 0.9,
                        "close_or_latest_price": 1.1, "volume": 100, "amount": 11000,
                        "trading_status": "已收盘",
                    },
                    "markdown": "行情指标 2026-07-22 16:20:00 已收盘",
                    "metadata": {"sourceURL": "https://stockpage.10jqka.com.cn/589130/"},
                },
            }
            self.responses = [no_status, no_status, closed]

        def post(self, url, **kwargs):
            self.calls.append((url, kwargs))
            return Response(self.responses.pop(0))

    resolver = FirecrawlEastmoneyResolver(api_key="test", session=Session(), retries_per_url=2)
    rows = resolver.resolve("589130.SS 2026-07-22 日线 开盘 最高 最低 收盘 成交量 成交额", ("eastmoney.com", "10jqka.com.cn"))

    assert rows[0]["source_url"] == "https://stockpage.10jqka.com.cn/589130/"
    assert rows[0]["payload"]["trading_status"] == "已收盘"
    assert [item["error"] for item in rows[0]["payload"]["fetch_attempts"]] == [
        "MISSING_TRADING_STATUS", "MISSING_TRADING_STATUS"
    ]


def test_close_mode_requires_source_close_confirmation():
    class Resolver:
        def resolve(self, query, allowed_domains):
            return [{
                "source_level": "B", "source_url": "https://quote.eastmoney.com/sh589130.html",
                "payload": {"bar": {"Date": "2026-07-22", "Open": 1, "High": 2, "Low": 1, "Close": 1.5, "Volume": 100}},
            }]

    result = resolve_current_daily_bar(
        Resolver(), symbol="589130.SS", analysis_date="2026-07-22", allowed_domains=("eastmoney.com",),
        require_close_confirmation=True,
    )
    assert result.status == "CLOSE_CONFIRMATION_REQUIRED"
