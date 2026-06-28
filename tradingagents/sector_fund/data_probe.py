from __future__ import annotations

import json
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

import requests
import yaml

from .akshare_provider import AKSHARE_META, AkShareProvider
from .baostock_provider import BaostockProvider, to_baostock_code
from .data_audit import build_audit_rows, render_terminal_summary, write_audit_outputs
from .db import initialize_database, get_connection
from .domestic_web_provider import build_sector_fund_urls
from .eastmoney_quote_provider import EastMoneyQuoteProvider
from .parsers import parse_announcement_text, parse_fund_flow_text, parse_fund_holdings_text
from .repository import FundRepository


@dataclass
class ProbeRecord:
    source_name: str
    source_type: str
    category: str
    entity_type: str = ""
    entity_code: str = ""
    entity_name: str = ""
    url: str = ""
    interface_name: str = ""
    fetch_status: str = "not_started"
    status_code: str | int | None = None
    raw_text_length: int = 0
    parser_status: str = "not_started"
    matched_fields: List[str] = field(default_factory=list)
    missing_fields: List[str] = field(default_factory=list)
    error_reason: str = ""
    raw_file: str = ""
    data: Dict[str, Any] = field(default_factory=dict)
    core_fields: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_name": self.source_name,
            "source_type": self.source_type,
            "category": self.category,
            "entity_type": self.entity_type,
            "entity_code": self.entity_code,
            "entity_name": self.entity_name,
            "url": self.url,
            "interface_name": self.interface_name,
            "fetch_status": self.fetch_status,
            "status_code": self.status_code,
            "raw_text_length": self.raw_text_length,
            "parser_status": self.parser_status,
            "matched_fields": self.matched_fields,
            "missing_fields": self.missing_fields,
            "error_reason": self.error_reason,
            "raw_file": self.raw_file,
            "data": self.data,
            "core_fields": self.core_fields,
        }


def run_data_probe(
    config_path: str = "config/personal_semiconductor.yaml",
    output_dir: str | Path = "reports/sector_fund",
    raw_root: str | Path = "data/debug_raw",
    timeout: int = 10,
    db_path: str | None = None,
    baostock_only: bool = False,
    use_akshare: bool | None = None,
    no_web: bool = False,
    view: bool = False,
) -> Dict[str, Any]:
    config = load_probe_config(config_path)
    probe_date = date.today().isoformat()
    run_id = f"data_probe_{probe_date}_{uuid.uuid4().hex[:8]}"
    run_time = datetime.now().isoformat(timespec="seconds")
    raw_dir = Path(raw_root) / probe_date
    raw_dir.mkdir(parents=True, exist_ok=True)

    records: List[ProbeRecord] = []
    records.extend(_probe_baostock(config, raw_dir))
    if not baostock_only:
        records.extend(_probe_tiantian_fund(config, raw_dir, timeout=timeout))
        records.extend(_probe_eastmoney_structured(config, raw_dir, timeout=timeout))
        if _akshare_enabled(config, use_akshare):
            records.extend(_probe_akshare(config, raw_dir))
        if not no_web:
            records.extend(_probe_raw_fallbacks(config, raw_dir, timeout=timeout))
            records.extend(_probe_firecrawl(config, raw_dir, timeout=timeout))

    coverage = calculate_probe_coverage(records)
    report = _render_probe_report(config_path, records, coverage, raw_dir)
    report_path = Path(output_dir) / "data_probe_report.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")

    summary_path = raw_dir / "data_probe_records.json"
    summary_path.write_text(json.dumps([record.to_dict() for record in records], ensure_ascii=False, indent=2), encoding="utf-8")

    resolved_db_path = db_path or config.get("database", {}).get("path") or "data/fund_assistant.sqlite3"
    sql_status = _write_sql_diagnostics(resolved_db_path, run_id, probe_date, records, run_time, config_path)
    audit = write_audit_outputs(
        records,
        coverage,
        config_file=config_path,
        raw_dir=raw_dir,
        output_dir=output_dir,
        run_id=run_id,
        run_time=run_time,
    )

    result = {
        "records": [record.to_dict() for record in records],
        "coverage": coverage,
        "report": report,
        "report_path": report_path,
        "raw_dir": raw_dir,
        "summary_path": summary_path,
        "db_path": resolved_db_path,
        "sql_status": sql_status,
        "audit_csv_path": audit["audit_csv_path"],
        "audit_json_path": audit["audit_json_path"],
        "audit_summary_path": audit["summary_path"],
        "audit_rows": audit["audit_rows"],
        "cross_validation": audit["cross_validation"],
        "terminal_summary": render_terminal_summary(audit["audit_rows"], coverage, audit["cross_validation"]),
    }
    if view:
        print(result["terminal_summary"])
    return result


