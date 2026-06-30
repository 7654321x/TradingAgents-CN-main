from datetime import date
from pathlib import Path
from typing import Any, Dict
import webbrowser

from .data_quality import calculate_data_quality
from .domestic_web_provider import DomesticWebProvider, merge_raw_text_status
from .fetch_logger import DataFetchLogger
from .formatter import format_sector_fund_context_for_agents
from .history_store import HistoryStore
from .mock_data import build_mock_sector_fund_context
from .parsers import apply_raw_text_to_context
from .report import render_sector_fund_report, save_sector_fund_report
from .score_history import ScoreHistoryStore, analyze_signal_changes, build_score_record
from .scoring import apply_data_quality_gate, score_sector_fund_context


def _source_mode(use_mock: bool, use_firecrawl: bool) -> str:
    if use_mock:
        return "mock"
    return "firecrawl" if use_firecrawl else "real_data"


def _expected_report_path(output_dir: str | Path, analysis_date: str) -> Path:
    return Path(output_dir) / f"sector_fund_report_{analysis_date}.md"


def _open_report_safely(path: Path) -> None:
    try:
        webbrowser.open(path.resolve().as_uri())
    except Exception:
        pass


def run_sector_fund_analysis(
    config_path: str = "config/personal_semiconductor.yaml",
    analysis_date: str | None = None,
    use_mock: bool = True,
    use_firecrawl: bool = False,
    output_dir: str | Path = "reports/sector_fund",
    history_path: str | Path = "data/sector_fund_history.json",
    score_history_path: str | Path = "data/sector_fund_score_history.json",
    save_history: bool = True,
    history_days: int = 5,
    min_real_coverage: float = 0.4,
    open_report: bool = False,
) -> Dict[str, Any]:
    analysis_date = analysis_date or date.today().isoformat()

    # 当前真实网页模式先采集 raw_text，再用可解释 mock 结构兜底，避免网页失败阻断报告。
    context = build_mock_sector_fund_context(config_path=config_path, analysis_date=analysis_date)
    context.source_mode = _source_mode(use_mock, use_firecrawl)
    context.report_date = date.today().isoformat()
    context.data_date = None
    if not use_mock:
        fetch_logger = DataFetchLogger()
        fetch_logger.info(f"开始真实数据采集 | mode={_source_mode(use_mock, use_firecrawl)} | config={config_path}")
        provider = DomesticWebProvider()
        raw_result = provider.fetch_sector_fund_pages(context.config, use_firecrawl=use_firecrawl, fetch_logger=fetch_logger)
        context = merge_raw_text_status(context, raw_result)
        source_label = "firecrawl_raw" if use_firecrawl else "real_data"
        context = apply_raw_text_to_context(
            context,
            raw_result.raw_text,
            source_label=source_label,
            history_store=HistoryStore(history_path),
            fetch_logger=fetch_logger,
        )
        fetch_logger.source_summary(raw_result.source_status, context.field_sources)
        if not any(status == "success" for status in raw_result.source_status.values()):
            context.warnings.append("真实网页抓取未成功，已使用mock结构化数据兜底。")
        elif any(value in {"real_data", "firecrawl_raw"} for value in context.field_sources.values()):
            context.data_date = analysis_date

    context.data_quality = calculate_data_quality(context.field_sources)
    score = score_sector_fund_context(context)
    score = apply_data_quality_gate(
        score,
        real_coverage_rate=context.data_quality.get("real_coverage_rate", 0.0),
        min_real_coverage=min_real_coverage,
    )

    output_path = _expected_report_path(output_dir, analysis_date)
    score_store = ScoreHistoryStore(score_history_path)
    score_record = build_score_record(
        analysis_date=analysis_date,
        score=score,
        data_quality=context.data_quality,
        source_mode=_source_mode(use_mock, use_firecrawl),
        report_path=str(output_path),
    )
    try:
        history_rows = score_store.load()
        context.history_summary = analyze_signal_changes(history_rows, score_record, history_days=history_days)
    except Exception as exc:
        context.history_summary = {}
        context.warnings.append(f"评分历史读取失败：{exc}")

    report = render_sector_fund_report(context, score)
    saved_path = save_sector_fund_report(report, output_dir=output_dir, analysis_date=analysis_date)
    score_record["report_path"] = str(saved_path)
    if save_history:
        try:
            score_store.upsert(score_record)
        except Exception as exc:
            context.warnings.append(f"评分历史保存失败：{exc}")
    if open_report:
        _open_report_safely(saved_path)

    return {
        "context": context,
        "score": score,
        "score_record": score_record,
        "history_summary": context.history_summary,
        "agent_context": format_sector_fund_context_for_agents(context),
        "report": report,
        "output_path": saved_path,
    }
