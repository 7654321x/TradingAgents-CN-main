from __future__ import annotations

import json
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any, Dict, Iterable, List

from .fund_sql_list import SqlField, list_sql_fields_for_context, render_sql_field_report


def run_fund_context_report(
    config_path: str = "config/personal_fund_portfolio.yaml",
    db_path: str | None = None,
    decision_time: str = "1445",
    output_dir: str | Path = "reports/fund_intraday",
    view: bool = False,
) -> Dict[str, Any]:
    resolved_db_path = db_path or _db_path_from_config(config_path)
    fields = list_sql_fields_for_context(resolved_db_path, decision_time=decision_time)
    context = build_fund_context(fields, decision_time=decision_time)
    trade_date = _latest_trade_date(fields)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    report_path = output_path / f"fund_context_report_{trade_date}_{decision_time}.md"
    json_path = output_path / f"fund_context_report_{trade_date}_{decision_time}.json"
    report = render_fund_context_report(context, fields, config_path=config_path, db_path=resolved_db_path, decision_time=decision_time)
    report_path.write_text(report, encoding="utf-8")
    json_path.write_text(json.dumps({"context": context, "fields": [field.to_dict() for field in fields if field.include_in_llm]}, ensure_ascii=False, indent=2), encoding="utf-8")
    if view:
        print(_terminal_summary(context, report_path))
    return {"context": context, "fields": [field.to_dict() for field in fields], "report_path": str(report_path), "json_path": str(json_path)}


def build_fund_context(fields: Iterable[SqlField], decision_time: str = "1445") -> Dict[str, Any]:
    field_list = list(fields)
    by_fund: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"fields": {}, "holdings": [], "estimates": {}, "nav": {}, "tracking": {}})
    holding_rows: Dict[tuple[str, str], Dict[str, Any]] = defaultdict(dict)
    securities: Dict[str, Dict[str, Any]] = defaultdict(dict)
    etfs: Dict[str, Dict[str, Any]] = defaultdict(dict)
    indices: Dict[str, Dict[str, Any]] = defaultdict(dict)
    sectors: Dict[str, Dict[str, Any]] = defaultdict(dict)
    sources: List[Dict[str, Any]] = []
    data_date = _latest_trade_date(field_list)
    stale_fields: List[Dict[str, Any]] = []
    for field in field_list:
        value = field.value
        if not field.include_in_llm and field.field_name not in {"tracking_json", "auto_enriched_json"}:
            continue
        if (
            field.table_name in {"field_source", "security_quote_snapshot", "security_kline_daily", "security_indicator_daily"}
            and field.trade_date
            and data_date
            and field.trade_date != data_date
            and field.include_in_llm
        ):
            stale_fields.append(
                {
                    "table": field.table_name,
                    "entity_type": field.entity_type,
                    "entity_code": field.entity_code,
                    "field": field.field_name,
                    "trade_date": field.trade_date,
                }
            )
        if field.table_name in {"fund_config", "fund_enrichment_result"} and field.entity_code:
            if field.field_name in {"tracking_json", "auto_enriched_json"}:
                _merge_json_fund_context(by_fund[field.entity_code], value)
                continue
            by_fund[field.entity_code]["fields"][field.field_name] = value
        elif field.table_name == "fund_intraday_estimate" and field.entity_code:
            by_fund[field.entity_code]["estimates"][field.field_name] = value
        elif field.table_name == "fund_nav_daily" and field.entity_code:
            by_fund[field.entity_code]["nav"][field.field_name] = value
        elif field.table_name == "fund_holding_snapshot" and field.entity_code:
            holding_rows[(field.entity_code, field.row_id)][field.field_name] = value
        elif field.table_name == "security_quote_snapshot" and field.entity_code:
            target = _market_target(field.entity_type, securities, etfs, indices, sectors)
            target[field.entity_code][field.field_name] = value
            if field.entity_name:
                target[field.entity_code]["name"] = field.entity_name
            target[field.entity_code]["entity_type"] = field.entity_type
        elif field.table_name in {"security_kline_daily", "security_indicator_daily", "security_master"} and field.entity_code:
            securities[field.entity_code][field.field_name] = value
            if field.entity_name:
                securities[field.entity_code]["name"] = field.entity_name
        elif field.table_name == "sector_snapshot" and field.entity_code:
            sectors[field.entity_code][field.field_name] = value
        elif field.table_name == "data_source_run":
            sources.append(
                {
                    "source_name": field.entity_code or field.row_id,
                    "field": field.field_name,
                    "value": value,
                    "status": field.source_status,
                }
            )
    for (fund_code, _row_id), item in sorted(holding_rows.items()):
        if item.get("holding_stock_code") or item.get("holding_stock_name"):
            by_fund[fund_code]["holdings"].append(
                {
                    "code": item.get("holding_stock_code") or "",
                    "name": item.get("holding_stock_name") or "",
                    "weight_pct": item.get("holding_weight_pct"),
                    "market": item.get("holding_market") or "",
                    "source": item.get("source") or "",
                    "source_status": item.get("source_status") or "",
                    "report_date": item.get("report_date") or "",
                }
            )
    for fund in by_fund.values():
        seen = set()
        deduped = []
        for holding in fund.get("holdings", []):
            key = (str(holding.get("code") or ""), str(holding.get("name") or ""))
            if key in seen:
                continue
            seen.add(key)
            deduped.append(holding)
        fund["holdings"] = deduped
    market_snapshot = _market_quote_snapshot(dict(etfs), dict(indices), dict(sectors), data_date, decision_time)
    return {
        "data_date": data_date,
        "decision_time": decision_time,
        "funds": dict(by_fund),
        "securities": dict(securities),
        "etfs": dict(etfs),
        "indices": dict(indices),
        "sectors": dict(sectors),
        "market_quote_snapshot": market_snapshot,
        "stale_fields": stale_fields[:200],
        "stale_field_count": len(stale_fields),
        "source_field_count": len(field_list),
        "data_sources": sources[:120],
    }


