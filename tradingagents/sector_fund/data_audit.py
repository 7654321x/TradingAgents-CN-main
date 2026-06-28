from __future__ import annotations

import csv
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple


AUDIT_COLUMNS = [
    "run_id",
    "run_time",
    "config_file",
    "entity_type",
    "entity_code",
    "entity_name",
    "field_name",
    "semantic_field",
    "value",
    "value_numeric",
    "trade_date",
    "source",
    "upstream_source",
    "upstream_group",
    "source_level",
    "independent",
    "final_source",
    "source_status",
    "parser_status",
    "raw_text_path",
    "audit_status",
    "audit_reason",
    "fix_suggestion",
]


def build_audit_rows(
    records: Iterable[Any],
    run_id: str,
    run_time: str,
    config_file: str,
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for item in records:
        record = item.to_dict() if hasattr(item, "to_dict") else dict(item)
        fields = list(dict.fromkeys(record.get("matched_fields", []) + record.get("missing_fields", [])))
        for field_name in fields:
            value = _field_value(record, field_name)
            audit_status, audit_reason, fix_suggestion = audit_field(record, field_name, value)
            source_meta = _source_meta(record)
            rows.append(
                {
                    "run_id": run_id,
                    "run_time": run_time,
                    "config_file": config_file,
                    "entity_type": record.get("entity_type", ""),
                    "entity_code": record.get("entity_code", ""),
                    "entity_name": record.get("entity_name", ""),
                    "field_name": field_name,
                    "semantic_field": _semantic_field(field_name),
                    "value": "" if value is None else value,
                    "value_numeric": _numeric(value),
                    "trade_date": _trade_date(record, field_name, value),
                    "source": source_meta["source"],
                    "upstream_source": source_meta["upstream_source"],
                    "upstream_group": source_meta["upstream_group"],
                    "source_level": source_meta["source_level"],
                    "independent": source_meta["independent"],
                    "final_source": "",
                    "source_status": _source_status(record),
                    "parser_status": record.get("parser_status", ""),
                    "raw_text_path": record.get("raw_file", ""),
                    "audit_status": audit_status,
                    "audit_reason": audit_reason,
                    "fix_suggestion": fix_suggestion,
                }
            )
    for row in rows:
        row["final_source"] = _final_source_for_field(rows, row.get("entity_type", ""), row.get("entity_code", ""), row.get("semantic_field", ""))
    return rows


def audit_field(record: Dict[str, Any], field_name: str, value: Any) -> Tuple[str, str, str]:
    fetch_status = record.get("fetch_status", "")
    parser_status = record.get("parser_status", "")
    error_reason = record.get("error_reason", "")
    data = record.get("data", {}) or {}
    entity_type = record.get("entity_type", "")
    entity_code = str(record.get("entity_code", ""))
    field_lower = field_name.lower()

    if fetch_status == "skipped":
        return "skipped", error_reason or "source skipped", _fix_suggestion(record, field_name)
    if fetch_status in {"failed", "dependency_missing"}:
        return "failed", error_reason or fetch_status, _fix_suggestion(record, field_name)
    if field_name in set(record.get("missing_fields", [])):
        if "holdings" in record.get("source_type", ""):
            return "missing", "parser_no_match", _fix_suggestion(record, field_name)
        if field_lower.endswith(".kline") and _as_int(data.get("rows")) == 0:
            return "missing", error_reason or "baostock returned no rows", "use eastmoney index quote as primary source"
        if _is_pct_field(field_lower):
            return "missing", "percentage value is empty", _fix_suggestion(record, field_name)
        if _is_ma_field(field_lower):
            rows = _as_int(data.get("rows"))
            window = _ma_window(field_lower)
            if rows >= window:
                return "suspect", f"{field_name} missing although rows={rows}", f"检查 MA{window} 计算逻辑，rows>={window} 时应能计算对应均线。"
            return "missing", f"insufficient_history: rows={rows}", "历史日K不足，增加 lookback_days 或确认数据源是否返回足够行数。"
        if "科创50" in entity_code and field_lower.endswith(".kline") and _as_int(data.get("rows")) == 0:
            return (
                "missing",
                "科创50 Baostock rows=0",
                "use eastmoney index quote as primary source",
            )
        return "missing", error_reason or "field missing", _fix_suggestion(record, field_name)

    if parser_status == "no_match":
        return "missing", error_reason or "parser no match", _fix_suggestion(record, field_name)

    if field_lower.endswith(".kline"):
        rows = _as_int(data.get("rows"))
        if rows > 0:
            return "ok", f"kline rows={rows}", ""
        return "missing", error_reason or f"kline rows={rows}", _fix_suggestion(record, field_name)

    if field_lower.endswith("latest_trade_date"):
        if not value:
            return "missing", "latest_trade_date is empty", "检查数据源是否返回最近交易日字段。"
        parsed = _parse_date(value)
        if parsed and parsed > date.today():
            return "suspect", "latest_trade_date is later than today", "检查日期字段解析或数据源时区。"
        return "ok", "date looks valid", ""

    if _is_price_field(field_lower):
        number = _numeric(value)
        if number is None or number <= 0:
            return "suspect", "price must be > 0", "检查代码映射、停牌状态或结构化字段映射。"
        if entity_type == "etf" and number > 100:
            return "suspect", "ETF price is unusually high", "确认单位是否被放大，或字段是否取成成交额/指数点位。"
        return "ok", "price looks valid", ""

    if _is_pct_field(field_lower):
        number = _numeric(value)
        if number is None:
            return "missing", "percentage value is empty", _fix_suggestion(record, field_name)
        if abs(number) > 20:
            return "suspect", "percentage move exceeds +/-20%", "检查是否单位错误、取到指数点位，或需要人工确认异常行情。"
        if entity_type == "sector" and data.get("match_method"):
            return "ok", str(data.get("match_method")), ""
        return "ok", "percentage looks valid", ""

    if _is_ma_field(field_lower):
        number = _numeric(value)
        if number is None or number <= 0:
            rows = _as_int(data.get("rows"))
            window = _ma_window(field_lower)
            if rows >= window:
                return "suspect", f"MA{window} missing/invalid although rows={rows}", f"检查 MA{window} 计算逻辑。"
            return "missing", f"insufficient_history: rows={rows}", "历史日K不足，增加 lookback_days。"
        return "ok", "MA looks valid", ""

    if field_lower.endswith("source_status"):
        if str(value) in {"success", "ok"}:
            if entity_type == "sector" and data.get("match_method"):
                return "ok", str(data.get("match_method")), ""
            return "ok", "source status is success", ""
        if str(value) == "missing":
            return "missing", error_reason or "baostock returned no rows", _fix_suggestion(record, field_name)
        if str(value) == "dependency_missing":
            return "failed", "dependency missing", _fix_suggestion(record, field_name)
        return "suspect", f"source_status={value}", _fix_suggestion(record, field_name)

    if value in (None, "", [], {}):
        return "missing", "empty value", _fix_suggestion(record, field_name)
    return "ok", "value present", ""


def cross_validate_quotes(
    records: Iterable[Any],
    eastmoney_records: Iterable[Any] | None = None,
    run_time: str | None = None,
    intraday: bool | None = None,
) -> List[Dict[str, Any]]:
    by_code: Dict[str, Dict[str, Dict[str, Any]]] = {}
    combined = list(records)
    if eastmoney_records is not None:
        combined.extend(list(eastmoney_records))
    for item in combined:
        record = item.to_dict() if hasattr(item, "to_dict") else dict(item)
        code = str(record.get("entity_code", ""))
        if not code:
            continue
        source_type = record.get("source_type", "")
        data = record.get("data", {}) or {}
        if source_type == "baostock_daily_k":
            by_code.setdefault(code, {})["baostock"] = {
                "price": data.get("latest_close"),
                "pct": data.get("pct_chg"),
            }
        if source_type == "eastmoney_push2_quote":
            by_code.setdefault(code, {})["eastmoney"] = {
                "price": data.get("latest_price"),
                "pct": data.get("change_pct"),
            }

    is_intraday = _is_intraday(run_time) if intraday is None else intraday
    rows: List[Dict[str, Any]] = []
    for code, sources in by_code.items():
        if "baostock" not in sources or "eastmoney" not in sources:
            continue
        for field, left_key, right_key in (("price", "price", "price"), ("change_pct", "pct", "pct")):
            left = _numeric(sources["baostock"].get(left_key))
            right = _numeric(sources["eastmoney"].get(right_key))
            if left is None or right is None:
                continue
            diff = abs(left - right)
            if is_intraday:
                status = "daily_vs_intraday"
                reason = "Baostock 为日K，东方财富为盘中行情，差异仅供参考。"
                difference_pct = None if not left else round(diff / abs(left) * 100, 4)
            elif field == "price":
                difference_pct = None if not left else round(diff / abs(left) * 100, 4)
                if difference_pct is None or difference_pct <= 0.5:
                    status = "ok"
                elif difference_pct <= 2:
                    status = "suspect"
                else:
                    status = "suspect"
                reason = "盘后/非交易日价格差异交叉验证"
            else:
                difference_pct = round(diff, 4)
                if diff <= 0.5:
                    status = "ok"
                elif diff <= 2:
                    status = "suspect"
                else:
                    status = "suspect"
                reason = "盘后/非交易日涨跌幅差异交叉验证"
            rows.append(
                {
                    "code": code,
                    "field": field,
                    "baostock_value": left,
                    "eastmoney_value": right,
                    "diff": round(diff, 6),
                    "difference_pct": difference_pct,
                    "audit_status": status,
                    "audit_reason": reason,
                }
            )
    return rows


def write_audit_outputs(
    records: Iterable[Any],
    coverage: Dict[str, Any],
    config_file: str,
    raw_dir: str | Path,
    output_dir: str | Path,
    run_id: str,
    run_time: str | None = None,
) -> Dict[str, Any]:
    run_time = run_time or datetime.now().isoformat(timespec="seconds")
    raw_path = Path(raw_dir)
    output_path = Path(output_dir)
    raw_path.mkdir(parents=True, exist_ok=True)
    output_path.mkdir(parents=True, exist_ok=True)

    record_list = list(records)
    audit_rows = build_audit_rows(record_list, run_id=run_id, run_time=run_time, config_file=config_file)
    cross_rows = cross_validate_quotes(record_list, run_time=run_time)
    cross_audit_rows = _cross_audit_rows(cross_rows, run_id, run_time, config_file)
    csv_path = raw_path / "data_probe_audit.csv"
    json_path = raw_path / "data_probe_audit.json"
    summary_path = output_path / "data_probe_summary.md"

    with csv_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=AUDIT_COLUMNS)
        writer.writeheader()
        writer.writerows(audit_rows + cross_audit_rows)
    json_path.write_text(
        json.dumps({"audit_rows": audit_rows, "cross_validation": cross_rows, "cross_audit_rows": cross_audit_rows, "coverage": coverage}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    summary_path.write_text(render_summary_markdown(audit_rows, coverage, cross_rows), encoding="utf-8")

    return {
        "audit_rows": audit_rows,
        "cross_validation": cross_rows,
        "audit_csv_path": csv_path,
        "audit_json_path": json_path,
        "summary_path": summary_path,
    }


def render_summary_markdown(
    audit_rows: List[Dict[str, Any]],
    coverage: Dict[str, Any],
    cross_rows: List[Dict[str, Any]],
) -> str:
    failed_rows = [row for row in audit_rows if row["audit_status"] in {"missing", "failed", "skipped"}]
    suspect_rows = [row for row in audit_rows if row["audit_status"] == "suspect"]
    lines = [
        "# data_probe 数据摘要",
        "",
        "## 1. 整体覆盖率",
        f"- Core coverage: {coverage.get('core_coverage_rate', 0)}%",
        f"- All coverage: {coverage.get('all_coverage_rate', 0)}%",
        f"- OK fields: {sum(1 for row in audit_rows if row.get('audit_status') == 'ok')}",
        f"- Missing fields: {len(failed_rows)}",
        f"- Suspicious fields: {len(suspect_rows)}",
        "",
        "## 2. ETF 数据",
        _entity_table(audit_rows, "etf"),
        "",
        "## 3. 指数数据",
        _entity_table(audit_rows, "index"),
        "",
        "## 4. 基金估算数据",
        _fund_table(audit_rows),
        "",
        "## 5. 板块数据",
        _sector_table(audit_rows),
        "",
        "## 6. 失败字段",
        _failure_table(failed_rows),
        "",
        "## 7. 可疑数据",
        _suspect_table(suspect_rows),
        "",
        "## 8. 交叉验证",
        _cross_table(cross_rows),
        "",
        "## 9. 最终采用数据源",
        _final_source_table(audit_rows),
        "",
        "## 10. 数据源分组",
        _source_group_table(),
        "",
        "## 11. AKShare 基金估算",
        _akshare_fund_estimate_table(audit_rows),
        "",
        "## 12. AKShare 基金持仓",
        _akshare_holding_table(audit_rows),
        "",
        "## 13. 读取通道一致性检查",
        _consistency_table(audit_rows),
        "",
    ]
    return "\n".join(lines)


def render_terminal_summary(
    audit_rows: List[Dict[str, Any]],
    coverage: Dict[str, Any],
    cross_rows: List[Dict[str, Any]] | None = None,
) -> str:
    suspect_count = sum(1 for row in audit_rows if row.get("audit_status") == "suspect")
    failed_count = sum(1 for row in audit_rows if row.get("audit_status") in {"missing", "failed", "skipped"})
    ok_count = sum(1 for row in audit_rows if row.get("audit_status") == "ok")
    lines = [
        "data_probe view 摘要",
        "【覆盖率】",
        f"Core: {coverage.get('core_coverage_rate', 0)}%",
        f"All: {coverage.get('all_coverage_rate', 0)}%",
        f"Core coverage: {coverage.get('core_coverage_rate', 0)}%",
        f"All coverage: {coverage.get('all_coverage_rate', 0)}%",
        f"OK字段: {ok_count}",
        f"可疑字段: {suspect_count}",
        f"失败/缺失字段: {failed_count}",
        "",
        "【AKShare】",
        _terminal_akshare_rows(audit_rows),
        "",
        "【估算误差/偏差提示】",
        _terminal_estimate_warning_rows(audit_rows),
        "",
        "【Baostock ETF】",
        _terminal_entity_rows(audit_rows, "etf", source="baostock", all_rows=audit_rows),
        "",
        "【Baostock 指数】",
        _terminal_entity_rows(audit_rows, "index", source="baostock", all_rows=audit_rows),
        "",
        "【最终采用数据源】",
        _terminal_adoption_rows(audit_rows),
        "",
        "【失败字段】",
        _terminal_failure_rows(audit_rows),
        "",
        "【交叉验证】",
        _terminal_cross_rows(cross_rows or []),
        "",
        "【同源读取一致性检查】",
        _terminal_consistency_rows(audit_rows),
    ]
    return "\n".join(lines)


def load_latest_audit(raw_root: str | Path = "data/debug_raw") -> Dict[str, Any]:
    root = Path(raw_root)
    candidates = sorted([item for item in root.glob("*") if item.is_dir()])
    if not candidates:
        raise FileNotFoundError(f"未找到 data_probe raw 目录: {root}")
    latest = candidates[-1]
    audit_json = latest / "data_probe_audit.json"
    if not audit_json.exists():
        raise FileNotFoundError(f"未找到 audit json: {audit_json}")
    return json.loads(audit_json.read_text(encoding="utf-8"))


def _cross_audit_rows(
    cross_rows: List[Dict[str, Any]],
    run_id: str,
    run_time: str,
    config_file: str,
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for row in cross_rows:
        status = row.get("audit_status", "")
        rows.append(
            {
                "run_id": run_id,
                "run_time": run_time,
                "config_file": config_file,
                "entity_type": "cross_validation",
                "entity_code": row.get("code", ""),
                "entity_name": row.get("code", ""),
                "field_name": f"cross_validation.{row.get('code', '')}.{row.get('field', '')}",
                "semantic_field": row.get("field", ""),
                "value": row.get("diff", ""),
                "value_numeric": row.get("difference_pct"),
                "trade_date": "",
                "source": "baostock_vs_eastmoney",
                "upstream_source": "mixed",
                "upstream_group": "cross_group",
                "source_level": "diagnostic",
                "independent": True,
                "final_source": "",
                "source_status": "success",
                "parser_status": "success",
                "raw_text_path": "",
                "audit_status": status,
                "audit_reason": row.get("audit_reason", ""),
                "fix_suggestion": "" if status in {"ok", "daily_vs_intraday"} else "对照 Baostock 日K与东方财富行情接口，确认交易时段和复权/单位是否一致。",
            }
        )
    return rows


def _final_source_table(rows: List[Dict[str, Any]]) -> str:
    lines = ["| entity_type | entity_code | entity_name | semantic_field | final_source | upstream_group | independent | value | status |"]
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    seen = set()
    for row in rows:
        key = (row.get("entity_type"), row.get("entity_code"), row.get("semantic_field"))
        if key in seen or not row.get("entity_code"):
            continue
        seen.add(key)
        final_source = row.get("final_source") or _final_source_for_field(rows, row.get("entity_type", ""), row.get("entity_code", ""), row.get("semantic_field", ""))
        winner = _winner_row(rows, row.get("entity_type", ""), row.get("entity_code", ""), row.get("semantic_field", ""), final_source)
        lines.append(
            f"| {_md(row.get('entity_type', ''))} | {_md(row.get('entity_code', ''))} | {_md(row.get('entity_name', ''))} | {_md(row.get('semantic_field', ''))} | {_md(final_source)} | {_md((winner or row).get('upstream_group', ''))} | {_md((winner or row).get('independent', ''))} | {_md((winner or row).get('value', ''))} | {_md((winner or row).get('audit_status', ''))} |"
        )
    return "\n".join(lines)


def _source_group_table() -> str:
    return "\n".join(
        [
            "| group | sources | 说明 |",
            "| --- | --- | --- |",
            "| eastmoney | tiantianfund_direct / eastmoney_push2 / akshare | 同上游读取通道，只做一致性提示，不作为独立交叉验证 |",
            "| baostock | baostock | 独立结构化 provider，用于历史K线、MA、最近交易日 |",
            "| official_disclosure | cninfo / exchange / fund_company | 官方披露源，适合公告和合同 |",
            "| supplementary | pywencai / firecrawl / raw_html | 补充和诊断，不作为主链路 |",
        ]
    )


def _akshare_fund_estimate_table(rows: List[Dict[str, Any]]) -> str:
    grouped = _group_rows([row for row in rows if row.get("source") == "akshare" and row.get("field_name", "").startswith("akshare.fund.")], "fund")
    lines = ["| 基金代码 | 基金名称 | 估算日期 | 估算净值 | 估算涨跌幅 | 公布单位净值 | 公布日增长率 | 估算偏差 | stale | 可信度 | warning | source/upstream_group |"]
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    if not grouped:
        lines.append("| - | - | - | - | - | - | - | - | - | - | - | akshare/eastmoney |")
        return "\n".join(lines)
    for code, item in grouped.items():
        values = item["values"]
        lines.append(
            f"| {_md(code)} | {_md(item.get('name', ''))} | {_md(_first(values, 'estimate_date'))} | {_md(_first(values, 'estimate_nav'))} | {_md(_first(values, 'estimate_change_pct'))} | {_md(_first(values, 'published_nav'))} | {_md(_first(values, 'published_change_pct'))} | {_md(_first(values, 'estimate_bias_pct'))} | {_md(_first(values, 'is_stale'))} | {_md(_first(values, 'estimate_reliability'))} | {_md(_first(values, 'estimate_warning'))} | akshare/eastmoney |"
        )
    return "\n".join(lines)


def _akshare_holding_table(rows: List[Dict[str, Any]]) -> str:
    grouped = _group_rows([row for row in rows if row.get("source") == "akshare" and "top_holdings" in row.get("field_name", "")], "fund")
    lines = ["| 基金代码 | 基金名称 | 季度 | 前十大持仓 | 占净值比例 | 持仓滞后提示 |"]
    lines.append("| --- | --- | --- | --- | --- | --- |")
    if not grouped:
        lines.append("| - | - | - | - | - | - |")
        return "\n".join(lines)
    for code, item in grouped.items():
        holdings = item["values"].get("top_holdings")
        if isinstance(holdings, str):
            try:
                holdings = json.loads(holdings)
            except Exception:
                holdings = []
        names = ", ".join(str(row.get("holding_stock_name") or row.get("holding_stock_code") or "") for row in (holdings or [])[:10])
        weights = ", ".join(str(row.get("holding_weight_pct") or "") for row in (holdings or [])[:10])
        quarter = ""
        if holdings:
            quarter = str(holdings[0].get("quarter_label") or "")
        lines.append(f"| {_md(code)} | {_md(item.get('name', ''))} | {_md(quarter)} | {_md(names)} | {_md(weights)} | 基金持仓来自季度披露，存在滞后，不代表实时持仓。 |")
    return "\n".join(lines)


def _consistency_table(rows: List[Dict[str, Any]]) -> str:
    checks = []
    for entity_type, entity_code, semantic in sorted({(r.get("entity_type"), r.get("entity_code"), r.get("semantic_field")) for r in rows if r.get("entity_code")}):
        ok_rows = [r for r in rows if r.get("entity_type") == entity_type and r.get("entity_code") == entity_code and r.get("semantic_field") == semantic and r.get("audit_status") == "ok"]
        groups = {r.get("upstream_group") for r in ok_rows}
        if len(ok_rows) >= 2 and len(groups) == 1:
            checks.append((entity_type, entity_code, semantic, list(groups)[0], "read_consistency_check"))
    lines = ["| entity | semantic_field | upstream_group | check_type |"]
    lines.append("| --- | --- | --- | --- |")
    if not checks:
        lines.append("| - | - | - | - |")
        return "\n".join(lines)
    for entity_type, entity_code, semantic, group, check_type in checks[:30]:
        lines.append(f"| {_md(entity_type + ':' + entity_code)} | {_md(semantic)} | {_md(group)} | {_md(check_type)} |")
    return "\n".join(lines)


def _winner_row(rows: List[Dict[str, Any]], entity_type: str, entity_code: str, semantic_field: str, final_source: str) -> Dict[str, Any] | None:
    for row in rows:
        if row.get("entity_type") == entity_type and str(row.get("entity_code", "")) == str(entity_code) and row.get("semantic_field") == semantic_field and row.get("source") == final_source and row.get("audit_status") == "ok":
            return row
    return None


def _entity_table(rows: List[Dict[str, Any]], entity_type: str) -> str:
    grouped = _group_rows(rows, entity_type)
    lines = ["| 代码 | 名称 | 数据日期 | 最新收盘/价格 | 涨跌幅 | MA5 | MA10 | MA20 | 来源 | 状态 | 校验结果 | 最终采用数据源 |"]
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    if not grouped:
        lines.append("| - | - | - | - | - | - | - | - | - | - | - | missing |")
        return "\n".join(lines)
    for key, item in grouped.items():
        values = item["values"]
        lines.append(
            "| "
            + " | ".join(
                [
                    _md(key),
                    _md(item.get("name", "")),
                    _md(_first(values, "latest_trade_date")),
                    _md(_first(values, "latest_close", "latest_price")),
                    _md(_first(values, "pct_chg", "change_pct")),
                    _md(_first(values, "ma5")),
                    _md(_first(values, "ma10")),
                    _md(_first(values, "ma20")),
                    _md(item.get("source", "")),
                    _md(item.get("source_status", "")),
                    _md(item.get("audit_status", "")),
                    _md(_adopted_source(rows, entity_type, key)),
                ]
            )
            + " |"
        )
    return "\n".join(lines)


def _fund_table(rows: List[Dict[str, Any]]) -> str:
    grouped = _group_rows(rows, "fund")
    lines = ["| 基金代码 | 基金名称 | 估算净值 | 估算涨跌 | 估算时间 | 上一单位净值 | 来源 | 状态 | 校验结果 | 最终采用数据源 |"]
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    if not grouped:
        lines.append("| - | - | - | - | - | - | - | - | - | missing |")
        return "\n".join(lines)
    for key, item in grouped.items():
        values = item["values"]
        lines.append(
            "| "
            + " | ".join(
                [
                    _md(key),
                    _md(item.get("name", "")),
                    _md(_first(values, "estimate_nav")),
                    _md(_first(values, "estimate_change_pct")),
                    _md(_first(values, "estimate_time")),
                    _md(_first(values, "previous_unit_nav", "unit_nav")),
                    _md(item.get("source", "")),
                    _md(item.get("source_status", "")),
                    _md(item.get("audit_status", "")),
                    _md(_adopted_source(rows, "fund", key)),
                ]
            )
            + " |"
        )
    return "\n".join(lines)


def _sector_table(rows: List[Dict[str, Any]]) -> str:
    grouped = _group_rows(rows, "sector")
    lines = ["| 板块 | 涨跌幅 | 来源 | 状态 | 校验结果 | 最终采用数据源 |"]
    lines.append("| --- | --- | --- | --- | --- | --- |")
    if not grouped:
        lines.append("| - | - | - | - | - | missing |")
        return "\n".join(lines)
    for key, item in grouped.items():
        values = item["values"]
        lines.append(
            f"| {_md(key)} | {_md(_first(values, 'change_pct'))} | {_md(item.get('source', ''))} | {_md(item.get('source_status', ''))} | {_md(item.get('audit_status', ''))} | {_md(_adopted_source(rows, 'sector', key))} |"
        )
    return "\n".join(lines)


def _failure_table(rows: List[Dict[str, Any]]) -> str:
    lines = ["| 字段 | 来源 | 错误原因 | 修复建议 |"]
    lines.append("| --- | --- | --- | --- |")
    if not rows:
        lines.append("| - | - | - | - |")
        return "\n".join(lines)
    for row in rows:
        lines.append(
            f"| {_md(row['field_name'])} | {_md(row['source'])} | {_md(row['audit_reason'])} | {_md(row['fix_suggestion'])} |"
        )
    return "\n".join(lines)


def _suspect_table(rows: List[Dict[str, Any]]) -> str:
    lines = ["| 实体 | 字段 | 当前值 | 可疑原因 | 建议人工复核方式 |"]
    lines.append("| --- | --- | --- | --- | --- |")
    if not rows:
        lines.append("| - | - | - | - | - |")
        return "\n".join(lines)
    for row in rows:
        entity = f"{row.get('entity_name') or row.get('entity_code')}({row.get('entity_code')})"
        lines.append(
            f"| {_md(entity)} | {_md(row['field_name'])} | {_md(row['value'])} | {_md(row['audit_reason'])} | {_md(row['fix_suggestion'] or '对照原始数据源页面/API返回值人工核对。')} |"
        )
    return "\n".join(lines)


def _cross_table(rows: List[Dict[str, Any]]) -> str:
    lines = ["| 代码 | 字段 | Baostock 值 | 东方财富值 | 差异 | 差异% | 校验结果 |"]
    lines.append("| --- | --- | --- | --- | --- | --- | --- |")
    if not rows:
        lines.append("| - | - | - | - | - | - | 无可交叉验证字段 |")
        return "\n".join(lines)
    for row in rows:
        lines.append(
            f"| {_md(row['code'])} | {_md(row['field'])} | {_md(row['baostock_value'])} | {_md(row['eastmoney_value'])} | {_md(row['diff'])} | {_md(row.get('difference_pct', ''))} | {_md(row['audit_status'])} |"
        )
    return "\n".join(lines)


def _group_rows(rows: List[Dict[str, Any]], entity_type: str) -> Dict[str, Dict[str, Any]]:
    grouped: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        if row.get("entity_type") != entity_type:
            continue
        code = str(row.get("entity_code", ""))
        if not code:
            continue
        item = grouped.setdefault(
            code,
            {
                "name": row.get("entity_name", ""),
                "values": {},
                "source": row.get("source", ""),
                "source_status": row.get("source_status", ""),
                "audit_status": "ok",
            },
        )
        leaf = str(row.get("field_name", "")).split(".")[-1]
        item["values"][leaf] = row.get("value", "")
        if row.get("audit_status") == "ok":
            item["source"] = row.get("source", item.get("source", ""))
            item["source_status"] = row.get("source_status", item.get("source_status", ""))
        if row.get("audit_status") in {"failed", "missing", "skipped"}:
            item["audit_status"] = row.get("audit_status")
        elif row.get("audit_status") == "suspect" and item["audit_status"] == "ok":
            item["audit_status"] = "suspect"
        if row.get("source_status") and item.get("source_status") in {"", "success"}:
            item["source_status"] = row.get("source_status")
    return grouped


def _terminal_entity_rows(rows: List[Dict[str, Any]], entity_type: str, source: str, all_rows: List[Dict[str, Any]] | None = None) -> str:
    grouped = _group_rows([row for row in rows if row.get("source") == source], entity_type)
    lines = ["代码 名称 日期 收盘 涨跌幅 MA5 MA10 MA20 状态 校验 最终源"]
    if not grouped:
        return "\n".join(lines + ["- - - - - - - - - - -"])
    for key, item in grouped.items():
        values = item["values"]
        lines.append(
            " ".join(
                [
                    _plain(key),
                    _plain(item.get("name", "")),
                    _plain(_first(values, "latest_trade_date")),
                    _plain(_first(values, "latest_close", "latest_price")),
                    _plain(_first(values, "pct_chg", "change_pct")),
                    _plain(_first(values, "ma5")),
                    _plain(_first(values, "ma10")),
                    _plain(_first(values, "ma20")),
                    _plain(item.get("source_status", "")),
                    _plain(item.get("audit_status", "")),
                    _plain(_adopted_source(all_rows or rows, entity_type, key)),
                ]
            )
        )
    return "\n".join(lines)


def _terminal_adoption_rows(rows: List[Dict[str, Any]]) -> str:
    entities = sorted({(row.get("entity_type", ""), row.get("entity_code", ""), row.get("entity_name", "")) for row in rows if row.get("entity_code")})
    lines: List[str] = []
    for entity_type, code, name in entities:
        if entity_type not in {"etf", "index", "stock", "fund", "sector"}:
            continue
        adopted = _adopted_source(rows, entity_type, code)
        if adopted == "missing":
            continue
        baostock = _source_state(rows, entity_type, code, "baostock")
        eastmoney = _source_state(rows, entity_type, code, "eastmoney_push2")
        akshare = _source_state(rows, entity_type, code, "akshare")
        label = name or code
        if baostock or eastmoney or akshare:
            parts = []
            if baostock:
                parts.append(f"Baostock {baostock}")
            if eastmoney:
                parts.append(f"EastMoney {eastmoney}")
            if akshare:
                parts.append(f"AKShare {akshare}")
            lines.append(f"{label}：{'，'.join(parts)}，最终采用 {_display_source(adopted)}。")
        elif adopted in {"tiantianfund_direct", "fallback"}:
            lines.append(f"{label}：最终采用 {_display_source(adopted)}。")
    return "\n".join(lines[:30]) if lines else "-"


def _terminal_akshare_rows(rows: List[Dict[str, Any]]) -> str:
    available = any(row.get("source") == "akshare" and row.get("entity_type") == "source" and row.get("audit_status") == "ok" for row in rows)
    estimate_hit = any(row.get("source") == "akshare" and row.get("semantic_field") == "estimate_change_pct" and row.get("audit_status") == "ok" for row in rows)
    holding_hit = any(row.get("source") == "akshare" and row.get("semantic_field") == "top_holdings" and row.get("audit_status") == "ok" for row in rows)
    return "\n".join(
        [
            f"AKShare 可用: {'yes' if available else 'no'}",
            f"AKShare 基金估算命中: {'yes' if estimate_hit else 'no'}",
            f"AKShare 基金持仓命中: {'yes' if holding_hit else 'no'}",
        ]
    )


def _terminal_estimate_warning_rows(rows: List[Dict[str, Any]]) -> str:
    grouped = _group_rows([row for row in rows if row.get("entity_type") == "fund"], "fund")
    lines = ["基金 估算偏差 公布涨跌 估算涨跌 可信度 提示"]
    for code in ("020671", "025500"):
        item = grouped.get(code)
        if not item:
            continue
        values = item["values"]
        warning = _first(values, "estimate_warning")
        reason = "主动基金估算误差较大，不宜单独作为交易依据。" if str(warning).lower() in {"true", "1"} and code == "025500" else "-"
        lines.append(
            " ".join(
                [
                    code,
                    _plain(_first(values, "estimate_bias_pct", "estimate_error_pct")),
                    _plain(_first(values, "published_change_pct", "daily_change_pct")),
                    _plain(_first(values, "estimate_change_pct")),
                    _plain(_first(values, "estimate_reliability")),
                    reason,
                ]
            )
        )
    return "\n".join(lines) if len(lines) > 1 else "-"


def _terminal_consistency_rows(rows: List[Dict[str, Any]]) -> str:
    text = _consistency_table(rows).splitlines()
    return "\n".join(text[:12])


def _terminal_failure_rows(rows: List[Dict[str, Any]]) -> str:
    failed = [row for row in rows if row.get("audit_status") in {"missing", "failed", "skipped", "suspect", "suspect_high"}]
    lines = ["实体 字段 来源 错误原因 修复建议"]
    if not failed:
        return "\n".join(lines + ["- - - - -"])
    for row in failed[:30]:
        entity = row.get("entity_name") or row.get("entity_code") or row.get("entity_type") or "-"
        lines.append(
            " ".join(
                [
                    _plain(entity),
                    _plain(row.get("field_name", "")),
                    _plain(row.get("source", "")),
                    _plain(row.get("audit_reason", "")),
                    _plain(row.get("fix_suggestion", "")),
                ]
            )
        )
    if len(failed) > 30:
        lines.append(f"... 还有 {len(failed) - 30} 项，详见 data_probe_summary.md")
    return "\n".join(lines)


def _terminal_cross_rows(rows: List[Dict[str, Any]]) -> str:
    lines = ["代码 字段 Baostock 东方财富 差异 校验"]
    if not rows:
        return "\n".join(lines + ["- - - - - 无可交叉验证字段"])
    for row in rows[:20]:
        diff = row.get("difference_pct")
        diff_text = f"{diff}%" if diff not in (None, "") else str(row.get("diff", ""))
        lines.append(
            " ".join(
                [
                    _plain(row.get("code", "")),
                    _plain(row.get("field", "")),
                    _plain(row.get("baostock_value", "")),
                    _plain(row.get("eastmoney_value", "")),
                    _plain(diff_text),
                    _plain(row.get("audit_status", "")),
                ]
            )
        )
    return "\n".join(lines)


def _adopted_source(rows: List[Dict[str, Any]], entity_type: str, entity_code: str) -> str:
    entity_rows = [row for row in rows if row.get("entity_type") == entity_type and str(row.get("entity_code", "")) == str(entity_code)]
    if not entity_rows:
        return "missing"
    if any(row.get("source") == "eastmoney_push2" and row.get("audit_status") == "ok" for row in entity_rows):
        return "eastmoney_push2"
    if any(row.get("source") == "baostock" and row.get("audit_status") == "ok" for row in entity_rows):
        return "baostock"
    if any(row.get("source") == "tiantianfund_direct" and row.get("audit_status") == "ok" for row in entity_rows):
        return "tiantianfund_direct"
    if any(row.get("source") == "akshare" and row.get("audit_status") == "ok" for row in entity_rows):
        return "akshare"
    if any("raw" in str(row.get("source", "")) and row.get("audit_status") == "ok" for row in entity_rows):
        return "fallback"
    return "missing"


def _final_source_for_field(rows: List[Dict[str, Any]], entity_type: str, entity_code: str, semantic_field: str) -> str:
    matches = [
        row
        for row in rows
        if row.get("entity_type") == entity_type
        and str(row.get("entity_code", "")) == str(entity_code)
        and row.get("semantic_field") == semantic_field
        and row.get("audit_status") == "ok"
    ]
    if not matches:
        return "missing"
    if semantic_field in {"ma5", "ma10", "ma20", "kline", "latest_trade_date"}:
        return _first_source(matches, ["baostock", "akshare"])
    if entity_type in {"etf", "stock", "index"} and semantic_field in {"price", "change_pct", "source_status", "amount"}:
        return _first_source(matches, ["eastmoney_push2", "akshare", "baostock"])
    if entity_type == "fund" and semantic_field in {"estimate_nav", "estimate_change_pct", "estimate_time"}:
        return _first_source(matches, ["tiantianfund_direct", "akshare"])
    if entity_type == "fund" and semantic_field in {"unit_nav", "daily_change_pct", "published_change_pct", "purchase_status", "redeem_status", "top_holdings"}:
        return _first_source(matches, ["akshare", "tiantianfund_direct"])
    if entity_type == "sector":
        return _first_source(matches, ["eastmoney_push2", "akshare"])
    return str(matches[0].get("source") or "missing")


def _first_source(rows: List[Dict[str, Any]], priority: List[str]) -> str:
    sources = [str(row.get("source") or "") for row in rows]
    for source in priority:
        if source in sources:
            return source
    return sources[0] if sources else "missing"


def _source_state(rows: List[Dict[str, Any]], entity_type: str, entity_code: str, source: str) -> str:
    entity_rows = [
        row
        for row in rows
        if row.get("entity_type") == entity_type and str(row.get("entity_code", "")) == str(entity_code) and row.get("source") == source
    ]
    if not entity_rows:
        return ""
    if any(row.get("audit_status") == "ok" for row in entity_rows):
        return "success"
    if any(row.get("audit_status") in {"missing", "failed", "skipped"} for row in entity_rows):
        return "missing"
    if any(row.get("audit_status") == "suspect" for row in entity_rows):
        return "suspect"
    return str(entity_rows[0].get("source_status") or "")


def _source_meta(record: Dict[str, Any]) -> Dict[str, Any]:
    data = record.get("data", {}) or {}
    source_type = str(record.get("source_type", ""))
    if data.get("source"):
        source = str(data.get("source", ""))
        if source in {"eastmoney_push2", "eastmoney_push2_sector"}:
            return {"source": "eastmoney_push2", "upstream_source": "eastmoney", "upstream_group": "eastmoney", "source_level": "direct_endpoint", "independent": False}
        if source in {"tiantian_fund_estimate", "tiantianfund_direct"}:
            return {"source": "tiantianfund_direct", "upstream_source": "eastmoney", "upstream_group": "eastmoney", "source_level": "direct_endpoint", "independent": False}
        if source == "baostock":
            return {"source": "baostock", "upstream_source": "baostock", "upstream_group": "baostock", "source_level": "structured_provider", "independent": True}
        if source == "akshare":
            return {"source": "akshare", "upstream_source": "eastmoney", "upstream_group": "eastmoney", "source_level": "structured_wrapper", "independent": False}
        return {
            "source": source,
            "upstream_source": data.get("upstream_source", data.get("upstream_group", "")),
            "upstream_group": data.get("upstream_group", ""),
            "source_level": data.get("source_level", ""),
            "independent": data.get("independent", False),
        }
    if source_type.startswith("akshare"):
        return {"source": "akshare", "upstream_source": "eastmoney", "upstream_group": "eastmoney", "source_level": "structured_wrapper", "independent": False}
    if source_type.startswith("tiantian_fund"):
        return {"source": "tiantianfund_direct", "upstream_source": "eastmoney", "upstream_group": "eastmoney", "source_level": "direct_endpoint", "independent": False}
    if source_type.startswith("eastmoney_push2"):
        return {"source": "eastmoney_push2", "upstream_source": "eastmoney", "upstream_group": "eastmoney", "source_level": "direct_endpoint", "independent": False}
    if source_type.startswith("baostock"):
        return {"source": "baostock", "upstream_source": "baostock", "upstream_group": "baostock", "source_level": "structured_provider", "independent": True}
    if "cninfo" in source_type:
        return {"source": "cninfo", "upstream_source": "cninfo", "upstream_group": "official_disclosure", "source_level": "official_disclosure", "independent": True}
    if "firecrawl" in source_type:
        return {"source": "firecrawl", "upstream_source": "web", "upstream_group": "supplementary", "source_level": "raw_fallback", "independent": False}
    return {"source": source_type or record.get("source_name", ""), "upstream_source": "web", "upstream_group": "supplementary", "source_level": "raw_fallback", "independent": False}


def _semantic_field(field_name: str) -> str:
    leaf = str(field_name).split(".")[-1]
    return {
        "latest_close": "price",
        "latest_price": "price",
        "pct_chg": "change_pct",
        "estimate_bias_pct": "estimate_bias_pct",
        "top_holdings_weight_pct": "top_holdings_weight_pct",
    }.get(leaf, leaf)


def _display_source(source: str) -> str:
    return {
        "eastmoney_push2": "EastMoney",
        "baostock": "Baostock",
        "tiantianfund_direct": "TiantianFund",
        "akshare": "AKShare",
        "fallback": "fallback",
        "missing": "missing",
    }.get(source, source)


def _field_value(record: Dict[str, Any], field_name: str) -> Any:
    data = record.get("data", {}) or {}
    if field_name in data:
        return data[field_name]
    leaf = field_name.split(".")[-1]
    return data.get(leaf)


def _trade_date(record: Dict[str, Any], field_name: str, value: Any) -> str:
    if field_name.lower().endswith("latest_trade_date") and value:
        return str(value)
    data = record.get("data", {}) or {}
    return str(data.get("latest_trade_date") or data.get("trade_date") or "")


def _source_status(record: Dict[str, Any]) -> str:
    data = record.get("data", {}) or {}
    return str(data.get("source_status") or record.get("fetch_status", ""))


def _fix_suggestion(record: Dict[str, Any], field_name: str) -> str:
    source_type = record.get("source_type", "")
    error = record.get("error_reason", "")
    entity_code = str(record.get("entity_code", ""))
    if "baostock" in source_type and ("No module named" in error or record.get("fetch_status") == "dependency_missing"):
        return "安装 baostock 依赖，并重新运行 data_probe；依赖已在 requirements/pyproject 中声明。"
    if "baostock" in source_type and ("baostock returned no rows" in error or "all candidate index codes returned no rows" in error):
        return "use eastmoney index quote as primary source"
    if "baostock" in source_type and "科创50" in entity_code:
        return "use eastmoney index quote as primary source"
    if "baostock" in source_type and field_name.lower().endswith(".kline"):
        return "use eastmoney index quote as primary source"
    if "firecrawl" in source_type:
        return "配置 FIRECRAWL_API_KEY 后重试；Firecrawl 仅作为 raw_text 兜底。"
    if "holdings" in source_type:
        return "后续优先接入结构化基金持仓接口，不建议长期依赖 raw HTML 正则。"
    if "raw" in source_type or "holdings" in source_type:
        return "打开 raw_text_path 查看页面结构，优先寻找结构化 JSON/API；必要时更新 parser。"
    if "eastmoney_push2_sector" in source_type:
        return "检查板块名称与东方财富板块列表的映射关系，必要时维护别名表。"
    if record.get("parser_status") == "no_match":
        return "抓取成功但 parser 未命中，检查字段名、单位和页面/API结构变化。"
    return "检查数据源状态、代码映射和字段解析逻辑。"


def _is_price_field(field_name: str) -> bool:
    return any(token in field_name for token in ("latest_price", "latest_close", ".close", "estimate_nav", "unit_nav"))


def _is_pct_field(field_name: str) -> bool:
    return any(token in field_name for token in ("pct_chg", "change_pct", "estimate_change_pct", "daily_change_pct"))


def _is_ma_field(field_name: str) -> bool:
    return field_name.endswith(".ma5") or field_name.endswith(".ma10") or field_name.endswith(".ma20")


def _ma_window(field_name: str) -> int:
    if field_name.endswith(".ma5"):
        return 5
    if field_name.endswith(".ma10"):
        return 10
    return 20


def _numeric(value: Any) -> float | None:
    if value in (None, "", "-", "--"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def _parse_date(value: Any) -> date | None:
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _is_intraday(run_time: str | None = None) -> bool:
    try:
        now = datetime.fromisoformat(run_time) if run_time else datetime.now()
    except ValueError:
        now = datetime.now()
    if now.weekday() >= 5:
        return False
    current = now.hour * 100 + now.minute
    return 930 <= current <= 1500


def _first(values: Dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = values.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def _md(value: Any) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ")[:500]


def _plain(value: Any) -> str:
    text = str(value if value is not None else "")
    text = text.replace("\n", " ").replace("\r", " ").strip()
    return text if text else "-"