def load_probe_config(config_path: str | Path) -> Dict[str, Any]:
    path = Path(config_path)
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if "profile" in data:
        funds = [{"code": item.get("code", ""), "name": item.get("name", ""), "type": item.get("type", "")} for item in data.get("funds", [])]
        etfs = [{"code": item.get("code", ""), "name": item.get("name", "")} for item in data.get("etfs", [])]
        stocks = _watch_stock_rows(data)
        return {
            "profile": data.get("profile", {}),
            "database": data.get("database", {"path": "data/fund_assistant.sqlite3"}),
            "funds": [{**item, "type": item.get("type", "")} for item in funds],
            "etfs": etfs,
            "indices": data.get("indices") or ["科创50", "创业板指"],
            "sectors": data.get("sectors", []),
            "stocks": stocks,
            "raw_config": data,
            "config_schema": "sector_fund",
        }
    funds = data.get("funds", [])
    etf_codes: Dict[str, Dict[str, str]] = {}
    index_codes: set[str] = set()
    sector_names: set[str] = set()
    stocks: List[Dict[str, str]] = []
    for fund in funds:
        tracking = fund.get("tracking", {})
        for item in tracking.get("etfs", []):
            code = _tracking_code(item)
            if code:
                etf_codes.setdefault(code, {"code": code, "name": _tracking_name(item) or code})
        index_codes.update(_tracking_name(item) for item in tracking.get("indices", []) if _tracking_name(item))
        sector_names.update(_tracking_name(item) for item in tracking.get("sectors", []) if _tracking_name(item))
        for stock in list(tracking.get("manual_holdings", [])) + list(tracking.get("stocks", [])):
            if isinstance(stock, dict) and stock.get("code"):
                stocks.append({"code": str(stock.get("code")), "name": str(stock.get("name", stock.get("code"))), "theme": str(fund.get("name", ""))})
    return {
        "profile": data.get("portfolio", {}),
        "database": data.get("database", {"path": "data/fund_assistant.sqlite3"}),
        "funds": [{"code": item.get("code", ""), "name": item.get("name", ""), "type": item.get("type", "")} for item in funds],
        "etfs": list(etf_codes.values()),
        "indices": sorted(index_codes) or ["科创50", "创业板指"],
        "sectors": sorted(sector_names),
        "stocks": stocks,
        "raw_config": data,
        "config_schema": "fund_portfolio",
    }


def _tracking_code(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get("code") or item.get("symbol") or "").zfill(6) if item.get("code") or item.get("symbol") else ""
    text = str(item or "")
    digits = "".join(ch for ch in text if ch.isdigit())
    return digits.zfill(6) if digits else text


def _tracking_name(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get("name") or item.get("code") or item.get("symbol") or "")
    return str(item or "")


def _probe_tiantian_fund(config: Dict[str, Any], raw_dir: Path, timeout: int) -> List[ProbeRecord]:
    records: List[ProbeRecord] = []
    for fund in config.get("funds", []):
        code = str(fund.get("code") or "")
        name = str(fund.get("name") or code)
        if not code:
            continue
        estimate_fields = [
            f"fund.{code}.estimate_nav",
            f"fund.{code}.estimate_change_pct",
            f"fund.{code}.estimate_time",
            f"fund.{code}.previous_unit_nav",
            f"fund.{code}.unit_nav",
            f"fund.{code}.daily_change_pct",
            f"fund.{code}.source_status",
        ]
        estimate_url = f"https://fundgz.1234567.com.cn/js/{code}.js?rt={int(time.time() * 1000)}"
        records.append(
            _http_record(
                source_name=f"tiantian_fund_estimate_{code}",
                source_type="tiantian_fund_estimate",
                category="天天基金基金估算",
                entity_type="fund",
                entity_code=code,
                entity_name=name,
                url=estimate_url,
                raw_dir=raw_dir,
                timeout=timeout,
                parser=lambda text, fund_code=code, fund_name=name: parse_fund_estimate_text(fund_code, fund_name, text),
                expected_fields=estimate_fields,
                core_fields=[field for field in estimate_fields if not field.endswith(".daily_change_pct")],
            )
        )
        holding_fields = [f"fund.{code}.top_holdings", f"fund.{code}.top_holdings_weight_pct"]
        records.append(
            _http_record(
                source_name=f"tiantian_fund_holdings_{code}",
                source_type="tiantian_fund_holdings",
                category="天天基金基金估算",
                entity_type="fund",
                entity_code=code,
                entity_name=name,
                url=f"https://fundf10.eastmoney.com/ccmx_{code}.html",
                raw_dir=raw_dir,
                timeout=timeout,
                parser=parse_fund_holdings_text,
                expected_fields=holding_fields,
                core_fields=[f"fund.{code}.top_holdings"],
            )
        )
    return records


def parse_fund_estimate_text(fund_code: str, fund_name: str, text: str) -> Dict[str, Any]:
    match = re.search(r"\{.*\}", text or "")
    if not match:
        return {}
    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}
    previous_unit_nav = _num(payload.get("dwjz"))
    estimate_change_pct = _num(payload.get("gszzl"))
    return {
        f"fund.{fund_code}.fund_code": fund_code,
        f"fund.{fund_code}.fund_name": fund_name or payload.get("name"),
        f"fund.{fund_code}.estimate_nav": _num(payload.get("gsz")),
        f"fund.{fund_code}.estimate_change_pct": estimate_change_pct,
        f"fund.{fund_code}.estimate_time": payload.get("gztime"),
        f"fund.{fund_code}.previous_unit_nav": previous_unit_nav,
        f"fund.{fund_code}.unit_nav": previous_unit_nav,
        f"fund.{fund_code}.daily_change_pct": _num(payload.get("jzzzl")),
        f"fund.{fund_code}.source": "tiantian_fund_estimate",
        f"fund.{fund_code}.source_status": "success" if payload else "",
    }