def render_fund_context_report(context: Dict[str, Any], fields: List[SqlField], config_path: str, db_path: str, decision_time: str) -> str:
    lines = [
        "# fund_context_report 基金盘中上下文",
        "",
        f"- 配置文件：`{config_path}`",
        f"- SQLite：`{db_path}`",
        f"- 决策时间：{decision_time}",
        f"- SQL字段数：{len(fields)}",
        "",
        "## 1. 基金上下文",
        "",
    ]
    if not context["funds"]:
        lines.append("- 未从 SQL 读取到基金上下文。")
    for code, item in context["funds"].items():
        name = item["fields"].get("fund_name") or item["fields"].get("fund_name", "")
        fund_type = item["fields"].get("fund_type") or item["fields"].get("inferred_type") or "-"
        lines.extend(
            [
                f"### {code} {name}",
                f"- 类型：{fund_type}",
                f"- 角色：{item['fields'].get('role') or item['fields'].get('inferred_role') or '-'}",
                f"- 仓位：{item['fields'].get('position_pct') or '-'}",
                f"- 估算净值：{item['estimates'].get('estimate_nav') or item['fields'].get('estimate_nav') or '-'}",
                f"- 估算涨跌：{item['estimates'].get('estimate_change_pct') or item['fields'].get('estimate_change_pct') or '-'}",
                f"- 最新净值：{item['nav'].get('unit_nav') or item['fields'].get('published_nav') or '-'}",
                f"- 持仓条目：{len(item.get('holdings', []))}",
                "",
            ]
        )
        if fund_type == "etf_feeder":
            lines.extend(
                [
                    "> ETF联接基金核心判断依据是 tracking ETF / index / sector；披露股票持仓若占比低，只作为辅助材料。",
                    "",
                ]
            )
        lines.extend(["#### 持仓股票字段", "", _holding_table(item, context["securities"]), ""])
    lines.extend(
        [
            "## 2. ETF / 指数 / 板块上下文",
            "",
            f"- 数据日期：{context.get('data_date') or '-'}",
            f"- 快照时间：{context.get('market_quote_snapshot', {}).get('snapshot_time') or '-'}",
            f"- ETF数量：{context.get('market_quote_snapshot', {}).get('etf_count', 0)}",
            f"- 指数数量：{context.get('market_quote_snapshot', {}).get('index_count', 0)}",
            f"- 板块数量：{context.get('market_quote_snapshot', {}).get('sector_count', 0)}",
            "",
            "### ETF 今日盘中表现",
            "",
            _market_table(context.get("etfs", {}), kind="etf"),
            "",
            "### 指数今日盘中表现",
            "",
            _market_table(context.get("indices", {}), kind="index"),
            "",
            "### 板块今日盘中表现",
            "",
            _sector_table(context["sectors"]),
            "",
            "## 3. 持仓证券上下文",
            "",
            _security_table(context["securities"]),
            "",
            "## 4. SQL全字段明细",
            "",
            render_sql_field_report([field for field in fields if field.include_in_llm], config_path, db_path, decision_time),
        ]
    )
    return "\n".join(lines) + "\n"


