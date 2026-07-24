"""Database-only report assembly for on-demand 020671 analysis."""
from __future__ import annotations

import json
from dataclasses import replace

from sqlalchemy import select
from sqlalchemy.orm import Session

from tradingagents.extensions.fund_agent import profile_payload, resolve_fund_analysis_profile
from tradingagents.storage.models import FundMetadataSnapshot, Instrument

from .daily_observation import build_daily_observation
from .fund_context import load_fund_context
from .llm_explanation import generate_llm_explanation
from .quant_metrics import SectorFundQuantService
from .scoring import build_scored_report


def generate_database_only_analysis(
    session: Session,
    *,
    fund_code: str,
    analysis_date: str,
    enable_llm: bool = False,
    analysis_mode: str = "close",
    llm_provider: str | None = None,
    llm_model: str | None = None,
    llm_factory=None,
):
    """Assemble a report from cache; this function never refreshes providers."""
    metadata = session.scalar(
        select(FundMetadataSnapshot)
        .join(Instrument, Instrument.id == FundMetadataSnapshot.fund_instrument_id)
        .where(Instrument.local_code == fund_code)
        .where(FundMetadataSnapshot.as_of_date <= analysis_date)
        .where(FundMetadataSnapshot.status == "SUCCESS")
        .order_by(FundMetadataSnapshot.as_of_date.desc(), FundMetadataSnapshot.id.desc())
    )
    if metadata is None or not metadata.payload_json:
        raise ValueError("no verified fund metadata snapshot at or before analysis date")
    identity = json.loads(metadata.payload_json)
    etf_code = identity.get("target_etf_code")
    index_code = identity.get("benchmark_index_code")
    if not etf_code or not index_code:
        raise ValueError("fund metadata lacks target ETF or benchmark index code")
    metrics = SectorFundQuantService(session, mode="database_only").analyze(
        fund_code=fund_code,
        target_etf_symbol=f"{etf_code}.SS",
        index_code=str(index_code),
        analysis_date=analysis_date,
        mcp_current_day_only=True,
        analysis_mode=analysis_mode,
    )
    context = load_fund_context(
        session,
        fund_code=fund_code,
        etf_code=str(etf_code),
        analysis_date=analysis_date,
        market_date=metrics.market_date,
    )
    profile = resolve_fund_analysis_profile(fund_code, identity)
    context = {**context, "analysis_profile": profile_payload(profile)}
    report = replace(
        build_scored_report(metrics, context),
        daily_observation=build_daily_observation(metrics.to_dict()),
    )
    if enable_llm:
        report = replace(
            report,
            llm_explanation=generate_llm_explanation(
                report,
                provider=llm_provider,
                model=llm_model,
                llm_factory=llm_factory,
            ),
        )
    return report
