from datetime import date
from pathlib import Path
from typing import Any, Dict

from .data_quality import calculate_data_quality
from .domestic_web_provider import DomesticWebProvider, merge_raw_text_status
from .formatter import format_sector_fund_context_for_agents
from .history_store import HistoryStore
from .mock_data import build_mock_sector_fund_context
from .parsers import apply_raw_text_to_context
from .report import render_sector_fund_report, save_sector_fund_report
from .scoring import score_sector_fund_context


def run_sector_fund_analysis(
    config_path: str = "config/personal_semiconductor.yaml",
    analysis_date: str | None = None,
    use_mock: bool = True,
    use_firecrawl: bool = False,
    output_dir: str | Path = "reports/sector_fund",
    history_path: str | Path = "data/sector_fund_history.json",
) -> Dict[str, Any]:
    analysis_date = analysis_date or date.today().isoformat()

    # 当前真实网页模式先采集 raw_text，再用可解释 mock 结构兜底，避免网页失败阻断报告。
    context = build_mock_sector_fund_context(config_path=config_path, analysis_date=analysis_date)
    if not use_mock:
        provider = DomesticWebProvider()
        raw_result = provider.fetch_sector_fund_pages(context.config, use_firecrawl=use_firecrawl)
        context = merge_raw_text_status(context, raw_result)
        source_label = "firecrawl_raw" if use_firecrawl else "real_data"
        context = apply_raw_text_to_context(
            context,
            raw_result.raw_text,
            source_label=source_label,
            history_store=HistoryStore(history_path),
        )
        if not any(status == "success" for status in raw_result.source_status.values()):
            context.warnings.append("真实网页抓取未成功，已使用mock结构化数据兜底。")

    context.data_quality = calculate_data_quality(context.field_sources)
    score = score_sector_fund_context(context)
    report = render_sector_fund_report(context, score)
    output_path = save_sector_fund_report(report, output_dir=output_dir, analysis_date=analysis_date)

    return {
        "context": context,
        "score": score,
        "agent_context": format_sector_fund_context_for_agents(context),
        "report": report,
        "output_path": output_path,
    }