def _security_table(securities: Dict[str, Dict[str, Any]]) -> str:
    lines = ["| 代码 | 名称 | 价格/收盘 | 涨跌幅 | MA5 | MA10 | MA20 |", "| --- | --- | ---: | ---: | ---: | ---: | ---: |"]
    if not securities:
        lines.append("| - | - | - | - | - | - | - |")
        return "\n".join(lines)
    for code, item in sorted(securities.items()):
        lines.append(f"| {code} | {item.get('name', '')} | {item.get('latest_price') or item.get('close') or '-'} | {item.get('change_pct') or item.get('pct_chg') or '-'} | {item.get('ma5') or '-'} | {item.get('ma10') or '-'} | {item.get('ma20') or '-'} |")
    return "\n".join(lines)


def _holding_table(fund: Dict[str, Any], securities: Dict[str, Dict[str, Any]]) -> str:
    lines = [
        "| 股票 | 权重 | 最新价 | 涨跌幅 | 成交额 | 换手率 | MA20 | 趋势 | quote_source | ma_source | final_source | missing_fields |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- | --- | --- |",
    ]
    holdings = fund.get("holdings", [])
    if not holdings:
        lines.append("| - | - | missing | missing | missing | missing | missing | missing | missing | missing | missing | holding_stock_code |")
        return "\n".join(lines)
    for holding in holdings:
        code = str(holding.get("code") or "")
        item = securities.get(code, {})
        missing = [
            field
            for field in ["latest_price", "change_pct", "amount", "turnover_rate", "ma20", "trend_status", "final_source"]
            if item.get(field) in (None, "")
        ]
        final_source = item.get("final_source") or item.get("source") or "missing"
        quote_source = final_source if item.get("latest_price") not in (None, "") else "missing"
        ma_source = item.get("history_source") or final_source if item.get("ma20") not in (None, "") else "missing"
        stock = f"{code} {holding.get('name') or item.get('name') or ''}".strip()
        lines.append(
            f"| {_md(stock)} | {_md(holding.get('weight_pct') or '-')} | {_md(item.get('latest_price') or 'missing')} | "
            f"{_md(item.get('change_pct') if item.get('change_pct') not in (None, '') else 'missing')} | "
            f"{_md(item.get('amount') if item.get('amount') not in (None, '') else 'missing')} | "
            f"{_md(item.get('turnover_rate') if item.get('turnover_rate') not in (None, '') else 'missing')} | "
            f"{_md(item.get('ma20') if item.get('ma20') not in (None, '') else 'missing')} | "
            f"{_md(item.get('trend_status') or 'missing')} | {_md(quote_source)} | {_md(ma_source)} | {_md(final_source)} | "
            f"{_md(','.join(missing) if missing else '-') } |"
        )
    return "\n".join(lines)


def _sector_table(sectors: Dict[str, Dict[str, Any]]) -> str:
    lines = ["| 板块 | 今日涨跌幅 | 成交额 | 来源 | 状态 |", "| --- | ---: | ---: | --- | --- |"]
    if not sectors:
        lines.append("| - | missing | missing | missing | missing |")
        return "\n".join(lines)
    for name, item in sorted(sectors.items()):
        lines.append(f"| {_md(name)} | {_md(_value(item.get('change_pct')))} | {_md(_value(item.get('amount')))} | {_md(item.get('final_source') or item.get('source') or 'missing')} | {_md(item.get('source_status') or 'missing')} |")
    return "\n".join(lines)


