"""One internal entry point for a user-requested 020671 daily analysis."""
from __future__ import annotations

from dataclasses import replace

from sqlalchemy.orm import Session

from tradingagents.extensions.fund_agent.runtime import analyze_fund_database_only

from .analysis_service import generate_database_only_analysis
from .daily_sync import refresh_020671_on_demand
from .llm_explanation import generate_llm_explanation
from .web_fallback import WebResolver


def analyze_020671_on_demand(
    engine,
    *,
    analysis_date: str,
    analysis_mode: str = "auto",
    enable_llm: bool = True,
    llm_provider: str | None = None,
    llm_model: str | None = None,
    web_resolver: WebResolver | None = None,
):
    """Refresh public cache, build deterministic report, then optionally explain it.

    This is intentionally an application service rather than a scheduled job:
    it runs only after an explicit user request in the project conversation.
    """
    sync = refresh_020671_on_demand(
        engine, analysis_date=analysis_date, analysis_mode=analysis_mode, web_resolver=web_resolver
    )
    with Session(engine) as session:
        report = generate_database_only_analysis(
            session,
            fund_code="020671",
            analysis_date=analysis_date,
            enable_llm=False,
            analysis_mode=sync["analysis_mode"],
        )
    report = replace(report, fund_context={**report.fund_context, "on_demand_sync": sync})
    if enable_llm:
        report = replace(
            report,
            llm_explanation=generate_llm_explanation(
                report, provider=llm_provider, model=llm_model
            ),
        )
    return report


def analyze_fund_on_demand(
    engine,
    *,
    fund_code: str,
    analysis_date: str,
    analysis_mode: str = "auto",
    enable_llm: bool = True,
    llm_provider: str | None = None,
    llm_model: str | None = None,
    web_resolver: WebResolver | None = None,
):
    """One user-requested entry point for any fund without implicit guessing.

    The established 020671 path retains its approved on-demand refresh.  A
    different fund is deliberately database-only until a verified provider
    profile is available; it therefore cannot silently fetch or substitute an
    unrelated target ETF/index.
    """
    if str(fund_code) == "020671":
        return analyze_020671_on_demand(
            engine,
            analysis_date=analysis_date,
            analysis_mode=analysis_mode,
            enable_llm=enable_llm,
            llm_provider=llm_provider,
            llm_model=llm_model,
            web_resolver=web_resolver,
        )
    resolved_mode = "close" if analysis_mode == "auto" else analysis_mode
    with Session(engine) as session:
        return analyze_fund_database_only(
            session,
            fund_code=str(fund_code),
            analysis_date=analysis_date,
            analysis_mode=resolved_mode,
        )
