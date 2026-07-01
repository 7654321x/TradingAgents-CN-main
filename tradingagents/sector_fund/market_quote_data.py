from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Iterable

import yaml

from .akshare_provider import AkShareProvider
from .db import initialize_database
from .eastmoney_quote_provider import EastMoneyQuoteProvider
from .logging_utils import get_sector_logger


QUOTE_FIELDS = [
    "latest_price",
    "change_pct",
    "change_amount",
    "volume",
    "amount",
    "turnover_rate",
    "open",
    "high",
    "low",
    "previous_close",
    "source_status",
]

FIELD_SOURCE_META = {
    "eastmoney_push2": {
        "source": "eastmoney_push2",
        "upstream_source": "eastmoney",
        "upstream_group": "eastmoney",
        "source_level": "direct_endpoint",
        "independent": 0,
    },
    "eastmoney_push2_sector": {
        "source": "eastmoney_push2",
        "upstream_source": "eastmoney",
        "upstream_group": "eastmoney",
        "source_level": "direct_endpoint",
        "independent": 0,
    },
    "akshare": {
        "source": "akshare",
        "upstream_source": "eastmoney",
        "upstream_group": "eastmoney",
        "source_level": "structured_wrapper",
        "independent": 0,
    },
    "missing": {
        "source": "missing",
        "upstream_source": "missing",
        "upstream_group": "missing",
        "source_level": "missing",
        "independent": 0,
    },
}


def collect_market_quote_targets(config: Dict[str, Any], sql_conn: sqlite3.Connection | None = None) -> Dict[str, list[Any]]:
    etfs: dict[str, Dict[str, str]] = {}
    indices: set[str] = set()
    sectors: set[str] = set()

    def add_tracking(tracking: Dict[str, Any]) -> None:
        for item in _as_list(tracking.get("etfs")):
            code = _tracking_code(item)
            if code:
                etfs.setdefault(code, {"code": code, "name": _tracking_name(item) or code})
        for item in _as_list(tracking.get("indices")):
            name = _tracking_name(item)
            if name:
                indices.add(name)
        for item in _as_list(tracking.get("sectors")):
            name = _tracking_name(item)
            if name:
                sectors.add(name)

    for item in _as_list(config.get("etfs")):
        code = _tracking_code(item)
        if code:
            etfs.setdefault(code, {"code": code, "name": _tracking_name(item) or code})
    for item in _as_list(config.get("indices")):
        name = _tracking_name(item)
        if name:
            indices.add(name)
    for item in _as_list(config.get("sectors")):
        name = _tracking_name(item)
        if name:
            sectors.add(name)
    for fund in _as_list(config.get("funds")):
        if isinstance(fund, dict):
            add_tracking(fund.get("tracking") or {})

    if sql_conn is not None:
        _collect_targets_from_sql(sql_conn, add_tracking)

    return {"etfs": sorted(etfs.values(), key=lambda item: item["code"]), "indices": sorted(indices), "sectors": sorted(sectors)}


