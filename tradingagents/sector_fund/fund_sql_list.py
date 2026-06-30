from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List

import yaml


CORE_TABLES = [
    "portfolio",
    "fund_config",
    "fund_nav_daily",
    "fund_intraday_estimate",
    "fund_holding_snapshot",
    "security_master",
    "security_quote_snapshot",
    "security_kline_daily",
    "security_indicator_daily",
    "sector_snapshot",
    "market_snapshot",
    "estimate_error",
    "intraday_snapshot",
    "data_source_run",
    "field_source",
    "fund_enrichment_result",
]


@dataclass
class SqlField:
    table_name: str
    row_id: str
    entity_type: str
    entity_code: str
    entity_name: str
    field_name: str
    value: Any
    source: str
    source_status: str
    trade_date: str
    decision_time: str
    include_in_llm: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return self.__dict__.copy()


def run_fund_sql_list(
    config_path: str = "config/personal_fund_portfolio.yaml",
    db_path: str | None = None,
    decision_time: str = "1445",
    output_dir: str | Path = "reports/fund_intraday",
    limit_per_table: int = 200,
    view: bool = False,
) -> Dict[str, Any]:
    config = _load_config(config_path)
    resolved_db_path = db_path or config.get("database", {}).get("path") or "data/fund_assistant.sqlite3"
    fields = list_sql_fields(resolved_db_path, decision_time=decision_time, limit_per_table=limit_per_table)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    trade_date = _latest_trade_date(fields)
    report_path = output_path / f"fund_sql_list_{trade_date}_{decision_time}.md"
    json_path = output_path / f"fund_sql_list_{trade_date}_{decision_time}.json"
    report = render_sql_field_report(fields, config_path=config_path, db_path=resolved_db_path, decision_time=decision_time)
    report_path.write_text(report, encoding="utf-8")
    json_path.write_text(json.dumps([field.to_dict() for field in fields], ensure_ascii=False, indent=2), encoding="utf-8")
    summary = {
        "field_count": len(fields),
        "table_count": len({field.table_name for field in fields}),
        "report_path": str(report_path),
        "json_path": str(json_path),
        "db_path": resolved_db_path,
        "trade_date": trade_date,
        "decision_time": decision_time,
    }
    if view:
        print(render_sql_terminal_summary(fields, summary))
    return {"fields": [field.to_dict() for field in fields], **summary}


def list_sql_fields(db_path: str | Path, decision_time: str = "1445", limit_per_table: int = 200) -> List[SqlField]:
    path = Path(db_path)
    if not path.exists():
        return []
    fields: List[SqlField] = []
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        tables = _existing_tables(conn)
        for table in [item for item in CORE_TABLES if item in tables]:
            rows = _recent_rows(conn, table, decision_time=decision_time, limit=limit_per_table)
            for row_index, row in enumerate(rows):
                row_dict = dict(row)
                row_id = str(row_dict.get("id") or f"{table}:{row_index}")
                entity = _infer_entity(table, row_dict)
                for field_name, value in row_dict.items():
                    if field_name in {"created_at", "updated_at"}:
                        continue
                    fields.append(
                        SqlField(
                            table_name=table,
                            row_id=row_id,
                            entity_type=entity["entity_type"],
                            entity_code=entity["entity_code"],
                            entity_name=entity["entity_name"],
                            field_name=field_name,
                            value=value,
                            source=str(row_dict.get("source") or row_dict.get("estimate_source") or row_dict.get("source_name") or table),
                            source_status=str(row_dict.get("source_status") or row_dict.get("fetch_status") or ""),
                            trade_date=str(row_dict.get("trade_date") or row_dict.get("event_date") or row_dict.get("report_date") or ""),
                            decision_time=str(row_dict.get("decision_time") or decision_time),
                            include_in_llm=_include_field(table, field_name, value),
                        )
                    )
    return fields