def _probe_baostock(config: Dict[str, Any], raw_dir: Path) -> List[ProbeRecord]:
    provider = BaostockProvider()
    records: List[ProbeRecord] = []
    targets: List[tuple[str, str, str, str]] = []
    targets.extend(("ETF", item.get("code", ""), item.get("name", ""), "etf") for item in config.get("etfs", []))
    targets.extend(("股票", item.get("code", ""), item.get("name", ""), "stock") for item in config.get("stocks", [])[:8])
    targets.extend(("指数", str(item), str(item), "index") for item in config.get("indices", []))
    try:
        provider.login()
        for label, code, name, entity_type in targets:
            if not code:
                continue
            snapshot = provider.fetch_latest_daily_snapshot(code)
            payload = json.dumps(snapshot, ensure_ascii=False, indent=2)
            raw_file = _write_raw(raw_dir, f"baostock_{entity_type}_{code}", payload)
            expected = [
                f"baostock.{entity_type}.{code}.kline",
                f"baostock.{entity_type}.{code}.latest_trade_date",
                f"baostock.{entity_type}.{code}.latest_close",
                f"baostock.{entity_type}.{code}.pct_chg",
                f"baostock.{entity_type}.{code}.ma5",
                f"baostock.{entity_type}.{code}.ma10",
                f"baostock.{entity_type}.{code}.ma20",
                f"baostock.{entity_type}.{code}.source_status",
            ]
            data = {
                f"baostock.{entity_type}.{code}.kline": snapshot.get("rows_count") if snapshot.get("rows") else None,
                f"baostock.{entity_type}.{code}.latest_trade_date": snapshot.get("latest_trade_date"),
                f"baostock.{entity_type}.{code}.latest_close": snapshot.get("latest_close"),
                f"baostock.{entity_type}.{code}.pct_chg": snapshot.get("pct_chg"),
                f"baostock.{entity_type}.{code}.ma5": snapshot.get("ma5"),
                f"baostock.{entity_type}.{code}.ma10": snapshot.get("ma10"),
                f"baostock.{entity_type}.{code}.ma20": snapshot.get("ma20"),
                f"baostock.{entity_type}.{code}.source_status": snapshot.get("source_status"),
            }
            records.append(
                ProbeRecord(
                    source_name=f"baostock_{entity_type}_{code}",
                    source_type="baostock_daily_k",
                    category="Baostock 日K",
                    entity_type=entity_type,
                    entity_code=code,
                    entity_name=name or code,
                    interface_name=f"baostock.query_history_k_data_plus({snapshot.get('baostock_code') or to_baostock_code(code)})",
                    fetch_status="success" if snapshot.get("rows") else "dependency_missing" if snapshot.get("source_status") == "dependency_missing" else "missing",
                    status_code=snapshot.get("source_status"),
                    raw_text_length=len(payload),
                    parser_status="success" if snapshot.get("rows") else "no_data",
                    matched_fields=_matched(data, expected),
                    missing_fields=_missing(data, expected),
                    error_reason=snapshot.get("error_reason") or ("" if snapshot.get("rows") else "baostock returned no rows"),
                    raw_file=raw_file,
                    data={
                        "rows": snapshot.get("rows_count", 0),
                        "latest_trade_date": snapshot.get("latest_trade_date"),
                        "latest_close": snapshot.get("latest_close"),
                        "pct_chg": snapshot.get("pct_chg"),
                        "ma5": snapshot.get("ma5"),
                        "ma10": snapshot.get("ma10"),
                        "ma20": snapshot.get("ma20"),
                        "source_status": snapshot.get("source_status"),
                        "label": label,
                        "baostock_code": snapshot.get("baostock_code"),
                        "candidate_codes": snapshot.get("candidate_codes", []),
                        "support_probe": snapshot.get("support_probe", {}),
                    },
                    core_fields=[field for field in expected if not field.endswith(".ma10") and not field.endswith(".ma20")],
                )
            )
    finally:
        provider.logout()
    total_symbols = len([target for target in targets if target[1]])
    success_symbols = sum(1 for record in records if record.fetch_status == "success")
    failed_symbols = total_symbols - success_symbols
    for record in records:
        record.data.update(
            {
                "baostock_login_status": provider.login_status,
                "baostock_logout_status": provider.logout_status,
                "total_symbols": total_symbols,
                "success_symbols": success_symbols,
                "failed_symbols": failed_symbols,
                "login_count": provider.login_count,
                "logout_count": provider.logout_count,
            }
        )
    return records