def refresh_market_quotes(
    config_path: str,
    decision_time: str,
    trade_date: str | None = None,
    use_sql: bool = True,
    logger=None,
) -> Dict[str, Any]:
    logger = logger or get_sector_logger("market")
    config = _load_config(config_path)
    db_path = config.get("database", {}).get("path") or "data/fund_assistant.sqlite3"
    initialize_database(db_path)
    trade_date = trade_date or date.today().isoformat()
    snapshot_time = _snapshot_time(decision_time)
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        targets = collect_market_quote_targets(config, sql_conn=conn)

    logger.info(
        "📥 [MarketQuote] 开始刷新ETF/指数/板块行情 | etfs=%s indices=%s sectors=%s decision_time=%s",
        len(targets["etfs"]),
        len(targets["indices"]),
        len(targets["sectors"]),
        decision_time,
    )
    etf_quotes = _fetch_etf_quotes(targets["etfs"])
    index_quotes = _fetch_index_quotes(targets["indices"])
    logger.info("📥 [MarketQuote] 开始刷新板块行情 | sectors=%s", len(targets["sectors"]))
    sector_quotes = _fetch_sector_quotes(targets["sectors"])

    for code, item in etf_quotes.items():
        if item.get("source_status") == "success":
            logger.info("✅ [MarketQuote] ETF行情读取成功 | code=%s change_pct=%s source=%s", code, item.get("change_pct"), item.get("final_source") or item.get("source"))
    for name, item in index_quotes.items():
        if item.get("source_status") == "success":
            logger.info("✅ [MarketQuote] 指数行情读取成功 | name=%s change_pct=%s source=%s", name, item.get("change_pct"), item.get("final_source") or item.get("source"))
    for name, item in sector_quotes.items():
        if item.get("source_status") == "success":
            logger.info("✅ [MarketQuote] 板块行情读取成功 | sector=%s change_pct=%s source=%s", name, item.get("change_pct"), item.get("final_source") or item.get("source"))
        else:
            logger.warning("⚠️ [MarketQuote] 板块行情缺失 | sector=%s source=eastmoney/akshare", name)

    write_result = {"security_quote_snapshot_rows": 0, "field_source_rows": 0, "data_source_run_rows": 0}
    run_id = f"market_quote_refresh_{trade_date}_{decision_time}"
    if use_sql:
        write_result = write_market_quotes_to_sql(
            db_path=db_path,
            run_id=run_id,
            trade_date=trade_date,
            decision_time=decision_time,
            snapshot_time=snapshot_time,
            etf_quotes=etf_quotes,
            index_quotes=index_quotes,
            sector_quotes=sector_quotes,
        )
    summary = {
        "etf_success": _success_count(etf_quotes),
        "etf_total": len(targets["etfs"]),
        "index_success": _success_count(index_quotes),
        "index_total": len(targets["indices"]),
        "sector_success": _success_count(sector_quotes),
        "sector_total": len(targets["sectors"]),
    }
    logger.info(
        "📊 [MarketQuote] 刷新完成 | etf_success=%s/%s index_success=%s/%s sector_success=%s/%s",
        summary["etf_success"],
        summary["etf_total"],
        summary["index_success"],
        summary["index_total"],
        summary["sector_success"],
        summary["sector_total"],
    )
    return {
        "trade_date": trade_date,
        "decision_time": decision_time,
        "snapshot_time": snapshot_time,
        "targets": targets,
        "etfs": etf_quotes,
        "indices": index_quotes,
        "sectors": sector_quotes,
        "summary": summary,
        "write_result": write_result,
        "market_quote_count": len(etf_quotes) + len(index_quotes) + len(sector_quotes),
        "db_path": db_path,
        "run_id": run_id,
    }