def list_sql_fields_for_context(db_path: str | Path, decision_time: str = "1445", limit_per_table: int = 800) -> List[SqlField]:
    """Return a compact, latest-only SQL field view for LLM context.

    fund_sql_list remains the full inspection surface. Agent/context reports use
    this view so historical field_source/security rows do not pollute prompts.
    """
    fields = list_sql_fields(db_path, decision_time=decision_time, limit_per_table=limit_per_table)
    data_date = _context_data_date(fields)
    current_quote_codes = {
        _normalize_code(field.entity_code)
        for field in fields
        if field.table_name == "security_quote_snapshot"
        and field.trade_date == data_date
        and field.source_status == "success"
        and field.entity_code
    }
    filtered: List[SqlField] = []
    for field in fields:
        if field.table_name in {"field_source", "security_quote_snapshot", "fund_intraday_estimate"}:
            if data_date and field.trade_date and field.trade_date != data_date:
                continue
        if field.table_name == "intraday_snapshot":
            if data_date and field.trade_date and field.trade_date != data_date:
                continue
        if field.table_name in {"security_kline_daily", "security_indicator_daily"}:
            if data_date and field.trade_date and field.trade_date != data_date and _normalize_code(field.entity_code) in current_quote_codes:
                continue
        filtered.append(field)
    return _dedupe_latest_fields(filtered)


def render_sql_field_report(fields: Iterable[SqlField], config_path: str, db_path: str, decision_time: str) -> str:
    field_list = list(fields)
    lines = [
        "# fund_sql_list SQL 全字段列表",
        "",
        f"- 配置文件：`{config_path}`",
        f"- SQLite：`{db_path}`",
        f"- 决策时间：{decision_time}",
        f"- 字段数：{len(field_list)}",
        f"- 表数量：{len({field.table_name for field in field_list})}",
        "",
        "## 表级统计",
        "",
        "| 表 | 字段行数 | 进入LLM字段 |",
        "| --- | ---: | ---: |",
    ]
    for table in sorted({field.table_name for field in field_list}):
        group = [field for field in field_list if field.table_name == table]
        lines.append(f"| {table} | {len(group)} | {sum(1 for field in group if field.include_in_llm)} |")
    lines.extend(["", "## 持仓股票关键字段", "", _stock_key_field_table(field_list), "", "## 全字段明细", "", _field_table(field_list)])
    return "\n".join(lines) + "\n"


def render_sql_terminal_summary(fields: Iterable[SqlField], summary: Dict[str, Any]) -> str:
    field_list = list(fields)
    lines = [
        "fund_sql_list 摘要",
        f"SQLite: {summary.get('db_path')}",
        f"字段数: {summary.get('field_count')}",
        f"表数量: {summary.get('table_count')}",
        f"报告: {summary.get('report_path')}",
    ]
    for table in sorted({field.table_name for field in field_list})[:20]:
        group = [field for field in field_list if field.table_name == table]
        lines.append(f"- {table}: {len(group)} fields")
    return "\n".join(lines)


