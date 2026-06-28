from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List

from .baostock_provider import BaostockProvider, calculate_indicators, to_baostock_code
from .db import get_connection, initialize_database
from .fund_config_loader import load_fund_portfolio_config, resolve_db_path
from .models import DECISION_TIMES
from .repository import FundRepository


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _security_type(code: str) -> str:
    raw = code.lower().replace("sh.", "").replace("sz.", "")
    if raw.startswith(("5", "15", "16")):
        return "etf"
    if code in {"科创50", "创业板指", "沪深300", "上证指数", "深成指"}:
        return "index"
    return "stock"


def _collect_tracking_codes(config: Dict[str, Any]) -> Dict[str, List[str]]:
    etfs: set[str] = set()
    indices: set[str] = set()
    stocks: set[str] = set()
    sectors: set[str] = set()
    for fund in config.get("funds", []):
        tracking = fund.get("tracking", {})
        etfs.update(tracking.get("etfs", []))
        indices.update(tracking.get("indices", []))
        sectors.update(tracking.get("sectors", []))
        for row in tracking.get("manual_holdings", []):
            if isinstance(row, dict) and row.get("code"):
                stocks.add(row["code"])
    return {
        "etfs": sorted(etfs),
        "indices": sorted(indices),
        "stocks": sorted(stocks),
        "sectors": sorted(sectors),
    }


def _coverage(collected: Dict[str, Any]) -> Dict[str, Any]:
    core_fields = [
        collected.get("funds"),
        collected.get("tracking", {}).get("etfs"),
        collected.get("tracking", {}).get("indices"),
        collected.get("kline"),
        collected.get("indicators"),
    ]
    total = len(core_fields)
    real = sum(1 for item in core_fields if item)
    core_rate = round(real / total * 100, 2) if total else 0.0
    all_items = [
        collected.get("funds"),
        collected.get("tracking", {}).get("etfs"),
        collected.get("tracking", {}).get("indices"),
        collected.get("tracking", {}).get("stocks"),
        collected.get("tracking", {}).get("sectors"),
        collected.get("kline"),
        collected.get("indicators"),
    ]
    all_total = len(all_items)
    all_real = sum(1 for item in all_items if item)
    all_rate = round(all_real / all_total * 100, 2) if all_total else 0.0
    if core_rate >= 70:
        level = "较高"
    elif core_rate >= 40:
        level = "中等"
    else:
        level = "较低"
    return {"core_coverage_rate": core_rate, "all_coverage_rate": all_rate, "data_quality_level": level}