def write_market_quotes_to_sql(
    db_path: str | Path,
    run_id: str,
    trade_date: str,
    decision_time: str,
    snapshot_time: str,
    etf_quotes: Dict[str, Dict[str, Any]],
    index_quotes: Dict[str, Dict[str, Any]],
    sector_quotes: Dict[str, Dict[str, Any]],
) -> Dict[str, int]:
    initialize_database(db_path)
    now = datetime.now().isoformat(timespec="seconds")
    quote_rows = 0
    field_rows = 0
    with sqlite3.connect(db_path) as conn:
        for entity_type, quotes in (("etf", etf_quotes), ("index", index_quotes), ("sector", sector_quotes)):
            for code, quote in quotes.items():
                source = quote.get("final_source") or quote.get("source") or "missing"
                meta = FIELD_SOURCE_META.get(source, FIELD_SOURCE_META.get(quote.get("source", ""), FIELD_SOURCE_META["missing"]))
                conn.execute(
                    """
                    INSERT INTO security_quote_snapshot (
                        entity_type, code, name, trade_date, snapshot_time, latest_price, change_pct,
                        change_amount, volume, amount, turnover_rate, high, low, open, previous_close,
                        source, source_status, final_source, upstream_group, audit_status, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(entity_type, code, trade_date, snapshot_time, source) DO UPDATE SET
                        name=excluded.name,
                        latest_price=excluded.latest_price,
                        change_pct=excluded.change_pct,
                        change_amount=excluded.change_amount,
                        volume=excluded.volume,
                        amount=excluded.amount,
                        turnover_rate=excluded.turnover_rate,
                        high=excluded.high,
                        low=excluded.low,
                        open=excluded.open,
                        previous_close=excluded.previous_close,
                        source_status=excluded.source_status,
                        final_source=excluded.final_source,
                        upstream_group=excluded.upstream_group,
                        audit_status=excluded.audit_status,
                        updated_at=excluded.updated_at
                    """,
                    (
                        entity_type,
                        code,
                        quote.get("name") or code,
                        trade_date,
                        snapshot_time,
                        _num(quote.get("latest_price")),
                        _num(quote.get("change_pct")),
                        _num(quote.get("change_amount")),
                        _num(quote.get("volume")),
                        _num(quote.get("amount")),
                        _num(quote.get("turnover_rate")),
                        _num(quote.get("high")),
                        _num(quote.get("low")),
                        _num(quote.get("open")),
                        _num(quote.get("previous_close") or quote.get("preclose")),
                        source,
                        quote.get("source_status") or "missing",
                        source,
                        meta["upstream_group"],
                        _audit_status(entity_type, quote),
                        now,
                        now,
                    ),
                )
                quote_rows += 1
                field_rows += _write_field_source_rows(conn, run_id, entity_type, code, quote, trade_date, snapshot_time)
        data_source_rows = _write_data_source_run(conn, run_id, trade_date, decision_time, {**etf_quotes, **index_quotes, **sector_quotes}, now)
    return {"security_quote_snapshot_rows": quote_rows, "field_source_rows": field_rows, "data_source_run_rows": data_source_rows}


def _fetch_etf_quotes(etfs: Iterable[Dict[str, str]]) -> Dict[str, Dict[str, Any]]:
    items = list(etfs)
    codes = [item["code"] for item in items]
    names = {item["code"]: item.get("name") or item["code"] for item in items}
    eastmoney = EastMoneyQuoteProvider()
    quotes = eastmoney.fetch_quotes(codes)
    missing = [code for code in codes if not _is_success_quote(quotes.get(code))]
    if missing:
        ak_quotes = AkShareProvider().fetch_etf_spot(missing)
        for code in missing:
            quotes[code] = ak_quotes.get(code, {})
    result: Dict[str, Dict[str, Any]] = {}
    for code in codes:
        quote = dict(quotes.get(code) or {})
        if not _is_success_quote(quote):
            quote = _missing_quote(code, names.get(code, code), "etf", quote.get("error_reason") or eastmoney.last_error)
        result[code] = _normalize_quote(quote, code, names.get(code, code))
    return result


def _fetch_index_quotes(indices: Iterable[str]) -> Dict[str, Dict[str, Any]]:
    names = [str(item) for item in indices if item]
    eastmoney = EastMoneyQuoteProvider()
    quotes = eastmoney.fetch_quotes(names)
    result: Dict[str, Dict[str, Any]] = {}
    for name in names:
        code = _index_code(name)
        quote = quotes.get(code) or quotes.get(name) or {}
        if not _is_success_quote(quote):
            quote = _missing_quote(name, name, "index", quote.get("error_reason") or eastmoney.last_error)
        result[name] = _normalize_quote(quote, name, name)
    return result


