"""On-demand incremental refresh used before a user-requested 020671 analysis."""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tradingagents.extensions.fund_agent.profile_registry import resolve_fund_analysis_profile
from tradingagents.storage.data_service import SUCCESS, MarketDataService
from tradingagents.storage.models import (
    FundMetadataSnapshot,
    Instrument,
    InstrumentClassificationSnapshot,
    Universe,
    UniverseConstituentWeight,
    UniverseSnapshot,
)
from tradingagents.storage.repository import MarketBarRepository

from .akshare_enrichment import (
    fetch_financial_indicators,
    fetch_individual_fund_flow,
    fetch_industry_cycle_board,
    normalize_financial_indicator,
)
from .akshare_market_provider import get_auto_daily_frame
from .analysis_enrichment import breadth_extensions, daily_price_structure, top_weight_snapshot
from .baseline import ingest_etf_status_snapshot, ingest_official_nav_history
from .classification import CSI_SCHEME, ingest_classification_snapshots
from .company_fundamental_extractor import extract_company_fundamental_facts
from .csindex_industry_provider import fetch_csindex_industry_classifications
from .data_observation_store import save_observation
from .efunds_provider import fetch_efunds_nav_history
from .etf_status_provider import fetch_etf_status
from .event_store import sync_fund_events
from .firecrawl_resolver import build_firecrawl_resolver_from_env
from .firecrawl_search import build_firecrawl_search_resolver_from_env
from .industry_cycle_extractor import extract_industry_cycle_facts
from .mcp_observation_store import save_mcp_observation
from .source_policy import source_policy_for
from .web_fallback import WebResolver, current_bar_frame, resolve_current_daily_bar

MARKET_WEB_DOMAINS = source_policy_for("current_daily_market").allowed_domains
FINANCIAL_WEB_DOMAINS = ("cninfo.com.cn", "sse.com.cn", "szse.cn", "eastmoney.com", "10jqka.com.cn")
EVENT_OFFICIAL_DOMAINS = ("cninfo.com.cn", "sse.com.cn", "szse.cn", "csrc.gov.cn", "miit.gov.cn")
EVENT_PLATFORM_DOMAINS = ("eastmoney.com", "10jqka.com.cn")
EVENT_LEAD_DOMAINS = ("stcn.com", "yicai.com", "caixin.com", "reuters.com")


def _failure(exc: Exception) -> dict[str, Any]:
    return {"status": "FAILED", "error": f"{type(exc).__name__}: {exc}"}


def _retry_fetch(fetch, *, attempts: int = 2):
    """Retry transient public-provider errors without hiding the final cause."""
    error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            result = fetch()
            if result is None or getattr(result, "empty", False):
                raise ValueError("provider returned an empty result")
            return result
        except Exception as exc:
            error = exc
            if attempt < attempts:
                time.sleep(0.25 * attempt)
    assert error is not None
    raise error


def _store_web_discovery(
    session: Session,
    *,
    dataset_type: str,
    query: str,
    analysis_date: str,
    instrument_symbol: str,
) -> int:
    """Persist A/B original pages after an API failure, never parsed values."""
    resolver = build_firecrawl_search_resolver_from_env(
        official_domains=("cninfo.com.cn", "sse.com.cn", "szse.cn")
    )
    documents = resolver.resolve(query, FINANCIAL_WEB_DOMAINS) if resolver else []
    if documents:
        inserted = 0
        for document in documents:
            inserted += save_mcp_observation(
                session,
                dataset_type=dataset_type,
                field_name="original_page_document",
                payload=document["payload"],
                source_level=document["source_level"],
                source="firecrawl_search",
                source_url=document["source_url"],
                confirmation_status="DISCOVERED_REQUIRES_STRUCTURED_VALIDATION",
                applicable_date=analysis_date,
                instrument_symbol=instrument_symbol,
                status="SUCCESS",
            )
            if dataset_type == "financial_web_discovery":
                for fact in extract_company_fundamental_facts(
                    source_url=document["source_url"],
                    source_level=document["source_level"],
                    payload=document["payload"],
                ):
                    inserted += save_observation(
                        session,
                        dataset_type="financial",
                        field_name=f"web_{fact.metric_name}",
                        value=fact.to_dict(),
                        source_level=fact.source_level,
                        source="firecrawl_search_original_page",
                        source_url=fact.source_url,
                        confirmation_status="VERIFIED_STRUCTURED_ORIGINAL_PAGE",
                        applicable_date=analysis_date,
                        published_date=fact.published_date,
                        instrument_symbol=instrument_symbol,
                    )
        return inserted
    return int(
        save_mcp_observation(
            session,
            dataset_type=dataset_type,
            field_name="original_page_document",
            payload=None,
            source_level="UNVERIFIED",
            source="firecrawl_search",
            source_url=None,
            confirmation_status="UNAVAILABLE",
            applicable_date=analysis_date,
            instrument_symbol=instrument_symbol,
            status="FAILED",
            error_message=(resolver.last_error if resolver else "FIRECRAWL_API_KEY is not configured"),
        )
    )