def _probe_eastmoney_structured(config: Dict[str, Any], raw_dir: Path, timeout: int) -> List[ProbeRecord]:
    provider = EastMoneyQuoteProvider(timeout=timeout)
    records: List[ProbeRecord] = []
    quote_targets: List[tuple[str, str, str]] = []
    quote_targets.extend((item.get("code", ""), item.get("name", ""), "etf") for item in config.get("etfs", []))
    quote_targets.extend((str(item), str(item), "index") for item in config.get("indices", []))
    quote_targets.extend((item.get("code", ""), item.get("name", ""), "stock") for item in config.get("stocks", [])[:8])
    quotes = provider.fetch_quotes([code for code, _, _ in quote_targets])
    _write_raw(raw_dir, "eastmoney_structured_quotes", json.dumps(quotes, ensure_ascii=False, indent=2))
    for code, name, entity_type in quote_targets:
        if not code:
            continue
        quote = quotes.get(_normalize_quote_key(code), {})
        expected = [
            f"eastmoney.{entity_type}.{code}.latest_price",
            f"eastmoney.{entity_type}.{code}.change_pct",
            f"eastmoney.{entity_type}.{code}.amount",
            f"eastmoney.{entity_type}.{code}.source_status",
        ]
        if entity_type != "index":
            expected.extend(
                [
                    f"eastmoney.{entity_type}.{code}.open",
                    f"eastmoney.{entity_type}.{code}.high",
                    f"eastmoney.{entity_type}.{code}.low",
                    f"eastmoney.{entity_type}.{code}.preclose",
                    f"eastmoney.{entity_type}.{code}.turnover_rate",
                ]
            )
        data = {field: quote.get(field.split(".")[-1]) for field in expected}
        records.append(
            ProbeRecord(
                source_name=f"eastmoney_quote_{entity_type}_{code}",
                source_type="eastmoney_push2_quote",
                category="东方财富盘中行情",
                entity_type=entity_type,
                entity_code=code,
                entity_name=name or quote.get("name", code),
                interface_name="eastmoney.push2.ulist",
                fetch_status="success" if quote else "failed",
                status_code="success" if quote else "empty",
                raw_text_length=len(json.dumps(quote, ensure_ascii=False)),
                parser_status="success" if _matched(data, expected) else "no_match",
                matched_fields=_matched(data, expected),
                missing_fields=_missing(data, expected),
                error_reason="" if quote else provider.last_error or "eastmoney structured quote missing",
                data=quote,
                core_fields=[field for field in expected if any(field.endswith(suffix) for suffix in (".latest_price", ".change_pct", ".source_status"))],
            )
        )
    sectors = provider.fetch_sector_changes(config.get("sectors", []))
    _write_raw(raw_dir, "eastmoney_structured_sectors", json.dumps(sectors, ensure_ascii=False, indent=2))
    for sector in config.get("sectors", []):
        item = sectors.get(sector, {})
        expected = [f"eastmoney.sector.{sector}.change_pct", f"eastmoney.sector.{sector}.source_status"]
        data = {
            f"eastmoney.sector.{sector}.change_pct": item.get("change_pct"),
            f"eastmoney.sector.{sector}.source_status": item.get("source_status"),
        }
        records.append(
            ProbeRecord(
                source_name=f"eastmoney_sector_{sector}",
                source_type="eastmoney_push2_sector",
                category="东方财富盘中行情",
                entity_type="sector",
                entity_code=sector,
                entity_name=sector,
                interface_name="eastmoney.push2.clist",
                fetch_status="success" if item else "failed",
                status_code="success" if item else "empty",
                raw_text_length=len(json.dumps(item, ensure_ascii=False)),
                parser_status="success" if _matched(data, expected) else "no_match",
                matched_fields=_matched(data, expected),
                missing_fields=_missing(data, expected),
                error_reason="" if item else provider.last_error or "eastmoney sector not matched",
                data=item,
                core_fields=expected,
            )
        )
    return records


