from __future__ import annotations

import json
import uuid
from copy import deepcopy
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List

import yaml

from .akshare_provider import AkShareProvider
from .db import get_connection, initialize_database
from .firecrawl_enrich_provider import FirecrawlEnrichProvider
from .fund_classifier import classify_fund
from .fund_tracking_infer import infer_tracking
from .repository import FundRepository


def run_fund_enrich(
    config_path: str = "config/personal_fund_portfolio.yaml",
    output_dir: str | Path = "reports/sector_fund",
    raw_root: str | Path = "data/debug_raw",
    db_path: str | None = None,
    use_akshare: bool | None = None,
    use_firecrawl: bool = False,
    fund_code: str | None = None,
    write_enriched_config: bool = False,
    view: bool = False,
) -> Dict[str, Any]:
    base_path = Path(config_path)
    config = yaml.safe_load(base_path.read_text(encoding="utf-8")) or {}
    run_date = date.today().isoformat()
    run_time = datetime.now().isoformat(timespec="seconds")
    run_id = f"fund_enrich_{run_date}_{uuid.uuid4().hex[:8]}"
    raw_dir = Path(raw_root) / run_date
    raw_dir.mkdir(parents=True, exist_ok=True)

    funds = _enabled_funds(config.get("funds", []), fund_code=fund_code)
    codes = [str(item.get("code") or "").zfill(6) for item in funds if item.get("code")]
    fund_types = {str(item.get("code") or "").zfill(6): str(item.get("type") or "") for item in funds}

    akshare_used = bool(use_akshare if use_akshare is not None else config.get("data_sources", {}).get("akshare", {}).get("enabled", True))
    akshare_payload = _fetch_akshare(codes, fund_types, raw_dir) if akshare_used else _empty_akshare(codes, "akshare disabled")
    firecrawl_payload = _fetch_firecrawl(codes, funds, raw_dir, use_firecrawl=use_firecrawl)

    enriched_funds: List[Dict[str, Any]] = []
    results: List[Dict[str, Any]] = []
    for fund in funds:
        code = str(fund.get("code") or "").zfill(6)
        estimate = akshare_payload["estimates"].get(code, {})
        daily = akshare_payload["daily"].get(code, {})
        nav_history = akshare_payload["nav_history"].get(code, [])
        holdings_payload = akshare_payload["holdings"].get(code, {})
        holdings = holdings_payload.get("top_holdings") or []
        firecrawl = firecrawl_payload.get(code, {})
        fire_fields = firecrawl.get("extracted", {}) or {}

        fund_name = fund.get("name") or daily.get("fund_name") or estimate.get("fund_name") or code
        classifier = classify_fund(
            name=str(fund_name),
            invest_scope=str(fire_fields.get("invest_scope", "")),
            holdings=holdings,
            existing_type=str(fund.get("type") or ""),
        )
        tracking = infer_tracking(
            classifier["fund_type"],
            str(fund_name),
            holdings=holdings,
            existing_tracking=fund.get("tracking", {}),
        )
        enriched = _build_enriched_fund(fund, fund_name, classifier, tracking, estimate, daily, nav_history, holdings_payload, firecrawl)
        enriched_funds.append(enriched)
        results.append(_result_row(code, enriched, estimate, daily, nav_history, holdings_payload, firecrawl, classifier, tracking))

    generated_config = _build_enriched_config(config, enriched_funds)
    generated_path = Path("config/generated") / f"{base_path.stem}.enriched.yaml"
    generated_path.parent.mkdir(parents=True, exist_ok=True)
    generated_path.write_text(yaml.safe_dump(generated_config, allow_unicode=True, sort_keys=False), encoding="utf-8")
    if write_enriched_config:
        # The flag confirms writing the generated file. It intentionally never overwrites the original config.
        generated_path.write_text(yaml.safe_dump(generated_config, allow_unicode=True, sort_keys=False), encoding="utf-8")

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    report_path = output_path / "fund_enrichment_report.md"
    report_path.write_text(_render_report(results, generated_path, akshare_used, use_firecrawl), encoding="utf-8")

    records_path = raw_dir / "fund_enrich_records.json"
    records_path.write_text(
        json.dumps(
            {
                "run_id": run_id,
                "run_time": run_time,
                "config_file": config_path,
                "akshare_used": akshare_used,
                "firecrawl_used": use_firecrawl,
                "results": results,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    resolved_db_path = db_path or config.get("database", {}).get("path") or "data/fund_assistant.sqlite3"
    sql_status = _write_sql(resolved_db_path, run_id, run_date, run_time, results)
    terminal_summary = _terminal_summary(results, generated_path, report_path, use_firecrawl)
    if view:
        print(terminal_summary)
    return {
        "run_id": run_id,
        "results": results,
        "enriched_config_path": str(generated_path),
        "report_path": str(report_path),
        "records_path": str(records_path),
        "raw_dir": str(raw_dir),
        "sql_status": sql_status,
        "terminal_summary": terminal_summary,
        "akshare_used": akshare_used,
        "firecrawl_used": use_firecrawl,
    }


def _fetch_akshare(codes: List[str], fund_types: Dict[str, str], raw_dir: Path) -> Dict[str, Any]:
    provider = AkShareProvider()
    availability = provider.check_available()
    estimates = provider.fetch_fund_estimates(codes, fund_types=fund_types) if availability.get("source_status") == "success" else {}
    daily = provider.fetch_fund_daily_snapshot(codes) if availability.get("source_status") == "success" else {}
    nav_history = provider.fetch_fund_nav_history(codes, tail=20) if availability.get("source_status") == "success" else {}
    holdings = provider.fetch_fund_holdings(codes) if availability.get("source_status") == "success" else {}
    payload = {"availability": availability, "estimates": estimates, "daily": daily, "nav_history": nav_history, "holdings": holdings}
    (raw_dir / "fund_enrich_akshare.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def _empty_akshare(codes: Iterable[str], reason: str) -> Dict[str, Any]:
    failed = {code: {"source_status": "skipped", "error_reason": reason} for code in codes}
    return {"availability": {"source_status": "skipped"}, "estimates": failed, "daily": failed, "nav_history": {}, "holdings": failed}


def _fetch_firecrawl(codes: List[str], funds: List[Dict[str, Any]], raw_dir: Path, use_firecrawl: bool) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if not use_firecrawl:
        payload = {code: {"source_status": "skipped", "parser_status": "skipped", "results": [], "extracted": {}} for code in codes}
    else:
        provider = FirecrawlEnrichProvider()
        by_code = {str(item.get("code") or "").zfill(6): item for item in funds}
        for code in codes:
            payload[code] = provider.search_fund_info(code, str(by_code.get(code, {}).get("name") or ""))
    sanitized = deepcopy(payload)
    (raw_dir / "fund_enrich_firecrawl.json").write_text(json.dumps(sanitized, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def _build_enriched_fund(
    fund: Dict[str, Any],
    fund_name: str,
    classifier: Dict[str, Any],
    tracking: Dict[str, Any],
    estimate: Dict[str, Any],
    daily: Dict[str, Any],
    nav_history: List[Dict[str, Any]],
    holdings_payload: Dict[str, Any],
    firecrawl: Dict[str, Any],
) -> Dict[str, Any]:
    fire_fields = firecrawl.get("extracted", {}) or {}
    firecrawl_validated = _validated_firecrawl_fields(fire_fields)
    enriched = deepcopy(fund)
    enriched["code"] = str(fund.get("code") or "").zfill(6)
    enriched["name"] = fund_name
    enriched["type"] = classifier["fund_type"]
    enriched["role"] = fund.get("role") or "待确认"
    enriched["enabled"] = fund.get("enabled", True)
    enriched["auto_enriched"] = True
    enriched["enrich_confidence"] = _merge_confidence(classifier.get("confidence"), tracking.get("confidence"))
    enriched["manual_review_required"] = bool(classifier.get("manual_review_required") or fund.get("role") in (None, "", "待确认"))
    enriched["fund_company"] = fund.get("fund_company") or firecrawl_validated.get("fund_company", "")
    enriched["fund_manager"] = fund.get("fund_manager") or firecrawl_validated.get("fund_manager", "")
    enriched["invest_scope"] = fund.get("invest_scope") or firecrawl_validated.get("invest_scope", "")
    enriched["benchmark"] = fund.get("benchmark") or firecrawl_validated.get("benchmark", "")
    enriched["estimate_nav"] = estimate.get("estimate_nav")
    enriched["estimate_change_pct"] = estimate.get("estimate_change_pct")
    enriched["published_nav"] = estimate.get("published_nav") or daily.get("unit_nav")
    enriched["published_change_pct"] = estimate.get("published_change_pct") or daily.get("daily_change_pct")
    enriched["purchase_status"] = daily.get("purchase_status")
    enriched["redeem_status"] = daily.get("redeem_status")
    enriched["nav_history"] = nav_history[-20:]
    enriched["top_holdings"] = holdings_payload.get("top_holdings", [])
    enriched["tracking"] = _merge_tracking(fund.get("tracking", {}), tracking)
    enriched["enrichment"] = {
        "fund_name_source": _source_for_name(fund, estimate, daily),
        "fund_type_source": "classifier" if not fund.get("type") else "config",
        "holdings_source": "akshare" if holdings_payload.get("source_status") == "success" else "",
        "firecrawl_used": firecrawl.get("source_status") not in {"skipped", ""},
        "firecrawl_status": firecrawl.get("source_status", "skipped"),
        "firecrawl_debug_only_fields": sorted(set(fire_fields) - set(firecrawl_validated)),
        "holding_is_stale": bool(holdings_payload.get("holding_is_stale")),
        "classifier_reasons": classifier.get("reasons", []),
        "notes": _notes(classifier, tracking, firecrawl),
    }
    return enriched


def _merge_tracking(existing: Dict[str, Any], inferred: Dict[str, Any]) -> Dict[str, Any]:
    result = deepcopy(existing or {})
    result.setdefault("etfs", [])
    result.setdefault("indices", [])
    result.setdefault("sectors", [])
    result.setdefault("manual_holdings", [])
    if inferred.get("stocks") and not result.get("stocks"):
        result["stocks"] = inferred["stocks"]
    if inferred.get("sectors") and not result.get("sectors"):
        result["sectors"] = inferred["sectors"]
    if inferred.get("etfs") and not result.get("etfs"):
        result["etfs"] = inferred["etfs"]
    if inferred.get("indices") and not result.get("indices"):
        result["indices"] = inferred["indices"]
    result["tracking_source"] = inferred.get("tracking_source")
    result["tracking_confidence"] = inferred.get("confidence")
    result["holding_is_stale"] = inferred.get("holding_is_stale")
    return result


def _result_row(
    code: str,
    enriched: Dict[str, Any],
    estimate: Dict[str, Any],
    daily: Dict[str, Any],
    nav_history: List[Dict[str, Any]],
    holdings_payload: Dict[str, Any],
    firecrawl: Dict[str, Any],
    classifier: Dict[str, Any],
    tracking: Dict[str, Any],
) -> Dict[str, Any]:
    missing = []
    for field in ("name", "type", "fund_company", "fund_manager", "invest_scope", "benchmark"):
        if not enriched.get(field):
            missing.append(field)
    if not enriched.get("top_holdings"):
        missing.append("top_holdings")
    if not nav_history:
        missing.append("nav_history")
    source_summary = {
        "akshare_estimate": estimate.get("source_status", "missing"),
        "akshare_daily": daily.get("source_status", "missing"),
        "akshare_holdings": holdings_payload.get("source_status", "missing"),
        "firecrawl": firecrawl.get("source_status", "skipped"),
    }
    return {
        "fund_code": code,
        "fund_name": enriched.get("name"),
        "inferred_type": enriched.get("type"),
        "type_confidence": classifier.get("confidence"),
        "enrich_confidence": enriched.get("enrich_confidence"),
        "manual_review_required": enriched.get("manual_review_required"),
        "estimate_nav": enriched.get("estimate_nav"),
        "estimate_change_pct": enriched.get("estimate_change_pct"),
        "published_nav": enriched.get("published_nav"),
        "published_change_pct": enriched.get("published_change_pct"),
        "purchase_status": enriched.get("purchase_status"),
        "redeem_status": enriched.get("redeem_status"),
        "top_holdings": enriched.get("top_holdings", []),
        "tracking": enriched.get("tracking", {}),
        "missing_fields": missing,
        "source_summary": source_summary,
        "firecrawl": firecrawl,
        "classifier": classifier,
        "tracking_infer": tracking,
        "enriched": enriched,
    }


def _build_enriched_config(config: Dict[str, Any], enriched_funds: List[Dict[str, Any]]) -> Dict[str, Any]:
    generated = deepcopy(config)
    generated.setdefault("portfolio", {})
    generated["portfolio"].setdefault("base_currency", "CNY")
    generated["funds"] = enriched_funds
    generated.setdefault("data_sources", {})
    generated["data_sources"].setdefault("akshare", {"enabled": True})
    return generated


def _write_sql(db_path: str, run_id: str, run_date: str, run_time: str, results: List[Dict[str, Any]]) -> Dict[str, Any]:
    try:
        initialize_database(db_path)
        with get_connection(db_path) as conn:
            repo = FundRepository(conn)
            repo.record_data_source_runs(
                {
                    "run_id": run_id,
                    "trade_date": run_date,
                    "decision_time": "fund_enrich",
                    "source_name": f"fund_enrich_{row['fund_code']}",
                    "source_type": "fund_enrich",
                    "url": "",
                    "fetch_status": "success",
                    "status_code": 200,
                    "raw_text_length": len(json.dumps(row, ensure_ascii=False)),
                    "matched_fields_count": len(_matched_fields(row)),
                    "missing_fields_count": len(row.get("missing_fields", [])),
                    "error_reason": "",
                    "raw_text_path": "",
                }
                for row in results
            )
            conn.executemany(
                """
                INSERT INTO fund_enrichment_result(
                    run_id, fund_code, fund_name, inferred_type, inferred_role,
                    enrich_confidence, manual_review_required, auto_enriched_json,
                    missing_fields_json, source_summary_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                [
                    (
                        run_id,
                        row["fund_code"],
                        row.get("fund_name"),
                        row.get("inferred_type"),
                        row.get("enriched", {}).get("role"),
                        row.get("enrich_confidence"),
                        1 if row.get("manual_review_required") else 0,
                        json.dumps(row.get("enriched", {}), ensure_ascii=False),
                        json.dumps(row.get("missing_fields", []), ensure_ascii=False),
                        json.dumps(row.get("source_summary", {}), ensure_ascii=False),
                    )
                    for row in results
                ],
            )
            conn.executemany(
                """
                INSERT INTO field_source(
                    run_id, entity_type, entity_code, entity_name, field_name, semantic_field,
                    source, upstream_source, upstream_group, source_level, independent,
                    source_status, value_text, parser_status, confidence, audit_status,
                    audit_reason, fix_suggestion, config_file, run_time
                )
                VALUES (?, 'fund', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                _field_source_rows(run_id, run_time, results),
            )
            conn.commit()
        return {"status": "success", "db_path": str(db_path), "run_id": run_id}
    except Exception as exc:
        return {"status": "failed", "db_path": str(db_path), "run_id": run_id, "error_reason": str(exc)}


def _field_source_rows(run_id: str, run_time: str, results: List[Dict[str, Any]]) -> List[tuple[Any, ...]]:
    rows = []
    for row in results:
        values = {
            "fund_name": row.get("fund_name"),
            "inferred_type": row.get("inferred_type"),
            "estimate_nav": row.get("estimate_nav"),
            "estimate_change_pct": row.get("estimate_change_pct"),
            "published_nav": row.get("published_nav"),
            "published_change_pct": row.get("published_change_pct"),
            "top_holdings": row.get("top_holdings"),
        }
        for field, value in values.items():
            source = "akshare" if field not in {"fund_company", "fund_manager", "invest_scope", "benchmark"} else "firecrawl"
            status = "ok" if value not in (None, "", [], {}) else "missing"
            rows.append(
                (
                    run_id,
                    row["fund_code"],
                    row.get("fund_name"),
                    f"fund_enrich.{row['fund_code']}.{field}",
                    field,
                    source,
                    "eastmoney" if source == "akshare" else "web",
                    "eastmoney" if source == "akshare" else "supplementary",
                    "structured_wrapper" if source == "akshare" else "web_search",
                    0,
                    row.get("source_summary", {}).get("akshare_estimate", ""),
                    json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value or ""),
                    "success" if status == "ok" else "no_match",
                    1.0 if status == "ok" else 0.0,
                    status,
                    "value present" if status == "ok" else "empty value",
                    "使用 Firecrawl 或人工补充该字段。" if status != "ok" else "",
                    "",
                    run_time,
                )
            )
    return rows


def _render_report(results: List[Dict[str, Any]], generated_path: Path, akshare_used: bool, firecrawl_used: bool) -> str:
    need_review = [row for row in results if row.get("manual_review_required")]
    lines = [
        "# 基金配置自动补全报告",
        "",
        "## 1. 基金配置补全总览",
        f"- 本次处理基金数: {len(results)}",
        f"- 成功补全数量: {sum(1 for row in results if row.get('fund_name'))}",
        f"- 需要人工确认数量: {len(need_review)}",
        f"- AKShare 是否使用: {'yes' if akshare_used else 'no'}",
        f"- Firecrawl 是否使用: {'yes' if firecrawl_used else 'no'}",
        f"- Enriched config: `{generated_path}`",
        "",
        "## 2. 逐只基金补全结果",
    ]
    for row in results:
        lines.extend(
            [
                "",
                f"### {row.get('fund_code')} {row.get('fund_name')}",
                f"- 自动识别基金类型: {row.get('inferred_type')} / {row.get('type_confidence')}",
                f"- 是否需要人工确认: {row.get('manual_review_required')}",
                f"- 基金估算: {row.get('estimate_nav')} / {row.get('estimate_change_pct')}%",
                f"- 最新净值: {row.get('published_nav')} / {row.get('published_change_pct')}%",
                f"- 申购/赎回: {row.get('purchase_status')} / {row.get('redeem_status')}",
                f"- 前十大持仓: {_holding_names(row.get('top_holdings', []))}",
                f"- tracking.stocks 建议: {_tracking_values(row.get('tracking', {}).get('stocks', []), 'code')}",
                f"- tracking.sectors 建议: {_tracking_values(row.get('tracking', {}).get('sectors', []), 'name')}",
                f"- tracking.etfs 建议: {_tracking_values(row.get('tracking', {}).get('etfs', []), 'code')}",
                f"- tracking.indices 建议: {_tracking_values(row.get('tracking', {}).get('indices', []), 'name')}",
                f"- 缺失字段: {', '.join(row.get('missing_fields', [])) or '-'}",
                f"- 来源列表: {json.dumps(row.get('source_summary', {}), ensure_ascii=False)}",
            ]
        )
    lines.extend(["", "## 3. Firecrawl 抓取摘要", ""])
    for row in results:
        firecrawl = row.get("firecrawl", {})
        lines.append(f"- {row.get('fund_code')}: {firecrawl.get('source_status', 'skipped')} / 提取字段: {', '.join((firecrawl.get('extracted') or {}).keys()) or '-'}")
    lines.extend(["", "## 4. 人工确认清单", ""])
    for row in need_review:
        lines.append(f"- {row.get('fund_code')} {row.get('fund_name')}: 确认 role/type/tracking；持仓为季度披露，注意滞后。")
    if not need_review:
        lines.append("- 暂无")
    return "\n".join(lines) + "\n"


def _terminal_summary(results: List[Dict[str, Any]], generated_path: Path, report_path: Path, firecrawl_used: bool) -> str:
    lines = [
        "fund_enrich 摘要",
        f"处理基金数: {len(results)}",
        f"需要人工确认: {sum(1 for row in results if row.get('manual_review_required'))}",
        f"Firecrawl: {'enabled' if firecrawl_used else 'disabled'}",
        f"Enriched config: {generated_path}",
        f"报告路径: {report_path}",
    ]
    for row in results:
        lines.append(
            f"{row.get('fund_code')} {row.get('fund_name')} | type={row.get('inferred_type')} | "
            f"estimate={row.get('estimate_nav')}/{row.get('estimate_change_pct')}% | "
            f"holdings={len(row.get('top_holdings') or [])} | review={row.get('manual_review_required')}"
        )
    return "\n".join(lines)


def _enabled_funds(funds: List[Dict[str, Any]], fund_code: str | None = None) -> List[Dict[str, Any]]:
    result = []
    for fund in funds:
        code = str(fund.get("code") or "").zfill(6)
        if fund.get("enabled", True) is False:
            continue
        if fund_code and code != str(fund_code).zfill(6):
            continue
        result.append(fund)
    return result


def _source_for_name(fund: Dict[str, Any], estimate: Dict[str, Any], daily: Dict[str, Any]) -> str:
    if fund.get("name"):
        return "config"
    if daily.get("fund_name"):
        return "akshare_daily"
    if estimate.get("fund_name"):
        return "akshare_estimate"
    return "missing"


def _merge_confidence(left: str | None, right: str | None) -> str:
    order = ["low", "medium_low", "medium", "medium_high", "high"]
    scores = [order.index(item) for item in (left, right) if item in order]
    return order[min(scores)] if scores else "low"


def _notes(classifier: Dict[str, Any], tracking: Dict[str, Any], firecrawl: Dict[str, Any]) -> List[str]:
    notes = list(tracking.get("notes", []))
    if classifier.get("manual_review_required"):
        notes.append("基金类型为自动推断，建议人工确认。")
    if firecrawl.get("source_status") == "firecrawl_missing_key":
        notes.append("FIRECRAWL_API_KEY 缺失，网页补全已跳过。")
    return notes


def _matched_fields(row: Dict[str, Any]) -> List[str]:
    return [field for field in ("fund_name", "inferred_type", "estimate_nav", "estimate_change_pct", "top_holdings") if row.get(field) not in (None, "", [], {})]


def _validated_firecrawl_fields(fields: Dict[str, Any]) -> Dict[str, Any]:
    validated: Dict[str, Any] = {}
    for name in ("fund_company", "fund_manager", "invest_scope", "benchmark"):
        value = str(fields.get(name) or "").strip()
        if _is_reasonable_firecrawl_value(name, value):
            validated[name] = value
    return validated


def _is_reasonable_firecrawl_value(name: str, value: str) -> bool:
    if not value:
        return False
    limit = 30 if any("\u4e00" <= ch <= "\u9fff" for ch in value) else 80
    if len(value) > limit:
        return False
    if any(token in value for token in ("。", "，", "\n", "：", ";", "；")):
        return False
    if name == "fund_manager" and len(value) > 20:
        return False
    return True


def _holding_names(holdings: List[Dict[str, Any]]) -> str:
    return ", ".join(str(item.get("holding_stock_name") or item.get("holding_stock_code") or "") for item in holdings[:10]) or "-"


def _tracking_values(items: Any, key: str) -> str:
    if not isinstance(items, list):
        return "-"
    return ", ".join(str(item.get(key, item)) if isinstance(item, dict) else str(item) for item in items[:10]) or "-"
