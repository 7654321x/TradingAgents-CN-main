from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List

import yaml

from .akshare_provider import AkShareProvider
from .baostock_provider import BaostockProvider, calculate_indicators, to_baostock_code
from .db import initialize_database
from .eastmoney_quote_provider import EastMoneyQuoteProvider
from .fetch_logger import DataFetchLogger
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
]

MA_FIELDS = ["ma5", "ma10", "ma20", "below_ma20", "trend_status"]

FIELD_SOURCE_META = {
    "eastmoney_push2": {
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
    "baostock": {
        "source": "baostock",
        "upstream_source": "baostock",
        "upstream_group": "baostock",
        "source_level": "structured_provider",
        "independent": 1,
    },
    "missing": {
        "source": "missing",
        "upstream_source": "missing",
        "upstream_group": "missing",
        "source_level": "missing",
        "independent": 0,
    },
}


@dataclass
class HoldingStock:
    fund_code: str
    stock_code: str
    stock_name: str = ""
    holding_weight_pct: float | None = None
    source: str = ""
    report_date: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "fund_code": self.fund_code,
            "stock_code": self.stock_code,
            "stock_name": self.stock_name,
            "holding_weight_pct": self.holding_weight_pct,
            "source": self.source,
            "report_date": self.report_date,
        }


def refresh_holding_stock_data(
    config_path: str = "config/personal_fund_portfolio.yaml",
    db_path: str | None = None,
    decision_time: str = "1445",
    fund_codes: Iterable[str] | None = None,
    top_n: int = 10,
) -> Dict[str, Any]:
    logger = get_sector_logger("holding")
    resolved_db_path = db_path or _db_path_from_config(config_path)
    initialize_database(resolved_db_path)
    run_id = f"holding_stock_refresh_{date.today().isoformat()}_{decision_time}"
    logger.info("📥 [HoldingStock] 开始刷新持仓股行情 | top_n=%s decision_time=%s", top_n, decision_time)
    stocks = collect_holding_stock_codes(
        config_path=config_path,
        db_path=resolved_db_path,
        fund_codes=fund_codes,
        top_n=top_n,
    )
    stock_codes = [item.stock_code for item in stocks]
    quotes = fetch_holding_stock_quotes(stock_codes)
    history = fetch_holding_stock_history(stock_codes)
    ma_fields = compute_holding_stock_ma_fields(quotes, history)
    fetch_logger = DataFetchLogger()
    logger.info("📊 [HoldingStock] 持仓股列表完成 | stocks=%s", len(stock_codes))
    fetch_logger.quote_summary("holding_stock_quote(eastmoney/akshare)", quotes)
    fetch_logger.quote_summary("holding_stock_history(baostock/akshare)", ma_fields)
    for code, item in quotes.items():
        if item.get("latest_price") is not None:
            logger.info(
                "✅ [HoldingStock] 行情读取成功 | stock=%s name=%s price=%s change=%s",
                code,
                item.get("name", ""),
                item.get("latest_price"),
                item.get("change_pct"),
            )
    for code, item in ma_fields.items():
        if item.get("ma20") is not None:
            logger.info(
                "🧮 [HoldingStock] MA计算成功 | stock=%s ma20=%s trend=%s",
                code,
                item.get("ma20"),
                item.get("trend_status"),
            )
    quote_success = sum(1 for item in quotes.values() if item.get("latest_price") is not None and item.get("change_pct") is not None)
    ma20_success = sum(1 for item in ma_fields.values() if item.get("ma20") is not None)
    suspicious = sum(1 for item in list(quotes.values()) + list(ma_fields.values()) if item.get("audit_status") == "suspect")
    logger.info(
        "✅ [HoldingStock] 持仓股行情刷新完成 | total=%s quote_success=%s ma20_success=%s suspicious=%s",
        len(stock_codes),
        quote_success,
        ma20_success,
        suspicious,
    )
    write_result = write_holding_stock_quotes_to_sql(
        db_path=resolved_db_path,
        run_id=run_id,
        stocks=stocks,
        quotes=quotes,
        ma_fields=ma_fields,
        decision_time=decision_time,
    )
    return {
        "run_id": run_id,
        "db_path": resolved_db_path,
        "stock_count": len(stock_codes),
        "stocks": [item.to_dict() for item in stocks],
        "quotes": quotes,
        "ma_fields": ma_fields,
        "write_result": write_result,
    }