def _probe_akshare(config: Dict[str, Any], raw_dir: Path) -> List[ProbeRecord]:
    provider = AkShareProvider()
    records: List[ProbeRecord] = []
    funds = config.get("funds", [])
    fund_codes = [str(item.get("code") or "").zfill(6) for item in funds if item.get("code")]
    fund_names = {str(item.get("code") or "").zfill(6): str(item.get("name") or item.get("code") or "") for item in funds}
    fund_types = {str(item.get("code") or "").zfill(6): str(item.get("type") or "") for item in funds}

    availability = provider.check_available()
    records.append(_akshare_availability_record(availability, raw_dir))
    if availability.get("source_status") == "dependency_missing":
        return records

    estimates = provider.fetch_fund_estimates(fund_codes, fund_types=fund_types)
    estimates_raw = _write_raw(raw_dir, "akshare_fund_estimates", json.dumps(estimates, ensure_ascii=False, indent=2))
    for code in fund_codes:
        item = estimates.get(code, {})
        expected = [
            f"akshare.fund.{code}.estimate_date",
            f"akshare.fund.{code}.estimate_time",
            f"akshare.fund.{code}.estimate_nav",
            f"akshare.fund.{code}.estimate_change_pct",
            f"akshare.fund.{code}.published_nav",
            f"akshare.fund.{code}.previous_unit_nav",
            f"akshare.fund.{code}.published_change_pct",
            f"akshare.fund.{code}.estimate_bias_pct",
            f"akshare.fund.{code}.is_stale",
            f"akshare.fund.{code}.estimate_reliability",
            f"akshare.fund.{code}.estimate_warning",
            f"akshare.fund.{code}.source_status",
        ]
        data = {field: item.get(field.split(".")[-1]) for field in expected}
        data.update(item)
        records.append(_structured_record("akshare_fund_estimate", "AKShare 基金估算", "fund", code, fund_names.get(code, code), expected, data, core_fields=[
            f"akshare.fund.{code}.estimate_nav",
            f"akshare.fund.{code}.estimate_change_pct",
            f"akshare.fund.{code}.estimate_time",
            f"akshare.fund.{code}.source_status",
        ], raw_file=estimates_raw))

    daily = provider.fetch_fund_daily_snapshot(fund_codes)
    daily_raw = _write_raw(raw_dir, "akshare_fund_daily_snapshot", json.dumps(daily, ensure_ascii=False, indent=2))
    for code in fund_codes:
        item = daily.get(code, {})
        expected = [
            f"akshare.fund.{code}.unit_nav",
            f"akshare.fund.{code}.daily_change_pct",
            f"akshare.fund.{code}.purchase_status",
            f"akshare.fund.{code}.redeem_status",
            f"akshare.fund.{code}.source_status",
        ]
        data = {field: item.get(field.split(".")[-1]) for field in expected}
        data.update(item)
        records.append(_structured_record("akshare_fund_daily", "AKShare 基金净值", "fund", code, fund_names.get(code, code), expected, data, core_fields=[
            f"akshare.fund.{code}.unit_nav",
            f"akshare.fund.{code}.daily_change_pct",
            f"akshare.fund.{code}.source_status",
        ], raw_file=daily_raw))

    nav_history = provider.fetch_fund_nav_history(fund_codes, tail=20)
    nav_history_raw = _write_raw(raw_dir, "akshare_fund_nav_history", json.dumps(nav_history, ensure_ascii=False, indent=2))
    for code in fund_codes:
        rows = nav_history.get(code, [])
        data = {**AKSHARE_META, "source_status": "success" if rows else "failed", "history_rows": len(rows), "nav_history": rows}
        expected = [f"akshare.fund.{code}.nav_history", f"akshare.fund.{code}.source_status"]
        data[f"akshare.fund.{code}.nav_history"] = rows
        data[f"akshare.fund.{code}.source_status"] = data["source_status"]
        records.append(_structured_record("akshare_fund_nav_history", "AKShare 基金历史净值", "fund", code, fund_names.get(code, code), expected, data, core_fields=[], raw_file=nav_history_raw))

    holdings = provider.fetch_fund_holdings(fund_codes)
    holdings_raw = _write_raw(raw_dir, "akshare_fund_holdings", json.dumps(holdings, ensure_ascii=False, indent=2))
    for code in fund_codes:
        item = holdings.get(code, {})
        expected = [f"akshare.fund.{code}.top_holdings", f"akshare.fund.{code}.source_status"]
        data = {
            f"akshare.fund.{code}.top_holdings": item.get("top_holdings"),
            f"akshare.fund.{code}.source_status": item.get("source_status"),
        }
        data.update(item)
        records.append(_structured_record("akshare_fund_holdings", "AKShare 基金持仓", "fund", code, fund_names.get(code, code), expected, data, core_fields=[f"akshare.fund.{code}.top_holdings"], raw_file=holdings_raw))

    etf_codes = [str(item.get("code") or "").zfill(6) for item in config.get("etfs", []) if item.get("code")]
    stock_codes = [str(item.get("code") or "").zfill(6) for item in config.get("stocks", [])[:8] if item.get("code")]
    for source_name, category, entity_type, quotes, codes in (
        ("akshare_etf_spot", "AKShare ETF行情", "etf", provider.fetch_etf_spot(etf_codes), etf_codes),
        ("akshare_stock_spot", "AKShare 股票行情", "stock", provider.fetch_stock_spot(stock_codes), stock_codes),
    ):
        quote_raw = _write_raw(raw_dir, source_name, json.dumps(quotes, ensure_ascii=False, indent=2))
        for code in codes:
            item = quotes.get(code, {})
            expected = [
                f"akshare.{entity_type}.{code}.latest_price",
                f"akshare.{entity_type}.{code}.change_pct",
                f"akshare.{entity_type}.{code}.source_status",
            ]
            data = {field: item.get(field.split(".")[-1]) for field in expected}
            data.update(item)
            records.append(_structured_record(source_name, category, entity_type, code, item.get("name", code), expected, data, core_fields=[], raw_file=quote_raw))

    sectors = provider.fetch_concept_boards(config.get("sectors", []))
    sector_raw = _write_raw(raw_dir, "akshare_concept_boards", json.dumps(sectors, ensure_ascii=False, indent=2))
    for sector in config.get("sectors", []):
        item = sectors.get(str(sector), {})
        expected = [f"akshare.sector.{sector}.change_pct", f"akshare.sector.{sector}.source_status"]
        data = {field: item.get(field.split(".")[-1]) for field in expected}
        data.update(item)
        records.append(_structured_record("akshare_concept_board", "AKShare 板块概念", "sector", str(sector), str(sector), expected, data, core_fields=[], raw_file=sector_raw))

    return records


def _probe_raw_fallbacks(config: Dict[str, Any], raw_dir: Path, timeout: int) -> List[ProbeRecord]:
    urls = build_sector_fund_urls(config.get("raw_config", config))
    watch_stocks = {item.get("code", ""): item.get("name", "") for item in config.get("stocks", []) if item.get("code")}
    raw_specs = [
        ("eastmoney_sector_fund_flow_raw", "网页 raw 兜底", urls.get("eastmoney_sector_fund_flow", "https://data.eastmoney.com/bkzj/"), parse_fund_flow_text, ["raw.eastmoney.sector_flow"]),
        ("ths_industry_flow_raw", "网页 raw 兜底", "https://data.10jqka.com.cn/funds/hyzjl/", parse_fund_flow_text, ["raw.ths.sector_flow"]),
        (
            "cninfo_announcements_raw",
            "网页 raw 兜底",
            "https://www.cninfo.com.cn/new/hisAnnouncement/query",
            lambda text: {"announcements": parse_announcement_text(text, watch_stocks=watch_stocks)},
            ["raw.cninfo.announcement"],
        ),
    ]
    records: List[ProbeRecord] = []
    for source_name, category, url, parser, expected in raw_specs:
        records.append(
            _http_record(
                source_name=source_name,
                source_type="raw_text_fallback",
                category=category,
                entity_type="raw",
                url=url,
                raw_dir=raw_dir,
                timeout=timeout,
                parser=parser,
                expected_fields=expected,
                core_fields=[],
            )
        )
    return records