def _fetch_sector_quotes(sectors: Iterable[str]) -> Dict[str, Dict[str, Any]]:
    names = [str(item) for item in sectors if item]
    eastmoney = EastMoneyQuoteProvider()
    quotes = eastmoney.fetch_sector_changes(names)
    missing = [name for name in names if not _is_success_sector(quotes.get(name))]
    if missing:
        ak_quotes = AkShareProvider().fetch_sector_boards(missing)
        for name in missing:
            quotes[name] = ak_quotes.get(name, {})
    result: Dict[str, Dict[str, Any]] = {}
    for name in names:
        quote = dict(quotes.get(name) or {})
        if not _is_success_sector(quote):
            quote = _missing_quote(name, name, "sector", quote.get("error_reason") or eastmoney.last_error)
        result[name] = _normalize_quote(quote, name, name)
    return result


def _write_field_source_rows(
    conn: sqlite3.Connection,
    run_id: str,
    entity_type: str,
    code: str,
    quote: Dict[str, Any],
    trade_date: str,
    snapshot_time: str,
) -> int:
    source = quote.get("final_source") or quote.get("source") or "missing"
    meta = FIELD_SOURCE_META.get(source, FIELD_SOURCE_META.get(quote.get("source", ""), FIELD_SOURCE_META["missing"]))
    conn.execute(
        "DELETE FROM field_source WHERE run_id=? AND entity_type=? AND entity_code=?",
        (run_id, entity_type, code),
    )
    rows = []
    for field_name in QUOTE_FIELDS:
        if entity_type == "sector" and field_name not in {"change_pct", "amount", "source_status"}:
            continue
        rows.append((field_name, quote.get(field_name)))
    rows.extend([("final_source", source), ("trade_date", trade_date), ("data_time", snapshot_time)])
    count = 0
    for field_name, value in rows:
        semantic = f"{entity_type}.{code}.{field_name}"
        status = "success" if value not in (None, "") and source != "missing" else "missing"
        if field_name == "source_status":
            status = quote.get("source_status") or status
        conn.execute(
            """
            INSERT INTO field_source (
                run_id, entity_type, entity_code, entity_name, field_name, semantic_field,
                source, upstream_source, upstream_group, source_level, independent,
                source_status, value_text, value_numeric, trade_date, data_time, parser_status,
                confidence, error_reason, fix_suggestion, final_source, audit_status, run_time
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                entity_type,
                code,
                quote.get("name") or code,
                field_name,
                semantic,
                meta["source"],
                meta["upstream_source"],
                meta["upstream_group"],
                meta["source_level"],
                meta["independent"],
                quote.get("source_status") or status,
                "" if value is None else str(value),
                _num(value),
                trade_date,
                snapshot_time,
                quote.get("parser_status") or status,
                0.95 if status == "success" else 0.0,
                "" if status == "success" else quote.get("error_reason") or f"{field_name} missing",
                "" if status == "success" else "检查EastMoney/AKShare行情源。",
                source,
                "ok" if status == "success" else "missing",
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        count += 1
    return count


def _write_data_source_run(conn: sqlite3.Connection, run_id: str, trade_date: str, decision_time: str, quotes: Dict[str, Dict[str, Any]], now: str) -> int:
    matched = sum(1 for item in quotes.values() if item.get("source_status") == "success")
    missing = max(0, len(quotes) - matched)
    errors = [str(item.get("error_reason") or "") for item in quotes.values() if item.get("error_reason")]
    conn.execute("DELETE FROM data_source_run WHERE run_id=? AND source_name='market_quotes'", (run_id,))
    conn.execute(
        """
        INSERT INTO data_source_run (
            run_id, trade_date, decision_time, source_name, source_type, fetch_status,
            matched_fields_count, missing_fields_count, error_reason, parser_status,
            started_at, finished_at, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            trade_date,
            decision_time,
            "market_quotes",
            "market_quote_refresh",
            "success" if matched else "missing",
            matched,
            missing,
            "; ".join(errors[:5]),
            "success" if matched else "missing",
            now,
            datetime.now().isoformat(timespec="seconds"),
            now,
        ),
    )
    return 1