def collect_holding_stock_codes(
    fund_codes: Iterable[str] | None = None,
    top_n: int = 10,
    config_path: str = "config/personal_fund_portfolio.yaml",
    db_path: str | None = None,
    holdings_analysis_path: str | Path | None = None,
) -> List[HoldingStock]:
    wanted = {str(code).zfill(6) for code in fund_codes} if fund_codes else None
    config = _load_config(config_path)
    resolved_db_path = db_path or config.get("database", {}).get("path") or "data/fund_assistant.sqlite3"
    candidates: List[HoldingStock] = []
    candidates.extend(_collect_from_holding_snapshot(resolved_db_path, wanted))
    candidates.extend(_collect_from_enrichment_json(resolved_db_path, wanted))
    candidates.extend(_collect_from_config(config, wanted))
    candidates.extend(_collect_from_holdings_analysis(holdings_analysis_path, wanted))
    deduped = _dedupe_holdings(candidates)
    if any(item.holding_weight_pct is not None for item in deduped):
        deduped.sort(key=lambda item: (item.holding_weight_pct is None, -(item.holding_weight_pct or 0)))
    return deduped[:top_n]


def fetch_holding_stock_quotes(stock_codes: Iterable[str]) -> Dict[str, Dict[str, Any]]:
    codes = [_stock_code(code) for code in stock_codes if _stock_code(code)]
    if not codes:
        return {}
    eastmoney = EastMoneyQuoteProvider()
    eastmoney_quotes = eastmoney.fetch_quotes(codes)
    akshare_quotes: Dict[str, Dict[str, Any]] = {}
    missing_codes = [code for code in codes if not _success_quote(eastmoney_quotes.get(code))]
    if missing_codes:
        akshare_quotes = AkShareProvider().fetch_stock_spot(missing_codes)
    result: Dict[str, Dict[str, Any]] = {}
    for code in codes:
        quote = eastmoney_quotes.get(code)
        if _success_quote(quote):
            result[code] = _normalize_quote(code, quote, "eastmoney_push2")
            continue
        quote = akshare_quotes.get(code)
        if _success_quote(quote):
            result[code] = _normalize_quote(code, quote, "akshare")
            continue
        errors = []
        if eastmoney.last_error:
            errors.append(f"eastmoney_push2: {eastmoney.last_error}")
        if quote and quote.get("error_reason"):
            errors.append(f"akshare: {quote.get('error_reason')}")
        result[code] = {
            "code": code,
            "source": "missing",
            "final_source": "missing",
            "source_status": "missing",
            "parser_status": "missing",
            "audit_status": "missing",
            "error_reason": "; ".join(errors) or "holding stock quote missing",
            "fix_suggestion": "检查股票代码映射，或启用 eastmoney/akshare 持仓股行情源。",
        }
    return result


def fetch_holding_stock_history(stock_codes: Iterable[str], lookback_days: int = 40) -> Dict[str, Dict[str, Any]]:
    codes = [_stock_code(code) for code in stock_codes if _stock_code(code)]
    result: Dict[str, Dict[str, Any]] = {}
    baostock = BaostockProvider()
    snapshots = baostock.fetch_latest_daily_snapshots_batch(codes, lookback_days=lookback_days, purpose="holding_stock_history")
    for code in codes:
        snapshot = snapshots.get(code, {})
        if snapshot.get("source_status") == "success" and snapshot.get("rows"):
            result[code] = {
                "code": code,
                "rows": snapshot.get("rows", []),
                "indicator": snapshot.get("indicator", {}),
                "trade_date": snapshot.get("latest_trade_date"),
                "source": "baostock",
                "final_source": "baostock",
                "source_status": "success",
                "parser_status": "success",
                "error_reason": "",
            }
            continue
        akshare_payload = _fetch_akshare_history(code, lookback_days=lookback_days)
        if akshare_payload.get("source_status") == "success":
            result[code] = akshare_payload
            continue
        result[code] = {
            "code": code,
            "rows": [],
            "indicator": {},
            "trade_date": "",
            "source": "missing",
            "final_source": "missing",
            "source_status": "missing",
            "parser_status": "missing",
            "error_reason": snapshot.get("error_reason") or akshare_payload.get("error_reason") or "holding stock history missing",
            "fix_suggestion": "检查 baostock/akshare 历史K线可用性，或确认股票代码是否为 A 股六位代码。",
        }
    return result