def _probe_firecrawl(config: Dict[str, Any], raw_dir: Path, timeout: int) -> List[ProbeRecord]:
    api_key = os.getenv("FIRECRAWL_API_KEY")
    targets = {"firecrawl_eastmoney_sector": "https://data.eastmoney.com/bkzj/", "firecrawl_cninfo": "https://www.cninfo.com.cn/"}
    records: List[ProbeRecord] = []
    for source_name, target_url in targets.items():
        record = ProbeRecord(
            source_name=source_name,
            source_type="firecrawl_raw",
            category="网页 raw 兜底",
            entity_type="raw",
            url=target_url,
            interface_name="firecrawl.v1.scrape",
            missing_fields=["raw.firecrawl.text"],
        )
        if not api_key:
            record.fetch_status = "skipped"
            record.parser_status = "skipped"
            record.error_reason = "FIRECRAWL_API_KEY is not configured"
            records.append(record)
            continue
        try:
            response = requests.post(
                os.getenv("FIRECRAWL_API_URL", "https://api.firecrawl.dev").rstrip("/") + "/v1/scrape",
                timeout=timeout,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"url": target_url, "formats": ["markdown"]},
            )
            record.status_code = response.status_code
            payload = response.json() if response.ok else {}
            data = payload.get("data", payload)
            text = data.get("markdown") or data.get("content") or response.text
            record.fetch_status = "success" if response.ok and text else "failed"
            record.raw_text_length = len(text or "")
            record.raw_file = _write_raw(raw_dir, source_name, text or "")
            record.matched_fields = ["raw.firecrawl.text"] if response.ok and text else []
            record.missing_fields = [] if record.matched_fields else ["raw.firecrawl.text"]
            record.parser_status = "success" if record.matched_fields else "no_match"
            record.error_reason = "" if record.matched_fields else (response.text[:300] or "firecrawl empty")
        except Exception as exc:
            record.fetch_status = "failed"
            record.parser_status = "failed"
            record.error_reason = str(exc)
        records.append(record)
    return records


def _http_record(
    source_name: str,
    source_type: str,
    category: str,
    entity_type: str,
    url: str,
    raw_dir: Path,
    timeout: int,
    parser: Callable[[str], Dict[str, Any] | List[Dict[str, Any]]],
    expected_fields: List[str],
    core_fields: List[str],
    entity_code: str = "",
    entity_name: str = "",
) -> ProbeRecord:
    record = ProbeRecord(
        source_name=source_name,
        source_type=source_type,
        category=category,
        entity_type=entity_type,
        entity_code=entity_code,
        entity_name=entity_name,
        url=url,
        missing_fields=list(expected_fields),
        core_fields=list(core_fields),
    )
    try:
        response = requests.get(url, timeout=timeout, headers=_headers())
        record.status_code = response.status_code
        record.fetch_status = "success" if response.ok else "failed"
        response.encoding = response.apparent_encoding or response.encoding
        text = response.text or ""
        record.raw_text_length = len(text)
        record.raw_file = _write_raw(raw_dir, source_name, text)
        if not response.ok:
            record.parser_status = "skipped"
            record.error_reason = text[:300] or response.reason
            return record
        parsed = parser(text)
        record.data = parsed if isinstance(parsed, dict) else {"items": parsed}
        record.matched_fields = _matched(record.data, expected_fields)
        record.missing_fields = _missing(record.data, expected_fields)
        record.parser_status = "success" if record.matched_fields else "no_match"
        if not record.matched_fields:
            record.error_reason = "fetch succeeded but parser matched no expected fields"
    except Exception as exc:
        record.fetch_status = "failed"
        record.parser_status = "failed"
        record.error_reason = str(exc)
    return record


def _structured_record(
    source_type: str,
    category: str,
    entity_type: str,
    entity_code: str,
    entity_name: str,
    expected_fields: List[str],
    data: Dict[str, Any],
    core_fields: List[str],
    raw_file: str = "",
) -> ProbeRecord:
    matched = _matched(data, expected_fields)
    source_status = str(data.get("source_status") or "")
    fetch_status = "success" if matched and source_status == "success" else "dependency_missing" if source_status == "dependency_missing" else "failed"
    return ProbeRecord(
        source_name=f"{source_type}_{entity_code}",
        source_type=source_type,
        category=category,
        entity_type=entity_type,
        entity_code=entity_code,
        entity_name=entity_name or entity_code,
        interface_name=source_type,
        fetch_status=fetch_status,
        status_code=source_status,
        raw_text_length=len(json.dumps(data, ensure_ascii=False)),
        parser_status="success" if matched else "no_match",
        matched_fields=matched,
        missing_fields=_missing(data, expected_fields),
        error_reason="" if matched else data.get("error_reason", "structured field missing"),
        raw_file=raw_file,
        data=data,
        core_fields=core_fields,
    )