def _collect_targets_from_sql(conn: sqlite3.Connection, add_tracking) -> None:
    tables = {str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    if "fund_config" in tables:
        for row in conn.execute("SELECT tracking_json FROM fund_config WHERE tracking_json IS NOT NULL ORDER BY updated_at DESC, id DESC").fetchall():
            payload = _json_load(row[0])
            if payload:
                add_tracking(payload)
    if "fund_enrichment_result" in tables:
        for row in conn.execute("SELECT auto_enriched_json FROM fund_enrichment_result WHERE auto_enriched_json IS NOT NULL ORDER BY created_at DESC, id DESC LIMIT 20").fetchall():
            payload = _json_load(row[0])
            tracking = payload.get("tracking") if isinstance(payload.get("tracking"), dict) else payload
            if isinstance(tracking, dict):
                add_tracking(tracking)


def _normalize_quote(quote: Dict[str, Any], code: str, name: str) -> Dict[str, Any]:
    source = quote.get("source") or "missing"
    final_source = quote.get("final_source") or source
    if final_source == "eastmoney_push2_sector":
        final_source = "eastmoney_push2"
    return {
        **quote,
        "code": quote.get("code") or code,
        "name": quote.get("name") or quote.get("sector_name") or name,
        "latest_price": _num(quote.get("latest_price")),
        "change_pct": _num(quote.get("change_pct")),
        "change_amount": _num(quote.get("change_amount")),
        "volume": _num(quote.get("volume")),
        "amount": _num(quote.get("amount")),
        "turnover_rate": _num(quote.get("turnover_rate")),
        "open": _num(quote.get("open")),
        "high": _num(quote.get("high")),
        "low": _num(quote.get("low")),
        "previous_close": _num(quote.get("previous_close") or quote.get("preclose")),
        "source": source,
        "final_source": final_source,
        "source_status": quote.get("source_status") or "missing",
        "parser_status": quote.get("parser_status") or quote.get("source_status") or "missing",
    }


def _missing_quote(code: str, name: str, entity_type: str, reason: str = "") -> Dict[str, Any]:
    return {
        "code": code,
        "name": name,
        "entity_type": entity_type,
        "source": "missing",
        "final_source": "missing",
        "source_status": "missing",
        "parser_status": "missing",
        "error_reason": reason or "market quote missing",
    }


def _load_config(config_path: str | Path) -> Dict[str, Any]:
    path = Path(config_path)
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


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


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _tracking_code(item: Any) -> str:
    if isinstance(item, dict):
        raw = item.get("code") or item.get("symbol") or ""
    else:
        raw = item
    text = str(raw or "").strip()
    digits = "".join(ch for ch in text if ch.isdigit())
    return digits.zfill(6) if digits else text


def _tracking_name(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get("name") or item.get("code") or item.get("symbol") or "")
    return str(item or "")


def _snapshot_time(decision_time: str) -> str:
    return {"1000": "10:00:00", "1445": "14:45:00", "night": "21:30:00"}.get(str(decision_time), str(decision_time))


def _success_count(quotes: Dict[str, Dict[str, Any]]) -> int:
    return sum(1 for item in quotes.values() if item.get("source_status") == "success")


def _is_success_quote(quote: Dict[str, Any] | None) -> bool:
    return bool(quote and quote.get("source_status") == "success" and (quote.get("latest_price") is not None or quote.get("change_pct") is not None))


def _is_success_sector(quote: Dict[str, Any] | None) -> bool:
    return bool(quote and quote.get("source_status") == "success" and quote.get("change_pct") is not None)


def _index_code(name: str) -> str:
    return {"创业板指": "399006", "科创50": "000688", "上证指数": "000001", "上证综指": "000001", "深成指": "399001"}.get(name, name)


def _audit_status(entity_type: str, quote: Dict[str, Any]) -> str:
    if quote.get("source_status") != "success":
        return "missing"
    if entity_type == "sector":
        return "ok" if quote.get("change_pct") is not None else "missing"
    return "ok" if quote.get("latest_price") is not None or quote.get("change_pct") is not None else "missing"


def _num(value: Any) -> float | None:
    if value in (None, "", "-", "--", "missing"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