def _field_table(fields: List[SqlField], limit: int = 1000) -> str:
    lines = [
        "| 表 | 实体 | 字段 | 值 | 来源 | 状态 | 日期 | LLM |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for field in fields[:limit]:
        entity = f"{field.entity_type}:{field.entity_name or field.entity_code}".strip(":")
        lines.append(
            f"| {_md(field.table_name)} | {_md(entity)} | {_md(field.field_name)} | {_md(_short(field.value))} | "
            f"{_md(field.source)} | {_md(field.source_status)} | {_md(field.trade_date)} | {'yes' if field.include_in_llm else 'no'} |"
        )
    if len(fields) > limit:
        lines.append(f"| ... | ... | ... | 仅展示前 {limit} 行，共 {len(fields)} 行 | ... | ... | ... | ... |")
    return "\n".join(lines)


def _stock_key_field_table(fields: List[SqlField]) -> str:
    key_fields = {"latest_price", "change_pct", "amount", "turnover_rate", "ma5", "ma10", "ma20", "trend_status", "final_source", "audit_status"}
    selected = [field for field in fields if field.entity_type == "stock" and field.field_name in key_fields]
    if not selected:
        return "| 股票 | 字段 | 值 | 来源 | 状态 |\n| --- | --- | --- | --- | --- |\n| - | - | missing | - | - |"
    lines = ["| 股票 | 字段 | 值 | 来源 | 状态 |", "| --- | --- | --- | --- | --- |"]
    for field in selected[:500]:
        stock = field.entity_name or field.entity_code
        lines.append(f"| {_md(stock)} | {_md(field.field_name)} | {_md(_short(field.value))} | {_md(field.source)} | {_md(field.source_status)} |")
    return "\n".join(lines)


def _recent_rows(conn: sqlite3.Connection, table: str, decision_time: str, limit: int) -> List[sqlite3.Row]:
    columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    where = ""
    params: List[Any] = []
    if "decision_time" in columns:
        where = "WHERE decision_time=?"
        params.append(decision_time)
    order_by = "id DESC"
    if "trade_date" in columns:
        order_by = "trade_date DESC, id DESC"
    if "updated_at" in columns:
        order_by = "updated_at DESC, id DESC"
    return conn.execute(f"SELECT * FROM {table} {where} ORDER BY {order_by} LIMIT ?", (*params, limit)).fetchall()


def _existing_tables(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {str(row[0]) for row in rows}


def _infer_entity(table: str, row: Dict[str, Any]) -> Dict[str, str]:
    if row.get("fund_code"):
        return {"entity_type": "fund", "entity_code": str(row.get("fund_code")), "entity_name": str(row.get("fund_name") or "")}
    if row.get("code"):
        return {"entity_type": str(row.get("entity_type") or "security"), "entity_code": str(row.get("code")), "entity_name": str(row.get("name") or "")}
    if row.get("entity_code"):
        return {"entity_type": str(row.get("entity_type") or ""), "entity_code": str(row.get("entity_code") or ""), "entity_name": str(row.get("entity_name") or "")}
    if row.get("sector_name"):
        return {"entity_type": "sector", "entity_code": str(row.get("sector_name")), "entity_name": str(row.get("sector_name"))}
    if row.get("stock_code"):
        return {"entity_type": "stock", "entity_code": str(row.get("stock_code")), "entity_name": str(row.get("stock_name") or "")}
    if table == "portfolio":
        return {"entity_type": "portfolio", "entity_code": str(row.get("name") or row.get("id") or ""), "entity_name": str(row.get("name") or "")}
    return {"entity_type": table, "entity_code": str(row.get("id") or ""), "entity_name": ""}


def _include_field(table: str, field_name: str, value: Any) -> bool:
    if value in (None, "", [], {}):
        return False
    if field_name.endswith("_json") and len(str(value)) > 5000:
        return False
    if table in {"data_source_run"} and field_name in {"raw_text_path", "url"}:
        return False
    return field_name not in {"id", "snapshot_json", "diagnostics_json", "auto_enriched_json", "baostock_code", "baostock_status"}


def _latest_trade_date(fields: List[SqlField]) -> str:
    dates = sorted({field.trade_date for field in fields if field.trade_date}, reverse=True)
    return dates[0] if dates else date.today().isoformat()


def _context_data_date(fields: List[SqlField]) -> str:
    quote_dates = sorted(
        {
            field.trade_date
            for field in fields
            if field.table_name == "security_quote_snapshot"
            and field.trade_date
            and field.source_status == "success"
        },
        reverse=True,
    )
    if quote_dates:
        return quote_dates[0]
    return _latest_trade_date(fields)


def _dedupe_latest_fields(fields: List[SqlField]) -> List[SqlField]:
    def rank(field: SqlField) -> tuple:
        audit_ok = 1 if _field_value(field, "audit_status") == "ok" else 0
        source_ok = 1 if field.source_status == "success" else 0
        source_rank = 2 if _field_value(field, "final_source") else 1 if field.source else 0
        return (field.trade_date, _field_value(field, "data_time") or "", audit_ok, source_ok, source_rank, _row_id_int(field.row_id))

    latest: Dict[tuple[str, str, str, str], SqlField] = {}
    for field in fields:
        key = (field.table_name, field.entity_type, field.entity_code, field.field_name)
        current = latest.get(key)
        if current is None or rank(field) >= rank(current):
            latest[key] = field
    return sorted(latest.values(), key=lambda item: (item.table_name, item.entity_type, item.entity_code, item.field_name))


def _field_value(field: SqlField, name: str) -> Any:
    if field.field_name == name:
        return field.value
    return ""


def _row_id_int(value: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _normalize_code(code: str) -> str:
    text = str(code or "").strip().lower()
    if text.startswith(("sh.", "sz.")):
        text = text.split(".", 1)[1]
    digits = "".join(ch for ch in text if ch.isdigit())
    return digits.zfill(6) if digits else text


def _load_config(config_path: str) -> Dict[str, Any]:
    path = Path(config_path)
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _short(value: Any, limit: int = 160) -> str:
    if isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False)
    else:
        text = "" if value is None else str(value)
    text = text.replace("\n", " ").replace("|", "/")
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _md(value: Any) -> str:
    return _short(value).replace("|", "\\|")
