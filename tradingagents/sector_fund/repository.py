import json
import sqlite3
from typing import Any, Dict, Iterable, List, Optional


def _json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False)


def _row_to_dict(row: sqlite3.Row | None) -> Optional[Dict[str, Any]]:
    return dict(row) if row is not None else None


class FundRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def upsert_portfolio(self, portfolio: Dict[str, Any]) -> int:
        self.conn.execute(
            """
            INSERT INTO portfolio(name, style, total_position_pct, target_position_pct, max_position_pct,
                                  cash_position_pct, description, is_active, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1, CURRENT_TIMESTAMP)
            ON CONFLICT(name) DO UPDATE SET
                style=excluded.style,
                total_position_pct=excluded.total_position_pct,
                target_position_pct=excluded.target_position_pct,
                max_position_pct=excluded.max_position_pct,
                cash_position_pct=excluded.cash_position_pct,
                description=excluded.description,
                updated_at=CURRENT_TIMESTAMP
            """,
            (
                portfolio.get("name"),
                portfolio.get("style"),
                portfolio.get("total_position_pct"),
                portfolio.get("target_position_pct"),
                portfolio.get("max_position_pct"),
                portfolio.get("cash_position_pct"),
                portfolio.get("description", ""),
            ),
        )
        return int(self.conn.execute("SELECT id FROM portfolio WHERE name=?", (portfolio.get("name"),)).fetchone()["id"])

    def upsert_fund_config(self, portfolio_id: int, fund: Dict[str, Any]) -> int:
        self.conn.execute(
            """
            INSERT INTO fund_config(portfolio_id, fund_code, fund_name, fund_type, role, position_pct,
                                    max_single_position_pct, risk_level, decision_priority, holding_days,
                                    fee_note, is_active, tracking_json, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(portfolio_id, fund_code) DO UPDATE SET
                fund_name=excluded.fund_name,
                fund_type=excluded.fund_type,
                role=excluded.role,
                position_pct=excluded.position_pct,
                max_single_position_pct=excluded.max_single_position_pct,
                risk_level=excluded.risk_level,
                decision_priority=excluded.decision_priority,
                holding_days=excluded.holding_days,
                fee_note=excluded.fee_note,
                tracking_json=excluded.tracking_json,
                updated_at=CURRENT_TIMESTAMP
            """,
            (
                portfolio_id,
                fund.get("code"),
                fund.get("name"),
                fund.get("type"),
                fund.get("role"),
                fund.get("position_pct"),
                fund.get("max_single_position_pct"),
                fund.get("risk_level"),
                fund.get("decision_priority"),
                fund.get("holding_days"),
                fund.get("fee_note", ""),
                _json(fund.get("tracking", {})),
            ),
        )
        row = self.conn.execute(
            "SELECT id FROM fund_config WHERE portfolio_id=? AND fund_code=?",
            (portfolio_id, fund.get("code")),
        ).fetchone()
        return int(row["id"])

    def upsert_security_master(self, security: Dict[str, Any]) -> None:
        self.conn.execute(
            """
            INSERT INTO security_master(code, baostock_code, name, security_type, market, exchange, sector,
                                        theme_json, is_active, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, CURRENT_TIMESTAMP)
            ON CONFLICT(code) DO UPDATE SET
                baostock_code=excluded.baostock_code,
                name=excluded.name,
                security_type=excluded.security_type,
                market=excluded.market,
                exchange=excluded.exchange,
                sector=excluded.sector,
                theme_json=excluded.theme_json,
                updated_at=CURRENT_TIMESTAMP
            """,
            (
                security.get("code"),
                security.get("baostock_code"),
                security.get("name"),
                security.get("security_type"),
                security.get("market"),
                security.get("exchange"),
                security.get("sector"),
                _json(security.get("theme", [])),
            ),
        )

    def upsert_security_kline(self, row: Dict[str, Any]) -> None:
        self.conn.execute(
            """
            INSERT INTO security_kline_daily(code, baostock_code, trade_date, open, high, low, close, preclose,
                                             pct_chg, volume, amount, turnover_rate, tradestatus, source,
                                             source_status, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(code, trade_date) DO UPDATE SET
                baostock_code=excluded.baostock_code,
                open=excluded.open,
                high=excluded.high,
                low=excluded.low,
                close=excluded.close,
                preclose=excluded.preclose,
                pct_chg=excluded.pct_chg,
                volume=excluded.volume,
                amount=excluded.amount,
                turnover_rate=excluded.turnover_rate,
                tradestatus=excluded.tradestatus,
                source=excluded.source,
                source_status=excluded.source_status,
                updated_at=CURRENT_TIMESTAMP
            """,
            (
                row.get("code"),
                row.get("baostock_code"),
                row.get("trade_date") or row.get("date"),
                row.get("open"),
                row.get("high"),
                row.get("low"),
                row.get("close"),
                row.get("preclose"),
                row.get("pct_chg"),
                row.get("volume"),
                row.get("amount"),
                row.get("turnover_rate"),
                row.get("tradestatus"),
                row.get("source", "baostock"),
                row.get("source_status", "success"),
            ),
        )

    def upsert_security_indicator(self, row: Dict[str, Any]) -> None:
        self.conn.execute(
            """
            INSERT INTO security_indicator_daily(code, trade_date, ma5, ma10, ma20, ma60, below_ma5,
                                                 below_ma10, below_ma20, near_ma5, near_ma10,
                                                 long_upper_shadow, intraday_pullback, signal_json,
                                                 field_sources_json, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(code, trade_date) DO UPDATE SET
                ma5=excluded.ma5,
                ma10=excluded.ma10,
                ma20=excluded.ma20,
                ma60=excluded.ma60,
                below_ma5=excluded.below_ma5,
                below_ma10=excluded.below_ma10,
                below_ma20=excluded.below_ma20,
                near_ma5=excluded.near_ma5,
                near_ma10=excluded.near_ma10,
                long_upper_shadow=excluded.long_upper_shadow,
                intraday_pullback=excluded.intraday_pullback,
                signal_json=excluded.signal_json,
                field_sources_json=excluded.field_sources_json,
                updated_at=CURRENT_TIMESTAMP
            """,
            (
                row.get("code"),
                row.get("trade_date"),
                row.get("ma5"),
                row.get("ma10"),
                row.get("ma20"),
                row.get("ma60"),
                _bool_or_none(row.get("below_ma5")),
                _bool_or_none(row.get("below_ma10")),
                _bool_or_none(row.get("below_ma20")),
                _bool_or_none(row.get("near_ma5")),
                _bool_or_none(row.get("near_ma10")),
                _bool_or_none(row.get("long_upper_shadow")),
                _bool_or_none(row.get("intraday_pullback")),
                _json(row.get("signal", {})),
                _json(row.get("field_sources", {})),
            ),
        )

    def upsert_intraday_snapshot(self, snapshot: Dict[str, Any]) -> int:
        self.conn.execute(
            """
            INSERT INTO intraday_snapshot(portfolio_id, trade_date, decision_time, snapshot_time, source_mode,
                                          core_coverage_rate, all_coverage_rate, data_quality_level,
                                          baostock_status, web_status, firecrawl_status, snapshot_json,
                                          diagnostics_json, report_path, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(portfolio_id, trade_date, decision_time) DO UPDATE SET
                snapshot_time=excluded.snapshot_time,
                source_mode=excluded.source_mode,
                core_coverage_rate=excluded.core_coverage_rate,
                all_coverage_rate=excluded.all_coverage_rate,
                data_quality_level=excluded.data_quality_level,
                baostock_status=excluded.baostock_status,
                web_status=excluded.web_status,
                firecrawl_status=excluded.firecrawl_status,
                snapshot_json=excluded.snapshot_json,
                diagnostics_json=excluded.diagnostics_json,
                report_path=excluded.report_path,
                updated_at=CURRENT_TIMESTAMP
            """,
            (
                snapshot["portfolio_id"],
                snapshot["trade_date"],
                snapshot["decision_time"],
                snapshot.get("snapshot_time"),
                snapshot.get("source_mode"),
                snapshot.get("core_coverage_rate"),
                snapshot.get("all_coverage_rate"),
                snapshot.get("data_quality_level"),
                snapshot.get("baostock_status"),
                snapshot.get("web_status"),
                snapshot.get("firecrawl_status"),
                _json(snapshot.get("snapshot", {})),
                _json(snapshot.get("diagnostics", {})),
                snapshot.get("report_path"),
            ),
        )
        row = self.conn.execute(
            "SELECT id FROM intraday_snapshot WHERE portfolio_id=? AND trade_date=? AND decision_time=?",
            (snapshot["portfolio_id"], snapshot["trade_date"], snapshot["decision_time"]),
        ).fetchone()
        return int(row["id"])

    def get_intraday_snapshot(self, snapshot_id: int) -> Optional[Dict[str, Any]]:
        row = self.conn.execute("SELECT * FROM intraday_snapshot WHERE id=?", (snapshot_id,)).fetchone()
        return _row_to_dict(row)

    def get_latest_intraday_snapshot(self) -> Optional[Dict[str, Any]]:
        row = self.conn.execute("SELECT * FROM intraday_snapshot ORDER BY trade_date DESC, updated_at DESC LIMIT 1").fetchone()
        return _row_to_dict(row)

    def update_intraday_report_path(self, snapshot_id: int, report_path: str) -> None:
        self.conn.execute(
            "UPDATE intraday_snapshot SET report_path=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (report_path, snapshot_id),
        )

    def list_funds(self, portfolio_id: int) -> List[Dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM fund_config WHERE portfolio_id=? AND is_active=1 ORDER BY decision_priority, id",
            (portfolio_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def record_field_sources(self, snapshot_id: int, rows: Iterable[Dict[str, Any]]) -> None:
        self.conn.execute("DELETE FROM field_source WHERE snapshot_id=?", (snapshot_id,))
        self.conn.executemany(
            """
            INSERT INTO field_source(snapshot_id, entity_type, entity_code, field_name, source,
                                     source_status, value_text, confidence)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    snapshot_id,
                    row.get("entity_type"),
                    row.get("entity_code"),
                    row.get("field_name"),
                    row.get("source"),
                    row.get("source_status"),
                    row.get("value_text"),
                    row.get("confidence"),
                )
                for row in rows
            ],
        )

    def record_data_source_runs(self, rows: Iterable[Dict[str, Any]]) -> None:
        self.conn.executemany(
            """
            INSERT INTO data_source_run(run_id, trade_date, decision_time, source_name, source_type,
                                        url, fetch_status, status_code, raw_text_length,
                                        matched_fields_count, missing_fields_count, error_reason,
                                        raw_text_path)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    row.get("run_id"),
                    row.get("trade_date"),
                    row.get("decision_time"),
                    row.get("source_name"),
                    row.get("source_type"),
                    row.get("url"),
                    row.get("fetch_status"),
                    row.get("status_code"),
                    row.get("raw_text_length"),
                    row.get("matched_fields_count"),
                    row.get("missing_fields_count"),
                    row.get("error_reason"),
                    row.get("raw_text_path"),
                )
                for row in rows
            ],
        )


def _bool_or_none(value: Any) -> Optional[int]:
    if value is None:
        return None
    return 1 if bool(value) else 0