def _akshare_availability_record(availability: Dict[str, Any], raw_dir: Path) -> ProbeRecord:
    expected = ["akshare.available"]
    data = {"akshare.available": availability.get("source_status") == "success", **availability}
    raw_file = _write_raw(raw_dir, "akshare_availability", json.dumps(data, ensure_ascii=False, indent=2))
    return ProbeRecord(
        source_name="akshare_availability",
        source_type="akshare_availability",
        category="AKShare 可用性",
        entity_type="source",
        entity_code="akshare",
        entity_name="akshare",
        interface_name="import akshare",
        fetch_status="success" if availability.get("source_status") == "success" else "dependency_missing",
        status_code=availability.get("source_status"),
        raw_text_length=len(json.dumps(data, ensure_ascii=False)),
        parser_status="success" if availability.get("source_status") == "success" else "failed",
        matched_fields=_matched(data, expected),
        missing_fields=_missing(data, expected),
        error_reason=availability.get("error_reason", ""),
        raw_file=raw_file,
        data=data,
        core_fields=[],
    )


def _akshare_enabled(config: Dict[str, Any], cli_value: bool | None) -> bool:
    if cli_value is not None:
        return cli_value
    data_sources = config.get("raw_config", config).get("data_sources", {})
    return bool(data_sources.get("akshare", {}).get("enabled", True))


def calculate_probe_coverage(records: List[ProbeRecord]) -> Dict[str, Any]:
    all_expected = {field for record in records for field in record.matched_fields + record.missing_fields}
    all_matched = {field for record in records for field in record.matched_fields}
    core_groups: Dict[str, set[str]] = {}
    for record in records:
        for field in record.core_fields:
            core_groups.setdefault(_semantic_core_key(record, field), set()).add(field)
    core_matched_keys = {
        key
        for key, fields in core_groups.items()
        if any(field in all_matched for field in fields)
    }
    core_expected = {field for fields in core_groups.values() for field in fields}
    core_matched = {field for fields in core_groups.values() for field in fields if field in all_matched}
    core_missing = {field for key, fields in core_groups.items() if key not in core_matched_keys for field in fields}
    return {
        "core_matched_count": len(core_matched_keys),
        "core_total_count": len(core_groups),
        "core_coverage_rate": _rate(len(core_matched_keys), len(core_groups)),
        "all_matched_count": len(all_matched),
        "all_total_count": len(all_expected),
        "all_coverage_rate": _rate(len(all_matched), len(all_expected)),
        "matched_fields": sorted(all_matched),
        "missing_fields": sorted(all_expected - all_matched),
        "core_matched_fields": sorted(core_matched),
        "core_missing_fields": sorted(core_missing),
    }


