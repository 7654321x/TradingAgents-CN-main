from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from .fund_context_formatter import format_fund_intraday_context
from .fund_config_loader import load_fund_portfolio_config, resolve_db_path
from .db import get_connection
from .intraday_snapshot import build_context_from_snapshot, build_intraday_snapshot
from .repository import FundRepository


DISCLAIMER = "本报告仅用于个人研究和复盘，不构成投资建议，不包含自动交易或确定性收益承诺。"


def run_fund_intraday(
    config_path: str = "config/personal_fund_portfolio.yaml",
    decision_time: str = "1445",
    use_sql: bool = True,
    db_path: str | None = None,
    refresh_data: bool = False,
    baostock_only: bool = False,
    no_web: bool = False,
    save_snapshot: bool = False,
    snapshot_id: int | None = None,
    output_dir: str | Path = "reports/fund_intraday",
) -> Dict[str, Any]:
    config = load_fund_portfolio_config(config_path)
    resolved_db_path = resolve_db_path(config, db_path)
    if snapshot_id:
        snapshot = build_context_from_snapshot(snapshot_id, resolved_db_path)
        snapshot["db_path"] = resolved_db_path
    else:
        snapshot = build_intraday_snapshot(
            config,
            decision_time=decision_time,
            db_path=resolved_db_path,
            refresh_data=refresh_data,
            baostock_only=baostock_only,
            no_web=no_web,
            save_snapshot=save_snapshot or use_sql,
        )
    context_text = format_fund_intraday_context(snapshot)
    report = render_fund_intraday_report(snapshot, context_text)
    output_path = save_fund_intraday_report(report, output_dir, snapshot.get("trade_date", "unknown"), decision_time)
    if snapshot.get("snapshot_id"):
        with get_connection(resolved_db_path) as conn:
            FundRepository(conn).update_intraday_report_path(int(snapshot["snapshot_id"]), str(output_path))
            conn.commit()
    return {
        "snapshot": snapshot,
        "agent_context": context_text,
        "report": report,
        "output_path": output_path,
        "db_path": resolved_db_path,
    }


def render_fund_intraday_report(snapshot: Dict[str, Any], context_text: str) -> str:
    return (
        "# 场外基金盘中数据上下文报告\n\n"
        f"- 报告类型：fund_intraday 数据准备报告\n"
        f"- 数据时间：{snapshot.get('trade_date')} {snapshot.get('decision_time')}\n"
        f"- 核心覆盖率：{snapshot.get('core_coverage_rate')}%\n"
        f"- 全字段覆盖率：{snapshot.get('all_coverage_rate')}%\n"
        f"- 数据质量：{snapshot.get('data_quality_level')}\n"
        f"- 数据源状态：Baostock={snapshot.get('diagnostics', {}).get('baostock_status')}，"
        f"Web={snapshot.get('diagnostics', {}).get('web_status')}，"
        f"Firecrawl={snapshot.get('diagnostics', {}).get('firecrawl_status')}\n\n"
        "## 当前基金列表与上下文\n"
        f"{context_text}\n\n"
        "## Agent 分析正文\n"
        "本模式只准备结构化上下文；最终分析应交给原 TradingAgents-CN Agent 流程完成，数据层不生成硬编码交易结论。\n\n"
        "## 字段来源摘要\n"
        "- baostock: 结构化行情事实指标\n"
        "- web/firecrawl: 网页raw_text兜底，缺失时在上下文中标记\n\n"
        "## 人工复核清单\n"
        "- 核对基金净值和估算来源。\n"
        "- 核对ETF、指数、板块和重仓股行情是否完整。\n"
        "- 核对公告、龙虎榜、新闻风险是否遗漏。\n"
        "- 覆盖率不足时先人工复核。\n\n"
        f"## 免责声明\n{DISCLAIMER}\n"
    )


def save_fund_intraday_report(report: str, output_dir: str | Path, trade_date: str, decision_time: str) -> Path:
    path = Path(output_dir)
    path.mkdir(parents=True, exist_ok=True)
    output_path = path / f"fund_intraday_{trade_date}_{decision_time}.md"
    output_path.write_text(report, encoding="utf-8")
    return output_path
