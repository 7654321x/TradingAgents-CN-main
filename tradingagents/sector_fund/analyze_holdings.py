from __future__ import annotations

import json
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any, Dict, Iterable, List

from .fund_context_report import build_fund_context
from .fund_sql_list import SqlField, list_sql_fields_for_context


def run_analyze_holdings(
    config_path: str = "config/personal_fund_portfolio.yaml",
    db_path: str | None = None,
    decision_time: str = "1445",
    output_dir: str | Path = "reports/fund_intraday",
    view: bool = False,
) -> Dict[str, Any]:
    resolved_db_path = db_path or _db_path_from_config(config_path)
    fields = list_sql_fields_for_context(resolved_db_path, decision_time=decision_time)
    context = build_fund_context(fields, decision_time=decision_time)
    analysis = analyze_holdings_from_context(context, fields)
    trade_date = _latest_trade_date(fields)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    report_path = output_path / f"holdings_analysis_{trade_date}_{decision_time}.md"
    json_path = output_path / f"holdings_analysis_{trade_date}_{decision_time}.json"
    report = render_holdings_report(analysis, config_path=config_path, db_path=resolved_db_path, decision_time=decision_time)
    report_path.write_text(report, encoding="utf-8")
    json_path.write_text(json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8")
    if view:
        print(_terminal_summary(analysis, report_path))
    return {"analysis": analysis, "report_path": str(report_path), "json_path": str(json_path)}


def analyze_holdings_from_context(context: Dict[str, Any], fields: Iterable[SqlField]) -> Dict[str, Any]:
    field_list = list(fields)
    quote_by_code = _collect_table_fields(field_list, "security_quote_snapshot")
    kline_by_code = _collect_table_fields(field_list, "security_kline_daily")
    indicator_by_code = _collect_table_fields(field_list, "security_indicator_daily")
    master_by_code = _collect_table_fields(field_list, "security_master")

    rows: List[Dict[str, Any]] = []
    missing: List[Dict[str, Any]] = []
    for fund_code, fund in sorted(context.get("funds", {}).items()):
        fund_name = fund.get("fields", {}).get("fund_name") or ""
        for holding in fund.get("holdings", []):
            code = str(holding.get("code") or "").strip()
            name = str(holding.get("name") or master_by_code.get(code, {}).get("name") or "")
            quote = quote_by_code.get(code, {})
            kline = kline_by_code.get(code, {})
            indicator = indicator_by_code.get(code, {})
            latest_price = _first_number(quote.get("latest_price"), kline.get("close"))
            change_pct = _first_number(quote.get("change_pct"), kline.get("pct_chg"))
            ma20 = _first_number(quote.get("ma20"), indicator.get("ma20"))
            trend_status = quote.get("trend_status") or _trend_status(latest_price, ma20)
            source = quote.get("source") or kline.get("source") or indicator.get("source") or holding.get("source") or ""
            source_status = quote.get("source_status") or kline.get("source_status") or holding.get("source_status") or ""
            row = {
                "fund_code": fund_code,
                "fund_name": fund_name,
                "stock_code": code,
                "stock_name": name,
                "holding_weight_pct": _to_number(holding.get("weight_pct")),
                "report_date": holding.get("report_date") or "",
                "latest_price": latest_price,
                "change_pct": change_pct,
                "amount": _to_number(quote.get("amount")),
                "turnover_rate": _to_number(quote.get("turnover_rate")),
                "close": _to_number(kline.get("close")),
                "ma5": _first_number(quote.get("ma5"), indicator.get("ma5")),
                "ma10": _first_number(quote.get("ma10"), indicator.get("ma10")),
                "ma20": ma20,
                "trend_status": trend_status,
                "final_source": quote.get("final_source") or source or "",
                "trade_date": quote.get("trade_date") or kline.get("trade_date") or indicator.get("trade_date") or "",
                "source": source,
                "source_status": source_status,
                "data_status": _data_status(code, latest_price, change_pct, indicator),
                "review_note": _review_note(latest_price, change_pct, indicator),
                "fund_impact": _fund_impact(change_pct, _to_number(holding.get("weight_pct")), trend_status),
            }
            rows.append(row)
            for field_name in ["latest_price", "change_pct", "ma20"]:
                if row.get(field_name) in (None, ""):
                    missing.append(
                        {
                            "fund_code": fund_code,
                            "stock_code": code,
                            "field_name": field_name,
                            "reason": "SQL 中未读取到持仓股票对应字段",
                            "fix_suggestion": "先运行 fund_enrich/data_probe 刷新持仓和行情，再检查 security_quote_snapshot/security_indicator_daily。",
                        }
                    )

    unique_codes = sorted({row["stock_code"] for row in rows if row.get("stock_code")})
    return {
        "summary": {
            "fund_count": len(context.get("funds", {})),
            "holding_row_count": len(rows),
            "unique_stock_count": len(unique_codes),
            "missing_field_count": len(missing),
            "data_quality": "可用于Agent分析" if rows and len(missing) <= max(1, len(rows)) else "需先补齐持仓行情",
        },
        "holdings": rows,
        "missing_fields": missing,
        "unique_stock_codes": unique_codes,
    }


def render_holdings_report(analysis: Dict[str, Any], config_path: str, db_path: str, decision_time: str) -> str:
    summary = analysis.get("summary", {})
    lines = [
        "# analyze_holdings 持仓股票深度数据分析",
        "",
        f"- 配置文件：`{config_path}`",
        f"- SQLite：`{db_path}`",
        f"- 决策时间：{decision_time}",
        f"- 基金数：{summary.get('fund_count', 0)}",
        f"- 持仓行数：{summary.get('holding_row_count', 0)}",
        f"- 去重股票数：{summary.get('unique_stock_count', 0)}",
        f"- 缺失字段数：{summary.get('missing_field_count', 0)}",
        f"- 数据质量：{summary.get('data_quality', '-')}",
        "",
        "## 1. 持仓股票行情与均线",
        "",
        "| 基金 | 股票 | 权重 | 最新价 | 涨跌幅 | 成交额 | 换手率 | MA20 | 趋势 | 对基金影响 |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    holdings = analysis.get("holdings", [])
    if not holdings:
        lines.append("| - | 未读取到持仓股票 | - | missing | missing | missing | missing | missing | missing | 请先运行 fund_enrich 或补齐 fund_holding_snapshot |")
    for row in holdings:
        fund = f"{row.get('fund_code', '')} {row.get('fund_name', '')}".strip()
        stock = f"{row.get('stock_code', '')} {row.get('stock_name', '')}".strip()
        lines.append(
            f"| {_md(fund)} | {_md(stock)} | {_fmt(row.get('holding_weight_pct'))} | "
            f"{_fmt(row.get('latest_price'))} | {_fmt(row.get('change_pct'))} | {_fmt(row.get('amount'))} | "
            f"{_fmt(row.get('turnover_rate'))} | {_fmt(row.get('ma20'))} | {_md(row.get('trend_status') or 'missing')} | "
            f"{_md(row.get('fund_impact') or row.get('review_note', ''))} |"
        )
    lines.extend(["", "### 缺失核心字段速览", "", "| 股票 | latest_price | change_pct | ma20 |", "| ---- | ------------ | ---------- | ------- |"])
    missing_rows = [row for row in holdings if row.get("latest_price") is None or row.get("change_pct") is None or row.get("ma20") is None]
    if not missing_rows:
        lines.append("| - | - | - | - |")
    for row in missing_rows:
        lines.append(
            f"| {_md(row.get('stock_name') or row.get('stock_code') or '')} | "
            f"{_md(row.get('latest_price') if row.get('latest_price') is not None else 'missing')} | "
            f"{_md(row.get('change_pct') if row.get('change_pct') is not None else 'missing')} | "
            f"{_md(row.get('ma20') if row.get('ma20') is not None else 'missing')} |"
        )
    lines.extend(
        [
            "",
            "## 2. 缺失字段与修复建议",
            "",
            "| 基金 | 股票 | 字段 | 原因 | 修复建议 |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    missing = analysis.get("missing_fields", [])
    if not missing:
        lines.append("| - | - | - | 当前持仓股票核心字段未发现明显缺失 | - |")
    for item in missing:
        lines.append(
            f"| {_md(item.get('fund_code', ''))} | {_md(item.get('stock_code', ''))} | {_md(item.get('field_name', ''))} | "
            f"{_md(item.get('reason', ''))} | {_md(item.get('fix_suggestion', ''))} |"
        )
    lines.extend(
        [
            "",
            "## 3. 给 Agent 的事实提示",
            "",
            "- 本报告只整理持仓股票事实数据，不生成买卖规则。",
            "- 操作倾向应由 `fund_agent_report` 结合基金估算、ETF、指数、板块、仓位约束和持仓股票一致性后输出。",
        ]
    )
    return "\n".join(lines) + "\n"


def _collect_table_fields(fields: List[SqlField], table_name: str) -> Dict[str, Dict[str, Any]]:
    result: Dict[str, Dict[str, Any]] = defaultdict(dict)
    for field in fields:
        if field.table_name != table_name or not field.entity_code:
            continue
        result[field.entity_code][field.field_name] = field.value
        if field.entity_name:
            result[field.entity_code]["name"] = field.entity_name
        result[field.entity_code]["source"] = field.source
        result[field.entity_code]["source_status"] = field.source_status
        if field.trade_date:
            result[field.entity_code]["trade_date"] = field.trade_date
    return dict(result)


def _data_status(code: str, latest_price: float | None, change_pct: float | None, indicator: Dict[str, Any]) -> str:
    if not code:
        return "missing_code"
    if latest_price is None and change_pct is None:
        return "missing_quote"
    if latest_price is not None and latest_price <= 0:
        return "suspect_price"
    if change_pct is not None and abs(change_pct) > 20:
        return "suspect_change_pct"
    if indicator and _to_number(indicator.get("ma20")) is None:
        return "missing_ma20"
    return "ok"


def _trend_status(latest_price: float | None, ma20: float | None) -> str:
    if ma20 in (None, 0):
        return "ma_insufficient"
    if latest_price is None:
        return "unknown"
    if abs(latest_price - ma20) / ma20 < 0.015:
        return "near_ma20"
    return "above_ma20" if latest_price > ma20 else "below_ma20"


def _fund_impact(change_pct: float | None, weight_pct: float | None, trend_status: str) -> str:
    if change_pct is None:
        return "持仓披露滞后，结论需谨慎"
    if change_pct >= 2:
        return "重仓股强势"
    if change_pct <= -2:
        return "个别重仓股拖累" if weight_pct and weight_pct >= 5 else "重仓股偏弱"
    if trend_status in {"above_ma20", "near_ma20"}:
        return "重仓股表现相对稳定"
    if trend_status == "below_ma20":
        return "重仓股技术面偏弱"
    return "重仓股分化"


def _review_note(latest_price: float | None, change_pct: float | None, indicator: Dict[str, Any]) -> str:
    status = _data_status("x", latest_price, change_pct, indicator)
    if status == "missing_quote":
        return "缺少持仓股盘中行情，需补 security_quote_snapshot"
    if status == "suspect_price":
        return "价格小于等于0，需核对代码映射或行情源"
    if status == "suspect_change_pct":
        return "涨跌幅超过20%，需人工核对是否停复牌/新股/代码错配"
    if status == "missing_ma20":
        return "缺少MA20，需刷新日K或补足20日历史"
    return "ok"


def _first_number(*values: Any) -> float | None:
    for value in values:
        parsed = _to_number(value)
        if parsed is not None:
            return parsed
    return None


def _to_number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _fmt(value: Any) -> str:
    number = _to_number(value)
    if number is None:
        return "-"
    return f"{number:.4f}".rstrip("0").rstrip(".")


def _db_path_from_config(config_path: str) -> str:
    import yaml

    path = Path(config_path)
    if not path.exists():
        return "data/fund_assistant.sqlite3"
    config = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return config.get("database", {}).get("path") or "data/fund_assistant.sqlite3"


def _latest_trade_date(fields: List[SqlField]) -> str:
    dates = sorted({field.trade_date for field in fields if field.trade_date}, reverse=True)
    return dates[0] if dates else date.today().isoformat()


def _terminal_summary(analysis: Dict[str, Any], report_path: Path) -> str:
    summary = analysis.get("summary", {})
    return "\n".join(
        [
            "analyze_holdings 摘要",
            f"基金数: {summary.get('fund_count', 0)}",
            f"持仓行数: {summary.get('holding_row_count', 0)}",
            f"去重股票数: {summary.get('unique_stock_count', 0)}",
            f"缺失字段数: {summary.get('missing_field_count', 0)}",
            f"报告: {report_path}",
        ]
    )


def _md(value: Any) -> str:
    return str(value if value is not None else "").replace("\n", " ").replace("|", "\\|")