def _write_sql_diagnostics(
    db_path: str | Path,
    run_id: str,
    trade_date: str,
    records: List[ProbeRecord],
    run_time: str | None = None,
    config_file: str = "",
) -> Dict[str, Any]:
    try:
        initialize_database(db_path)
        with get_connection(db_path) as conn:
            repo = FundRepository(conn)
            repo.record_data_source_runs(
                {
                    "run_id": run_id,
                    "trade_date": trade_date,
                    "decision_time": "data_probe",
                    "source_name": record.source_name,
                    "source_type": record.source_type,
                    "url": record.url or record.interface_name,
                    "fetch_status": record.fetch_status,
                    "status_code": _status_code(record.status_code),
                    "raw_text_length": record.raw_text_length,
                    "matched_fields_count": len(record.matched_fields),
                    "missing_fields_count": len(record.missing_fields),
                    "error_reason": record.error_reason,
                    "raw_text_path": record.raw_file,
                }
                for record in records
            )
            audit_rows = build_audit_rows(records, run_id=run_id, run_time=run_time or datetime.now().isoformat(timespec="seconds"), config_file=config_file)
            conn.execute("DELETE FROM field_source WHERE run_id=?", (run_id,))
            conn.executemany(
                """
                INSERT INTO field_source(
                    run_id, snapshot_id, entity_type, entity_code, entity_name,
                    field_name, semantic_field, source, upstream_source, upstream_group,
                    source_level, independent, source_status, value_text, value_numeric,
                    trade_date, data_time, parser_status, confidence, error_reason,
                    fix_suggestion, final_source, raw_text_path, audit_status,
                    audit_reason, config_file, run_time
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        row.get("run_id"),
                        0,
                        row.get("entity_type"),
                        row.get("entity_code"),
                        row.get("entity_name"),
                        row.get("field_name"),
                        row.get("semantic_field"),
                        row.get("source"),
                        row.get("upstream_source"),
                        row.get("upstream_group"),
                        row.get("source_level"),
                        1 if row.get("independent") in (True, "true", "True", 1, "1") else 0,
                        row.get("source_status"),
                        str(row.get("value", ""))[:1000],
                        row.get("value_numeric"),
                        row.get("trade_date") or trade_date,
                        "",
                        row.get("parser_status"),
                        1.0 if row.get("audit_status") == "ok" else 0.0,
                        row.get("audit_reason"),
                        row.get("fix_suggestion"),
                        row.get("final_source"),
                        row.get("raw_text_path"),
                        row.get("audit_status"),
                        row.get("audit_reason"),
                        row.get("config_file"),
                        row.get("run_time"),
                    )
                    for row in audit_rows
                ],
            )
            conn.commit()
        return {"status": "success", "db_path": str(db_path), "run_id": run_id}
    except Exception as exc:
        return {"status": "failed", "db_path": str(db_path), "run_id": run_id, "error_reason": str(exc)}


def _render_probe_report(config_path: str, records: List[ProbeRecord], coverage: Dict[str, Any], raw_dir: Path) -> str:
    lines = [
        "# data_probe 数据抓取诊断报告",
        "",
        f"- 配置文件: `{config_path}`",
        f"- Debug raw: `{raw_dir}`",
        f"- Core coverage: {coverage['core_coverage_rate']}% ({coverage['core_matched_count']}/{coverage['core_total_count']})",
        f"- All coverage: {coverage['all_coverage_rate']}% ({coverage['all_matched_count']}/{coverage['all_total_count']})",
        "- 说明: mock fallback 不参与真实成功字段统计；raw_text 只作为失败诊断、parser 调试和兜底。",
        "- 约束: 未调用 TradingAgentsGraph，未调用 LLM，未生成正式投资报告或买卖建议。",
        "",
        "## Core 已打通字段",
        "",
    ]
    lines.extend(f"- `{field}`" for field in coverage["core_matched_fields"]) if coverage["core_matched_fields"] else lines.append("- 暂无")
    lines.extend(["", "## Core 仍失败字段", ""])
    lines.extend(f"- `{field}`" for field in coverage["core_missing_fields"]) if coverage["core_missing_fields"] else lines.append("- 暂无")
    for category in ("天天基金基金估算", "Baostock 日K", "东方财富盘中行情", "网页 raw 兜底"):
        group = [record for record in records if record.category == category]
        if not group:
            continue
        lines.extend(["", f"## {category}", ""])
        lines.append(
            "| source_name | entity | fetch_status | status_code | raw_text_length | parser_status | matched_fields | missing_fields | key_data | error_reason | raw_text_path |"
        )
        lines.append("| --- | --- | --- | --- | ---: | --- | --- | --- | --- | --- | --- |")
        for record in group:
            key_data = _key_data(record)
            lines.append(
                "| "
                + " | ".join(
                    [
                        _md(record.source_name),
                        _md(record.entity_name or record.entity_code or record.entity_type),
                        _md(record.fetch_status),
                        _md(str(record.status_code or "")),
                        str(record.raw_text_length),
                        _md(record.parser_status),
                        _md(", ".join(record.matched_fields) or "-"),
                        _md(", ".join(record.missing_fields) or "-"),
                        _md(key_data),
                        _md(record.error_reason or "-"),
                        _md(record.raw_file or "-"),
                    ]
                )
                + " |"
            )
    return "\n".join(lines) + "\n"


def _watch_stock_rows(config: Dict[str, Any]) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    for theme, stocks in config.get("watch_stocks", {}).items():
        for stock in stocks:
            rows.append({"code": str(stock.get("code", "")), "name": str(stock.get("name", "")), "theme": str(theme)})
    return rows


def _matched(data: Dict[str, Any], expected_fields: List[str]) -> List[str]:
    fields: List[str] = []
    for field in expected_fields:
        value = data.get(field, data.get(field.split(".")[-1]))
        if field.endswith(".source_status") and value not in ("success", "ok"):
            continue
        if value not in (None, "", [], {}):
            fields.append(field)
    return fields


def _missing(data: Dict[str, Any], expected_fields: List[str]) -> List[str]:
    matched = set(_matched(data, expected_fields))
    return [field for field in expected_fields if field not in matched]


def _normalize_quote_key(code: str) -> str:
    raw = str(code)
    if raw in {"科创50", "创业板指", "上证指数", "上证综指", "深成指", "深证成指"}:
        return {"科创50": "000688", "创业板指": "399006", "上证指数": "000001", "上证综指": "000001", "深成指": "399001", "深证成指": "399001"}[raw]
    return "".join(ch for ch in raw if ch.isdigit()).zfill(6)


def _semantic_core_key(record: ProbeRecord, field: str) -> str:
    leaf = field.split(".")[-1]
    entity_type = record.entity_type
    entity_code = record.entity_code
    semantic = {
        "latest_close": "price",
        "latest_price": "price",
        "pct_chg": "change_pct",
        "change_pct": "change_pct",
    }.get(leaf, leaf)
    return f"{entity_type}:{entity_code}:{semantic}"


def _write_raw(raw_dir: Path, source_name: str, text: str) -> str:
    suffix = "json" if (text or "").lstrip().startswith(("{", "[")) else "txt"
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", source_name)
    path = raw_dir / f"{safe_name}.{suffix}"
    path.write_text(text or "", encoding="utf-8")
    return str(path)


def _headers() -> Dict[str, str]:
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }


def _num(value: Any) -> Optional[float]:
    if value in (None, "", "-", "--"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _rate(count: int, total: int) -> float:
    return round(count / total * 100, 2) if total else 0.0


def _status_code(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _md(value: str) -> str:
    return (value or "").replace("|", "\\|").replace("\n", " ")[:500]


def _key_data(record: ProbeRecord) -> str:
    if record.category == "Baostock 日K":
        return f"rows={record.data.get('rows')}, latest_trade_date={record.data.get('latest_trade_date')}, latest_close={record.data.get('latest_close')}, pct_chg={record.data.get('pct_chg')}, ma5={record.data.get('ma5')}, ma10={record.data.get('ma10')}, ma20={record.data.get('ma20')}"
    if record.category == "东方财富盘中行情":
        return f"latest_price={record.data.get('latest_price')}, change_pct={record.data.get('change_pct')}, amount={record.data.get('amount')}, source_status={record.data.get('source_status')}"
    if record.category == "天天基金基金估算":
        code = record.entity_code
        return f"estimate_nav={record.data.get(f'fund.{code}.estimate_nav')}, estimate_change_pct={record.data.get(f'fund.{code}.estimate_change_pct')}, estimate_time={record.data.get(f'fund.{code}.estimate_time')}"
    return f"raw_text_length={record.raw_text_length}, parser_status={record.parser_status}"