def compute_holding_stock_ma_fields(
    quotes: Dict[str, Dict[str, Any]],
    history: Dict[str, Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    result: Dict[str, Dict[str, Any]] = {}
    for code in sorted(set(quotes) | set(history)):
        quote = quotes.get(code, {})
        hist = history.get(code, {})
        indicator = dict(hist.get("indicator") or {})
        latest_price = _num(quote.get("latest_price")) or _num(indicator.get("latest_price"))
        ma20 = _num(indicator.get("ma20"))
        trend_status = _trend_status(latest_price, ma20)
        result[code] = {
            "code": code,
            "ma5": _num(indicator.get("ma5")),
            "ma10": _num(indicator.get("ma10")),
            "ma20": ma20,
            "below_ma20": None if ma20 is None or latest_price is None else int(latest_price < ma20),
            "trend_status": trend_status,
            "history_source": hist.get("source") or "missing",
            "final_source": hist.get("final_source") or hist.get("source") or "missing",
            "source_status": hist.get("source_status") or "missing",
            "parser_status": hist.get("parser_status") or "missing",
            "trade_date": hist.get("trade_date") or "",
            "error_reason": hist.get("error_reason") or "",
            "fix_suggestion": hist.get("fix_suggestion") or "",
        }
    return result


def write_holding_stock_quotes_to_sql(
    db_path: str | Path,
    run_id: str,
    stocks: List[HoldingStock],
    quotes: Dict[str, Dict[str, Any]],
    ma_fields: Dict[str, Dict[str, Any]],
    decision_time: str = "1445",
) -> Dict[str, int]:
    initialize_database(db_path)
    now = datetime.now().isoformat(timespec="seconds")
    trade_date = date.today().isoformat()
    snapshot_time = _snapshot_time(decision_time)
    quote_rows = 0
    field_rows = 0
    data_source_rows = 0
    stock_by_code = {item.stock_code: item for item in stocks}
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        for code, stock in stock_by_code.items():
            quote = quotes.get(code, {})
            ma = ma_fields.get(code, {})
            combined = {**quote, **ma}
            final_source = _pick_final_source(quote.get("final_source"), ma.get("final_source"))
            meta = FIELD_SOURCE_META.get(final_source, FIELD_SOURCE_META["missing"])
            conn.execute(
                """
                INSERT INTO security_quote_snapshot (
                    entity_type, code, name, trade_date, snapshot_time, latest_price, change_pct,
                    change_amount, volume, amount, turnover_rate, high, low, open, previous_close,
                    source, source_status, ma5, ma10, ma20, below_ma20, trend_status,
                    final_source, upstream_group, audit_status, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    ma5=excluded.ma5,
                    ma10=excluded.ma10,
                    ma20=excluded.ma20,
                    below_ma20=excluded.below_ma20,
                    trend_status=excluded.trend_status,
                    final_source=excluded.final_source,
                    upstream_group=excluded.upstream_group,
                    audit_status=excluded.audit_status,
                    updated_at=excluded.updated_at
                """,
                (
                    "stock",
                    code,
                    stock.stock_name or quote.get("name") or code,
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
                    final_source,
                    quote.get("source_status") or ma.get("source_status") or "missing",
                    _num(ma.get("ma5")),
                    _num(ma.get("ma10")),
                    _num(ma.get("ma20")),
                    ma.get("below_ma20"),
                    ma.get("trend_status"),
                    final_source,
                    meta["upstream_group"],
                    _audit_status(combined),
                    now,
                    now,
                ),
            )
            quote_rows += 1
            field_rows += _write_field_source_rows(conn, run_id, stock, quote, ma, trade_date, snapshot_time)
        data_source_rows += _write_data_source_run(
            conn,
            run_id,
            "holding_stock_quotes",
            "holding_stock_quote_refresh",
            quotes,
            now,
            decision_time,
        )
        data_source_rows += _write_data_source_run(
            conn,
            run_id,
            "holding_stock_history",
            "holding_stock_history_refresh",
            ma_fields,
            now,
            decision_time,
        )
    return {
        "security_quote_snapshot_rows": quote_rows,
        "field_source_rows": field_rows,
        "data_source_run_rows": data_source_rows,
    }


def _write_field_source_rows(
    conn: sqlite3.Connection,
    run_id: str,
    stock: HoldingStock,
    quote: Dict[str, Any],
    ma: Dict[str, Any],
    trade_date: str,
    snapshot_time: str,
) -> int:
    rows = []
    quote_source = quote.get("final_source") or quote.get("source") or "missing"
    ma_source = ma.get("final_source") or ma.get("history_source") or "missing"
    combined = {**quote, **ma}
    for field_name in QUOTE_FIELDS:
        rows.append((field_name, quote.get(field_name), quote_source, quote))
    for field_name in MA_FIELDS:
        rows.append((field_name, ma.get(field_name), ma_source, ma))
    rows.extend(
        [
            ("quote_source", quote_source, quote_source, quote),
            ("history_source", ma_source, ma_source, ma),
            ("final_source", _pick_final_source(quote_source, ma_source), _pick_final_source(quote_source, ma_source), combined),
            ("data_time", snapshot_time, quote_source, quote),
            ("trade_date", trade_date, quote_source, quote),
        ]
    )
    conn.execute("DELETE FROM field_source WHERE run_id=? AND entity_type='stock' AND entity_code=?", (run_id, stock.stock_code))
    count = 0
    for field_name, value, source, payload in rows:
        meta = FIELD_SOURCE_META.get(source, FIELD_SOURCE_META["missing"])
        status = "success" if value not in (None, "") and source != "missing" else "missing"
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
                "stock",
                stock.stock_code,
                stock.stock_name,
                field_name,
                field_name,
                meta["source"],
                meta["upstream_source"],
                meta["upstream_group"],
                meta["source_level"],
                meta["independent"],
                payload.get("source_status") or status,
                "" if value is None else str(value),
                _num(value),
                trade_date,
                snapshot_time,
                payload.get("parser_status") or status,
                0.95 if status == "success" else 0.0,
                "" if status == "success" else payload.get("error_reason") or f"{field_name} missing",
                "" if status == "success" else payload.get("fix_suggestion") or "检查持仓股行情/历史K线数据源。",
                source,
                "ok" if status == "success" else "missing",
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        count += 1
    return count


def _write_data_source_run(
    conn: sqlite3.Connection,
    run_id: str,
    source_name: str,
    source_type: str,
    payload: Dict[str, Dict[str, Any]],
    now: str,
    decision_time: str,
) -> int:
    matched = sum(1 for item in payload.values() if item.get("source_status") == "success")
    missing = max(0, len(payload) - matched)
    errors = [str(item.get("error_reason") or "") for item in payload.values() if item.get("error_reason")]
    conn.execute("DELETE FROM data_source_run WHERE run_id=? AND source_name=? AND source_type=?", (run_id, source_name, source_type))
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
            date.today().isoformat(),
            decision_time,
            source_name,
            source_type,
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


def _collect_from_holding_snapshot(db_path: str | Path, wanted: set[str] | None) -> List[HoldingStock]:
    path = Path(db_path)
    if not path.exists():
        return []
    rows: List[HoldingStock] = []
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        if "fund_holding_snapshot" not in _tables(conn):
            return []
        for row in conn.execute("SELECT * FROM fund_holding_snapshot ORDER BY report_date DESC, id ASC").fetchall():
            fund_code = str(row["fund_code"]).zfill(6)
            if wanted and fund_code not in wanted:
                continue
            code = _stock_code(row["holding_stock_code"])
            if not code:
                continue
            rows.append(
                HoldingStock(
                    fund_code=fund_code,
                    stock_code=code,
                    stock_name=str(row["holding_stock_name"] or ""),
                    holding_weight_pct=_num(row["holding_weight_pct"]),
                    source=str(row["source"] or "fund_holding_snapshot"),
                    report_date=str(row["report_date"] or ""),
                )
            )
    return rows


def _collect_from_enrichment_json(db_path: str | Path, wanted: set[str] | None) -> List[HoldingStock]:
    path = Path(db_path)
    if not path.exists():
        return []
    rows: List[HoldingStock] = []
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        if "fund_enrichment_result" not in _tables(conn):
            return []
        for row in conn.execute("SELECT fund_code, auto_enriched_json FROM fund_enrichment_result ORDER BY id DESC").fetchall():
            fund_code = str(row["fund_code"]).zfill(6)
            if wanted and fund_code not in wanted:
                continue
            payload = _json_load(row["auto_enriched_json"])
            for stock in _extract_stock_items(payload):
                item = _holding_from_item(fund_code, stock, "fund_enrichment_result")
                if item:
                    rows.append(item)
    return rows


def _collect_from_config(config: Dict[str, Any], wanted: set[str] | None) -> List[HoldingStock]:
    rows: List[HoldingStock] = []
    for fund in config.get("funds", []) or []:
        fund_code = str(fund.get("code") or "").zfill(6)
        if wanted and fund_code not in wanted:
            continue
        tracking = fund.get("tracking") or {}
        for stock in tracking.get("stocks") or tracking.get("manual_holdings") or []:
            item = _holding_from_item(fund_code, stock, "config_tracking")
            if item:
                rows.append(item)
    return rows


def _collect_from_holdings_analysis(path: str | Path | None, wanted: set[str] | None) -> List[HoldingStock]:
    if path is None:
        base = Path("reports/fund_intraday")
        paths = sorted(base.glob("holdings_analysis_*.json"), reverse=True) if base.exists() else []
        path = paths[0] if paths else None
    if not path or not Path(path).exists():
        return []
    payload = _json_load(Path(path).read_text(encoding="utf-8"))
    rows = []
    for row in payload.get("holdings", []) or []:
        fund_code = str(row.get("fund_code") or "").zfill(6)
        if wanted and fund_code not in wanted:
            continue
        item = _holding_from_item(fund_code, row, "holdings_analysis")
        if item:
            rows.append(item)
    return rows


def _extract_stock_items(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    containers: List[Any] = []
    tracking = payload.get("tracking") if isinstance(payload.get("tracking"), dict) else {}
    containers.extend([tracking.get("stocks"), tracking.get("top_holdings"), tracking.get("manual_holdings")])
    holdings = payload.get("holdings") if isinstance(payload.get("holdings"), dict) else {}
    containers.append(holdings.get("top_holdings"))
    containers.append(payload.get("top_holdings"))
    auto = payload.get("auto_enriched") if isinstance(payload.get("auto_enriched"), dict) else {}
    auto_tracking = auto.get("tracking") if isinstance(auto.get("tracking"), dict) else {}
    containers.append(auto_tracking.get("stocks"))
    result: List[Dict[str, Any]] = []
    for container in containers:
        if isinstance(container, list):
            result.extend([item for item in container if isinstance(item, dict)])
    return result


def _holding_from_item(fund_code: str, item: Any, source: str) -> HoldingStock | None:
    if isinstance(item, str):
        code = _stock_code(item)
        return HoldingStock(fund_code=fund_code, stock_code=code, source=source) if code else None
    if not isinstance(item, dict):
        return None
    code = _stock_code(item.get("holding_stock_code") or item.get("stock_code") or item.get("code"))
    if not code:
        return None
    return HoldingStock(
        fund_code=fund_code,
        stock_code=code,
        stock_name=str(item.get("holding_stock_name") or item.get("stock_name") or item.get("name") or ""),
        holding_weight_pct=_num(item.get("holding_weight_pct") or item.get("weight_pct") or item.get("weight")),
        source=str(item.get("source") or source),
        report_date=str(item.get("report_date") or item.get("date") or ""),
    )


def _dedupe_holdings(items: List[HoldingStock]) -> List[HoldingStock]:
    by_code: Dict[str, HoldingStock] = {}
    order: List[str] = []
    for item in items:
        if item.stock_code not in by_code:
            by_code[item.stock_code] = item
            order.append(item.stock_code)
            continue
        current = by_code[item.stock_code]
        score = int(bool(item.stock_name)) + int(item.holding_weight_pct is not None)
        current_score = int(bool(current.stock_name)) + int(current.holding_weight_pct is not None)
        if score > current_score:
            by_code[item.stock_code] = item
    return [by_code[code] for code in order]


def _fetch_akshare_history(code: str, lookback_days: int) -> Dict[str, Any]:
    try:
        import akshare as ak  # type: ignore

        end_date = date.today().strftime("%Y%m%d")
        start_date = (date.today() - timedelta(days=lookback_days * 2)).strftime("%Y%m%d")
        frame = ak.stock_zh_a_hist(symbol=code, period="daily", start_date=start_date, end_date=end_date, adjust="qfq")
        rows = []
        for row in frame.tail(lookback_days).to_dict("records"):
            rows.append(
                {
                    "code": code,
                    "trade_date": str(row.get("日期") or row.get("date") or ""),
                    "open": _num(row.get("开盘")),
                    "high": _num(row.get("最高")),
                    "low": _num(row.get("最低")),
                    "close": _num(row.get("收盘")),
                    "preclose": None,
                    "volume": _num(row.get("成交量")),
                    "amount": _num(row.get("成交额")),
                    "turnover_rate": _num(row.get("换手率")),
                    "pct_chg": _num(row.get("涨跌幅")),
                    "source": "akshare",
                    "source_status": "success",
                }
            )
        indicator = calculate_indicators(rows)
        return {
            "code": code,
            "rows": rows,
            "indicator": indicator,
            "trade_date": indicator.get("trade_date") or (rows[-1].get("trade_date") if rows else ""),
            "source": "akshare",
            "final_source": "akshare",
            "source_status": "success" if rows else "missing",
            "parser_status": "success" if rows else "missing",
            "error_reason": "" if rows else "akshare stock_zh_a_hist returned no rows",
        }
    except Exception as exc:
        return {
            "code": code,
            "rows": [],
            "indicator": {},
            "source": "akshare",
            "final_source": "missing",
            "source_status": "failed",
            "parser_status": "failed",
            "error_reason": str(exc),
            "fix_suggestion": "检查 akshare 是否可用以及股票代码是否正确。",
        }


def _normalize_quote(code: str, quote: Dict[str, Any], source: str) -> Dict[str, Any]:
    return {
        "code": code,
        "name": quote.get("name") or "",
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
        "final_source": source,
        "source_status": "success",
        "parser_status": "success",
        "audit_status": "ok",
        "error_reason": "",
    }


def _success_quote(quote: Dict[str, Any] | None) -> bool:
    return bool(quote and quote.get("source_status") == "success" and _num(quote.get("latest_price")) is not None)


def _trend_status(latest_price: float | None, ma20: float | None) -> str:
    if ma20 in (None, 0):
        return "ma_insufficient"
    if latest_price is None:
        return "unknown"
    diff = abs(latest_price - ma20) / ma20
    if diff < 0.015:
        return "near_ma20"
    return "above_ma20" if latest_price > ma20 else "below_ma20"


def _audit_status(payload: Dict[str, Any]) -> str:
    return "ok" if payload.get("latest_price") is not None and payload.get("ma20") is not None else "missing"


def _pick_final_source(*sources: Any) -> str:
    for source in sources:
        if source and source != "missing":
            return str(source)
    return "missing"


def _snapshot_time(decision_time: str) -> str:
    return {"1000": "10:00:00", "1445": "14:45:00", "night": "21:30:00"}.get(str(decision_time), str(decision_time))


def _stock_code(value: Any) -> str:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    return digits.zfill(6) if digits else ""


def _num(value: Any) -> float | None:
    if value in (None, "", "-", "--"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}


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


def _load_config(config_path: str) -> Dict[str, Any]:
    path = Path(config_path)
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _db_path_from_config(config_path: str) -> str:
    config = _load_config(config_path)
    return config.get("database", {}).get("path") or "data/fund_assistant.sqlite3"
