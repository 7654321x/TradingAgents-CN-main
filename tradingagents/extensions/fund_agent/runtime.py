"""Safe routing for index-linked and actively managed fund analysis."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from tradingagents.analysis.fund_report import FundReportError, FundReportService
from tradingagents.extensions.sector_fund.analysis_service import generate_database_only_analysis
from tradingagents.storage.models import FundMetadataSnapshot, Instrument

from .profile_registry import profile_payload, resolve_fund_analysis_profile

FundAnalysisMode = Literal["INDEX_LINKED", "ACTIVE_DEGRADED"]


@dataclass(frozen=True)
class GenericFundAnalysisResult:
    fund_code: str
    analysis_date: str
    mode: FundAnalysisMode
    status: str
    profile: dict[str, Any]
    limitations: tuple[str, ...]
    sector_report: Any | None = None
    active_fund_report: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        if self.sector_report is not None:
            result["sector_report"] = self.sector_report.to_dict()
        return result


def _identity_at_or_before(
    session: Session, *, fund_code: str, analysis_date: str
) -> dict[str, Any]:
    snapshot = session.scalar(
        select(FundMetadataSnapshot)
        .join(Instrument, Instrument.id == FundMetadataSnapshot.fund_instrument_id)
        .where(Instrument.local_code == fund_code)
        .where(FundMetadataSnapshot.as_of_date <= analysis_date)
        .where(FundMetadataSnapshot.status == "SUCCESS")
        .order_by(FundMetadataSnapshot.as_of_date.desc(), FundMetadataSnapshot.id.desc())
    )
    return json.loads(snapshot.payload_json) if snapshot and snapshot.payload_json else {}


def classify_fund_analysis_mode(identity: dict[str, Any]) -> FundAnalysisMode:
    """Use complete verified relations only; never guess a target ETF/index."""
    if identity.get("target_etf_code") and identity.get("benchmark_index_code"):
        return "INDEX_LINKED"
    return "ACTIVE_DEGRADED"


def analyze_fund_database_only(
    session: Session,
    *,
    fund_code: str,
    analysis_date: str,
    analysis_mode: str = "close",
) -> GenericFundAnalysisResult:
    """Route any known fund to full index or conservative active-fund mode.

    This is deliberately database-only.  Live/on-demand collection remains a
    separate capability and cannot be implicitly triggered for an unfamiliar
    fund identity.
    """
    identity = _identity_at_or_before(
        session, fund_code=str(fund_code), analysis_date=analysis_date
    )
    profile = profile_payload(resolve_fund_analysis_profile(str(fund_code), identity))
    mode = classify_fund_analysis_mode(identity)
    if mode == "INDEX_LINKED":
        report = generate_database_only_analysis(
            session,
            fund_code=str(fund_code),
            analysis_date=analysis_date,
            analysis_mode=analysis_mode,
        )
        return GenericFundAnalysisResult(
            fund_code=str(fund_code),
            analysis_date=analysis_date,
            mode=mode,
            status="SUCCESS",
            profile=profile,
            limitations=(),
            sector_report=report,
        )
    try:
        active = FundReportService(session, mode="database_only").analyze(
            str(fund_code), analysis_date
        )
    except FundReportError as exc:
        return GenericFundAnalysisResult(
            fund_code=str(fund_code),
            analysis_date=analysis_date,
            mode=mode,
            status="DEGRADED_DATA_UNAVAILABLE",
            profile=profile,
            limitations=(
                "未核验到完整目标ETF和跟踪指数，已按主动基金模式降级。",
                str(exc),
                "不会以其他基金、指数或主题替代缺失的实时穿透数据。",
            ),
        )
    return GenericFundAnalysisResult(
        fund_code=str(fund_code),
        analysis_date=analysis_date,
        mode=mode,
        status="SUCCESS",
        profile=profile,
        limitations=(
            "主动基金模式只分析正式净值和已披露持仓；持仓披露存在报告期滞后。",
            "未核验目标ETF或跟踪指数，因此不输出指数穿透广度、ETF份额或核心权重结论。",
        ),
        active_fund_report=active.to_dict(),
    )