def _store_company_event_discovery(
    session: Session,
    *,
    fund_code: str,
    analysis_date: str,
    query: str,
    resolver=None,
) -> int:
    """Store raw event pages; C-level pages remain non-scoring leads."""
    resolver = resolver or build_firecrawl_search_resolver_from_env(
        official_domains=EVENT_OFFICIAL_DOMAINS,
        platform_domains=EVENT_PLATFORM_DOMAINS,
        lead_domains=EVENT_LEAD_DOMAINS,
    )
    allowed_domains = (*EVENT_OFFICIAL_DOMAINS, *EVENT_PLATFORM_DOMAINS, *EVENT_LEAD_DOMAINS)
    documents = resolver.resolve(query, allowed_domains) if resolver else []
    inserted = 0
    for document in documents:
        level = document["source_level"]
        inserted += save_mcp_observation(
            session,
            dataset_type="company_event_web_discovery",
            field_name="original_page_document",
            payload=document["payload"],
            source_level=level,
            source="firecrawl_search",
            source_url=document["source_url"],
            confirmation_status=(
                "MEDIA_LEAD_ONLY" if level == "C" else "DISCOVERED_REQUIRES_STRUCTURED_VALIDATION"
            ),
            applicable_date=analysis_date,
            fund_code=fund_code,
            status="SUCCESS",
        )
        if level == "C":
            document_body = document["payload"].get("source_document", {})
            metadata = document_body.get("metadata", {}) if isinstance(document_body, dict) else {}
            inserted += save_observation(
                session,
                dataset_type="news_lead",
                field_name="company_event_headline",
                value={
                    "title": metadata.get("title"),
                    "url": document["source_url"],
                    "search_query": query,
                },
                source_level="C",
                source="firecrawl_search",
                source_url=document["source_url"],
                confirmation_status="MEDIA_REPORTED_NOT_OFFICIALLY_CONFIRMED",
                applicable_date=analysis_date,
                fund_code=fund_code,
            )
    if documents:
        return inserted
    return int(
        save_mcp_observation(
            session,
            dataset_type="company_event_web_discovery",
            field_name="original_page_document",
            payload=None,
            source_level="UNVERIFIED",
            source="firecrawl_search",
            source_url=None,
            confirmation_status="UNAVAILABLE",
            applicable_date=analysis_date,
            fund_code=fund_code,
            status="FAILED",
            error_message=(resolver.last_error if resolver else "FIRECRAWL_API_KEY is not configured"),
        )
    )


def _resolve_analysis_mode(analysis_date: str, requested_mode: str) -> str:
    if requested_mode != "auto":
        return requested_mode
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    if analysis_date == now.date().isoformat() and now.hour < 16:
        return "intraday"
    return "close"