def _market_table(items: Dict[str, Dict[str, Any]], kind: str) -> str:
    title = "ETF" if kind == "etf" else "指数"
    price_title = "最新价" if kind == "etf" else "最新点位"
    lines = [f"| {title} | 名称 | {price_title} | 今日涨跌幅 | 成交额 | 来源 | 状态 |", "| --- | --- | ---: | ---: | ---: | --- | --- |"]
    if not items:
        lines.append("| - | - | missing | missing | missing | missing | missing |")
        return "\n".join(lines)
    for code, item in sorted(items.items()):
        lines.append(
            f"| {_md(code)} | {_md(item.get('name') or '')} | {_md(_value(item.get('latest_price')))} | "
            f"{_md(_value(item.get('change_pct')))} | {_md(_value(item.get('amount')))} | "
            f"{_md(item.get('final_source') or item.get('source') or 'missing')} | {_md(item.get('source_status') or 'missing')} |"
        )
    return "\n".join(lines)


def _terminal_summary(context: Dict[str, Any], report_path: Path) -> str:
    return "\n".join(
        [
            "fund_context_report 摘要",
            f"基金数: {len(context.get('funds', {}))}",
            f"证券数: {len(context.get('securities', {}))}",
            f"板块数: {len(context.get('sectors', {}))}",
            f"报告: {report_path}",
        ]
    )


def _merge_json_fund_context(item: Dict[str, Any], value: Any) -> None:
    payload = _json_load(value)
    if not payload:
        return
    for key in ["name", "fund_name", "type", "role", "position_pct", "risk_level", "estimate_nav", "estimate_change_pct"]:
        if key in payload and payload.get(key) not in (None, ""):
            target_key = "fund_name" if key == "name" else ("fund_type" if key == "type" else key)
            item["fields"].setdefault(target_key, payload.get(key))
    tracking = payload.get("tracking") if isinstance(payload.get("tracking"), dict) else payload
    if isinstance(tracking, dict):
        item["tracking"].update({k: v for k, v in tracking.items() if k in {"etfs", "indices", "sectors", "top_holdings_mode"}})
        stocks = tracking.get("stocks") or tracking.get("top_holdings") or tracking.get("manual_holdings") or []
        if isinstance(stocks, list):
            for stock in stocks:
                if not isinstance(stock, dict):
                    continue
                code = stock.get("holding_stock_code") or stock.get("code") or stock.get("stock_code")
                name = stock.get("holding_stock_name") or stock.get("name") or stock.get("stock_name") or ""
                if code or name:
                    item["holdings"].append(
                        {
                            "code": code or "",
                            "name": name,
                            "weight_pct": stock.get("holding_weight_pct") or stock.get("weight_pct") or stock.get("weight"),
                            "market": stock.get("holding_market") or stock.get("market") or "",
                            "source": stock.get("source") or "fund_enrichment_result",
                            "source_status": stock.get("source_status") or "success",
                            "report_date": stock.get("report_date") or "",
                        }
                    )


def _json_load(value: Any) -> Dict[str, Any]:
    if not value:
        return {}
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _short(value: Any, limit: int = 160) -> str:
    text = "" if value is None else str(value)
    text = text.replace("\n", " ").replace("|", "/")
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _md(value: Any) -> str:
    return _short(value).replace("|", "\\|")


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


def _market_target(
    entity_type: str,
    securities: Dict[str, Dict[str, Any]],
    etfs: Dict[str, Dict[str, Any]],
    indices: Dict[str, Dict[str, Any]],
    sectors: Dict[str, Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    if entity_type == "etf":
        return etfs
    if entity_type == "index":
        return indices
    if entity_type == "sector":
        return sectors
    return securities


def _market_quote_snapshot(
    etfs: Dict[str, Dict[str, Any]],
    indices: Dict[str, Dict[str, Any]],
    sectors: Dict[str, Dict[str, Any]],
    data_date: str,
    decision_time: str,
) -> Dict[str, Any]:
    snapshot_time = _snapshot_time(decision_time)
    return {
        "trade_date": data_date,
        "snapshot_time": snapshot_time,
        "etf_count": _success_count(etfs),
        "index_count": _success_count(indices),
        "sector_count": _success_count(sectors),
    }


def _success_count(items: Dict[str, Dict[str, Any]]) -> int:
    return sum(1 for item in items.values() if item.get("source_status") == "success")


def _snapshot_time(decision_time: str) -> str:
    return {"1000": "10:00:00", "1445": "14:45:00", "night": "21:30:00"}.get(str(decision_time), str(decision_time))


def _value(value: Any) -> Any:
    return "missing" if value in (None, "") else value