def build_intraday_snapshot(
    config: str | Dict[str, Any],
    decision_time: str = "1445",
    db_path: str | None = None,
    refresh_data: bool = True,
    baostock_only: bool = False,
    no_web: bool = False,
    save_snapshot: bool = True,
) -> Dict[str, Any]:
    if decision_time not in DECISION_TIMES:
        raise ValueError(f"不支持的 decision_time: {decision_time}")
    config_data = load_fund_portfolio_config(config) if isinstance(config, (str, Path)) else config
    resolved_db_path = resolve_db_path(config_data, db_path)
    initialize_database(resolved_db_path)
    tracking = _collect_tracking_codes(config_data)
    trade_date = _today()
    provider = BaostockProvider()
    baostock_status = "skipped"
    kline_data: Dict[str, Any] = {}
    indicators: Dict[str, Any] = {}

    if refresh_data and config_data.get("data_sources", {}).get("use_baostock", True):
        codes = tracking["etfs"] + tracking["stocks"]
        for code in codes:
            snapshot = provider.fetch_latest_snapshot(code)
            rows = snapshot.get("rows", [])
            indicator = snapshot.get("indicator") or calculate_indicators(rows)
            kline_data[code] = rows
            indicators[code] = indicator
        baostock_status = provider.login_status or "empty"

    snapshot_payload = {
        "portfolio": config_data["portfolio"],
        "funds": config_data.get("funds", []),
        "tracking": tracking,
        "kline": kline_data,
        "indicators": indicators,
        "source_flags": {
            "baostock_only": baostock_only,
            "no_web": no_web,
            "use_web": config_data.get("data_sources", {}).get("use_web", True) and not no_web,
        },
    }
    coverage = _coverage(snapshot_payload)
    diagnostics = {
        "baostock_status": baostock_status,
        "web_status": "skipped" if no_web or baostock_only else "not_implemented",
        "firecrawl_status": "skipped" if not config_data.get("data_sources", {}).get("use_firecrawl") else "not_implemented",
        "notes": ["快照只保存事实数据和来源诊断，不生成硬编码投资结论。"],
    }

    with get_connection(resolved_db_path) as conn:
        repo = FundRepository(conn)
        portfolio_id = repo.upsert_portfolio(config_data["portfolio"])
        for fund in config_data.get("funds", []):
            repo.upsert_fund_config(portfolio_id, fund)
        for code in tracking["etfs"] + tracking["stocks"] + tracking["indices"]:
            repo.upsert_security_master(
                {
                    "code": code,
                    "baostock_code": to_baostock_code(code) if code.isdigit() else "",
                    "name": code,
                    "security_type": _security_type(code),
                    "theme": [],
                }
            )
        for rows in kline_data.values():
            for row in rows:
                repo.upsert_security_kline(row)
        for code, indicator in indicators.items():
            if indicator:
                repo.upsert_security_indicator(indicator)
        snapshot_row = {
            "portfolio_id": portfolio_id,
            "trade_date": trade_date,
            "decision_time": decision_time,
            "snapshot_time": datetime.now().isoformat(timespec="seconds"),
            "source_mode": "baostock_only" if baostock_only else "sql_snapshot",
            **coverage,
            "baostock_status": baostock_status,
            "web_status": diagnostics["web_status"],
            "firecrawl_status": diagnostics["firecrawl_status"],
            "snapshot": snapshot_payload,
            "diagnostics": diagnostics,
            "report_path": "",
        }
        snapshot_id = repo.upsert_intraday_snapshot(snapshot_row) if save_snapshot else 0
        conn.commit()

    return {
        "snapshot_id": snapshot_id,
        "db_path": resolved_db_path,
        "portfolio_id": portfolio_id,
        "trade_date": trade_date,
        "decision_time": decision_time,
        "snapshot": snapshot_payload,
        "diagnostics": diagnostics,
        **coverage,
    }


def save_intraday_snapshot_to_sql(snapshot: Dict[str, Any], db_path: str | Path = "data/fund_assistant.sqlite3") -> int:
    initialize_database(db_path)
    with get_connection(db_path) as conn:
        snapshot_id = FundRepository(conn).upsert_intraday_snapshot(snapshot)
        conn.commit()
        return snapshot_id


def load_intraday_snapshot_from_sql(trade_date: str, decision_time: str, db_path: str | Path = "data/fund_assistant.sqlite3") -> Dict[str, Any] | None:
    initialize_database(db_path)
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM intraday_snapshot WHERE trade_date=? AND decision_time=? ORDER BY updated_at DESC LIMIT 1",
            (trade_date, decision_time),
        ).fetchone()
        return dict(row) if row else None


def get_latest_intraday_snapshot(db_path: str | Path = "data/fund_assistant.sqlite3") -> Dict[str, Any] | None:
    initialize_database(db_path)
    with get_connection(db_path) as conn:
        return FundRepository(conn).get_latest_intraday_snapshot()


def build_context_from_snapshot(snapshot_id: int, db_path: str | Path = "data/fund_assistant.sqlite3") -> Dict[str, Any]:
    initialize_database(db_path)
    with get_connection(db_path) as conn:
        row = FundRepository(conn).get_intraday_snapshot(snapshot_id)
    if not row:
        raise ValueError(f"未找到 intraday_snapshot: {snapshot_id}")
    snapshot_json = json.loads(row.get("snapshot_json") or "{}")
    diagnostics_json = json.loads(row.get("diagnostics_json") or "{}")
    return {**row, "snapshot": snapshot_json, "diagnostics": diagnostics_json}