def refresh_020671_on_demand(
    engine, *, analysis_date: str, analysis_mode: str = "auto", web_resolver: WebResolver | None = None,
) -> dict[str, Any]:
    """Refresh cache incrementally without changing scores or backtests.

    A verified metadata/universe snapshot must already exist.  This prevents a
    current constituent list being written as if it were valid for a historic
    user-requested date.
    """
    resolved_mode = _resolve_analysis_mode(analysis_date, analysis_mode)
    web_resolver = web_resolver or build_firecrawl_resolver_from_env()
    result: dict[str, Any] = {"analysis_date": analysis_date, "mode": "ON_DEMAND_INCREMENTAL", "analysis_mode": resolved_mode}
    today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
    requested_date = pd.Timestamp(analysis_date).date()
    if requested_date > today:
        return {**result, "market_data": {"status": "INVALID_FUTURE_DATE", "message": "不能分析未来交易日"}}
    # AKShare and its fallbacks are historical-only.  Today's raw bar is read
    # through the isolated MCP document path below, never persisted to the
    # AKShare/history market-bar table.
    is_current_day = requested_date == today
    historical_end_date = (today - timedelta(days=1)).isoformat() if is_current_day else analysis_date
    mcp_current_frames: dict[str, pd.DataFrame] = {}
    try:
        nav = fetch_efunds_nav_history("020671", max_rows=250)
        result["official_nav"] = ingest_official_nav_history(nav, engine=engine)
    except Exception as exc:
        result["official_nav"] = _failure(exc)
    try:
        etf = fetch_etf_status("589130")
        result["etf_status"] = ingest_etf_status_snapshot(etf, engine=engine)
    except Exception as exc:
        result["etf_status"] = _failure(exc)
    try:
        result["events"] = sync_fund_events(
            "020671",
            engine=engine,
            scanned_through_date=analysis_date,
            lookback_days=7,
        )
        with Session(engine) as session:
            save_observation(
                session,
                dataset_type="event_scan",
                field_name="official_fund_events_7d",
                value=result["events"],
                source_level="A",
                source="efunds_official",
                source_url=None,
                confirmation_status="VERIFIED_SCAN",
                applicable_date=analysis_date,
                fund_code="020671",
            )
            session.commit()
    except Exception as exc:
        result["events"] = _failure(exc)
        with Session(engine) as session:
            save_observation(
                session,
                dataset_type="event_scan",
                field_name="official_fund_events_7d",
                value=result["events"],
                source_level="A",
                source="efunds_official",
                source_url=None,
                confirmation_status="UNAVAILABLE",
                applicable_date=analysis_date,
                fund_code="020671",
                status="FAILED",
                error_message=result["events"]["error"],
            )
            session.commit()

    try:
        with Session(engine) as session:
            metadata = session.scalar(
                select(FundMetadataSnapshot)
                .join(Instrument, Instrument.id == FundMetadataSnapshot.fund_instrument_id)
                .where(Instrument.local_code == "020671")
                .where(FundMetadataSnapshot.as_of_date <= analysis_date)
                .where(FundMetadataSnapshot.status == "SUCCESS")
                .order_by(FundMetadataSnapshot.as_of_date.desc(), FundMetadataSnapshot.id.desc())
            )
            if metadata is None or not metadata.payload_json:
                raise ValueError("no verified fund metadata snapshot at or before analysis date")
            identity = json.loads(metadata.payload_json)
            index_code, etf_code = identity.get("benchmark_index_code"), identity.get("target_etf_code")
            if not index_code or not etf_code:
                raise ValueError("fund metadata lacks target ETF or benchmark index code")
            snapshot = session.scalar(
                select(UniverseSnapshot)
                .join(Universe, Universe.id == UniverseSnapshot.universe_id)
                .where(Universe.code == f"INDEX:{index_code}")
                .where(UniverseSnapshot.as_of_date <= analysis_date)
                .where(UniverseSnapshot.status == "SUCCESS")
                .order_by(UniverseSnapshot.as_of_date.desc(), UniverseSnapshot.id.desc())
            )
            if snapshot is None:
                raise ValueError("no successful universe snapshot at or before analysis date")
            constituents = session.execute(
                select(Instrument.symbol, Instrument.local_code, Instrument.id)
                .join(UniverseConstituentWeight, UniverseConstituentWeight.instrument_id == Instrument.id)
                .where(UniverseConstituentWeight.snapshot_id == snapshot.id)
            ).all()
            symbols = [row[0] for row in constituents]
            classification_ids = [row[2] for row in constituents]
            classified_count = session.scalar(
                select(func.count(func.distinct(InstrumentClassificationSnapshot.instrument_id)))
                .where(InstrumentClassificationSnapshot.instrument_id.in_(classification_ids))
                .where(InstrumentClassificationSnapshot.scheme == CSI_SCHEME)
                .where(InstrumentClassificationSnapshot.as_of_date <= analysis_date)
            ) or 0
            classification_codes = [row[1] for row in constituents]
            start_date = (pd.Timestamp(historical_end_date) - timedelta(days=450)).date().isoformat()
            rows = []
            for symbol in dict.fromkeys([f"{etf_code}.SS", *symbols]):
                market = MarketDataService(
                    session,
                    mode="database_first",
                    provider=get_auto_daily_frame,
                    persist_provider_results=True,
                    strict_requested_end=True,
                    require_turnover_amount=True,
                ).daily(symbol, start_date, historical_end_date)
                rows.append(
                    {
                        "symbol": symbol,
                        "status": market.status,
                        "source": market.source,
                        "provider_name": market.provider_name,
                        "refreshed": market.refreshed,
                        "provider_call_count": market.provider_call_count,
                        "row_count": len(market.data),
                        "message": market.message,
                    }
                )
            result["market_data"] = {
                "status": "SUCCESS" if all(row["status"] == SUCCESS for row in rows) else "PARTIAL",
                "universe_snapshot_date": str(snapshot.as_of_date),
                "symbols": rows,
                "network_call_count": sum(row["provider_call_count"] for row in rows),
                "historical_end_date": historical_end_date,
                "current_day_source_policy": "MCP_ONLY" if is_current_day else "NOT_APPLICABLE",
            }
            if is_current_day:
                current_rows = []
                for symbol in dict.fromkeys([f"{etf_code}.SS", *symbols]):
                    resolved = resolve_current_daily_bar(
                        web_resolver, symbol=symbol, analysis_date=analysis_date,
                        allowed_domains=MARKET_WEB_DOMAINS,
                        require_close_confirmation=resolved_mode in {"close", "nav_confirmed"},
                    )
                    inserted = save_mcp_observation(
                        session, dataset_type="current_daily_market", field_name="daily_bar",
                        payload=resolved.payload, source_level=resolved.source_level or "UNVERIFIED",
                        source="mcp_web_resolver", source_url=resolved.source_url,
                        confirmation_status="VERIFIED_WEB_SOURCE" if resolved.status == "SUCCESS" else "UNAVAILABLE",
                        applicable_date=analysis_date, instrument_symbol=symbol,
                        status=resolved.status, error_message=resolved.reason,
                    )
                    if resolved.status == "SUCCESS":
                        mcp_current_frames[symbol] = current_bar_frame(resolved)
                    current_rows.append({
                        "symbol": symbol, "status": resolved.status, "source_level": resolved.source_level,
                        "source_url": resolved.source_url, "stored": inserted, "message": resolved.reason,
                    })
                session.commit()
                result["market_data"]["current_day_mcp"] = current_rows
                if not all(row["status"] == "SUCCESS" for row in current_rows):
                    result["market_data"]["status"] = "PARTIAL"
    except Exception as exc:
        result["market_data"] = _failure(exc)
        return result
    try:
        if classified_count < len(classification_codes):
            classifications = fetch_csindex_industry_classifications(classification_codes)
            result["classifications"] = ingest_classification_snapshots(
                classifications, engine=engine
            )
            result["classifications"]["status"] = "SUCCESS"
        else:
            result["classifications"] = {
                "status": "SKIPPED_COMPLETE_CACHE",
                "classified_count": classified_count,
            }
    except Exception as exc:
        result["classifications"] = _failure(exc)
    try:
        with Session(engine) as session:
            snapshot = session.scalar(
                select(UniverseSnapshot).join(Universe, Universe.id == UniverseSnapshot.universe_id)
                .where(Universe.code == f"INDEX:{index_code}").where(UniverseSnapshot.status == "SUCCESS")
                .where(UniverseSnapshot.as_of_date <= analysis_date)
                .order_by(UniverseSnapshot.as_of_date.desc(), UniverseSnapshot.id.desc())
            )
            rows = session.execute(
                select(Instrument.symbol, Instrument.name, UniverseConstituentWeight.weight_pct)
                .join(UniverseConstituentWeight, UniverseConstituentWeight.instrument_id == Instrument.id)
                .where(UniverseConstituentWeight.snapshot_id == snapshot.id)
            ).all()
            constituents = [{"symbol": row[0], "name": row[1], "weight_pct": float(row[2] or 0)} for row in rows]
            repository = MarketBarRepository(session)
            start = (pd.Timestamp(historical_end_date) - timedelta(days=100)).date().isoformat()
            frames = {item["symbol"]: repository.get_latest_daily_bars(item["symbol"], start, historical_end_date) for item in constituents}
            etf_symbol = f"{etf_code}.SS"
            etf_frame = repository.get_latest_daily_bars(etf_symbol, start, historical_end_date)
            if is_current_day:
                for symbol, current_frame in mcp_current_frames.items():
                    base = etf_frame if symbol == etf_symbol else frames.get(symbol, pd.DataFrame())
                    combined = pd.concat([base, current_frame]).loc[lambda data: ~data.index.duplicated(keep="last")].sort_index()
                    if symbol == etf_symbol:
                        etf_frame = combined
                    else:
                        frames[symbol] = combined
            index_return = None
            if len(etf_frame) >= 2:
                index_return = (float(etf_frame["Close"].iloc[-1]) / float(etf_frame["Close"].iloc[-2]) - 1) * 100
            inserted = 0
            for name, value in (("etf_price_structure", daily_price_structure(etf_frame)), ("breadth_extensions", breadth_extensions(frames, constituents, analysis_date, index_return)), ("top10_weights", top_weight_snapshot(frames, constituents, analysis_date, index_return))):
                inserted += save_observation(session, dataset_type="market_structure", field_name=name, value=value, source_level="B", source="derived_from_verified_market_bars", source_url=None, confirmation_status="DERIVED", applicable_date=analysis_date, instrument_symbol=etf_symbol if name == "etf_price_structure" else None)
            top10 = sorted(constituents, key=lambda item: item["weight_pct"], reverse=True)[:10]
            profile = resolve_fund_analysis_profile("020671", identity)
            top_names = " ".join(item["name"] for item in top10[:3])
            keywords = " ".join(profile.event_keywords[:5])
            inserted += _store_company_event_discovery(
                session,
                fund_code="020671",
                analysis_date=analysis_date,
                query=f"{top_names} {keywords} {analysis_date} 公告",
            )
            try:
                cycle = fetch_industry_cycle_board("半导体", start, historical_end_date)
                inserted += save_observation(
                    session,
                    dataset_type="industry_cycle",
                    field_name="semiconductor_industry_board_proxy",
                    value=cycle,
                    source_level="B",
                    source="akshare_eastmoney",
                    source_url=None,
                    confirmation_status="THIRD_PARTY",
                    applicable_date=analysis_date,
                    published_date=cycle["market_date"],
                )
            except Exception as exc:
                inserted += save_observation(
                    session,
                    dataset_type="industry_cycle",
                    field_name="semiconductor_industry_board_proxy",
                    value={"status": "FAILED", "theme": "半导体"},
                    source_level="B",
                    source="akshare_eastmoney",
                    source_url=None,
                    confirmation_status="UNAVAILABLE",
                    applicable_date=analysis_date,
                    status="FAILED",
                    error_message=f"{type(exc).__name__}: {exc}",
                )
                # A Firecrawl search result is retained as isolated raw MCP
                # evidence only.  It cannot enter the cycle score until a
                # deterministic field extractor validates the original page.
                policy = source_policy_for("industry_cycle")
                resolver = build_firecrawl_search_resolver_from_env(
                    official_domains=policy.primary_domains
                )
                query = f"半导体 产业数据 {analysis_date} 集成电路 产量 销售额"
                # Only A/B domains may be automatically persisted as a source
                # candidate.  C-level research domains stay outside this
                # path and may later be recorded as non-scoring news leads.
                allowed_documents = (*policy.primary_domains, *policy.fallback_domains)
                documents = resolver.resolve(query, allowed_documents) if resolver else []
                if documents:
                    for document in documents:
                        inserted += save_mcp_observation(
                            session,
                            dataset_type="industry_cycle_web_discovery",
                            field_name="original_page_document",
                            payload=document["payload"],
                            source_level=document["source_level"],
                            source="firecrawl_search",
                            source_url=document["source_url"],
                            confirmation_status="DISCOVERED_REQUIRES_STRUCTURED_VALIDATION",
                            applicable_date=analysis_date,
                            status="SUCCESS",
                        )
                        for fact in extract_industry_cycle_facts(
                            source_url=document["source_url"],
                            source_level=document["source_level"],
                            payload=document["payload"],
                        ):
                            inserted += save_observation(
                                session,
                                dataset_type="industry_cycle",
                                field_name=fact.metric_name,
                                value=fact.to_dict(),
                                source_level=fact.source_level,
                                source="firecrawl_search_original_page",
                                source_url=fact.source_url,
                                confirmation_status="VERIFIED_STRUCTURED_ORIGINAL_PAGE",
                                applicable_date=analysis_date,
                                published_date=fact.published_date,
                            )
                else:
                    inserted += save_mcp_observation(
                        session,
                        dataset_type="industry_cycle_web_discovery",
                        field_name="original_page_document",
                        payload=None,
                        source_level="UNVERIFIED",
                        source="firecrawl_search",
                        source_url=None,
                        confirmation_status="UNAVAILABLE",
                        applicable_date=analysis_date,
                        status="FAILED",
                        error_message=(resolver.last_error if resolver else "FIRECRAWL_API_KEY is not configured"),
                    )
            for item in top10:
                symbol = item["symbol"]
                try:
                    flow = _retry_fetch(lambda symbol=symbol: fetch_individual_fund_flow(symbol))
                    latest = flow.iloc[-1].to_dict()
                    inserted += save_observation(session, dataset_type="fund_flow", field_name="individual_main_flow", value=latest, source_level="B", source="akshare_eastmoney", source_url=None, confirmation_status="THIRD_PARTY", applicable_date=analysis_date, instrument_symbol=item["symbol"])
                except Exception as exc:
                    inserted += save_observation(
                        session,
                        dataset_type="fund_flow",
                        field_name="individual_main_flow",
                        value={"status": "FAILED"},
                        source_level="B",
                        source="akshare_eastmoney",
                        source_url=None,
                        confirmation_status="UNAVAILABLE",
                        applicable_date=analysis_date,
                        instrument_symbol=item["symbol"],
                        status="FAILED",
                        error_message=f"{type(exc).__name__}: {exc}",
                    )
                    inserted += _store_web_discovery(
                        session,
                        dataset_type="fund_flow_web_discovery",
                        query=f"{item['name']} {item['symbol'].split('.')[0]} 资金流向 主力资金",
                        analysis_date=analysis_date,
                        instrument_symbol=item["symbol"],
                    )
                try:
                    financial = _retry_fetch(lambda symbol=symbol: fetch_financial_indicators(symbol))
                    latest_financial = financial.iloc[0].to_dict()
                    normalized_financial = normalize_financial_indicator(latest_financial)
                    published = str(normalized_financial.get("notice_date") or "")[:10] or None
                    inserted += save_observation(
                        session,
                        dataset_type="financial",
                        field_name="latest_financial_indicator",
                        value={"raw": latest_financial, "normalized": normalized_financial},
                        source_level="B",
                        source="akshare_eastmoney",
                        source_url=None,
                        confirmation_status="THIRD_PARTY",
                        applicable_date=analysis_date,
                        published_date=published,
                        instrument_symbol=item["symbol"],
                    )
                except Exception as exc:
                    inserted += save_observation(
                        session,
                        dataset_type="financial",
                        field_name="latest_financial_indicator",
                        value={"status": "FAILED"},
                        source_level="B",
                        source="akshare_eastmoney",
                        source_url=None,
                        confirmation_status="UNAVAILABLE",
                        applicable_date=analysis_date,
                        instrument_symbol=item["symbol"],
                        status="FAILED",
                        error_message=f"{type(exc).__name__}: {exc}",
                    )
                    inserted += _store_web_discovery(
                        session,
                        dataset_type="financial_web_discovery",
                        query=f"{item['name']} {item['symbol'].split('.')[0]} 财务指标 营业收入 净利润 公告",
                        analysis_date=analysis_date,
                        instrument_symbol=item["symbol"],
                    )
            if resolved_mode == "intraday":
                # Intraday data follows the same policy as current daily bars:
                # a future MCP resolver adapter may supply it, but AKShare is
                # never called for the current session.
                result["intraday"] = {
                    "status": "MCP_REQUIRED",
                    "message": "盘中 5 分钟行情需由 MCP 原始网页数据适配器提供；未调用 AKShare。",
                }
            session.commit()
            result["enrichment"] = {"status": "SUCCESS", "observations_inserted": inserted, "analysis_mode": resolved_mode}
    except Exception as exc:
        result["enrichment"] = _failure(exc)
    return result
