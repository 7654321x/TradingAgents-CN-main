import sqlite3
from pathlib import Path


def get_connection(db_path: str | Path = "data/fund_assistant.sqlite3") -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_database(db_path: str | Path = "data/fund_assistant.sqlite3") -> None:
    with get_connection(db_path) as conn:
        create_schema(conn)


def create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS portfolio (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            style TEXT,
            total_position_pct REAL,
            target_position_pct REAL,
            max_position_pct REAL,
            cash_position_pct REAL,
            description TEXT,
            is_active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS fund_config (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            portfolio_id INTEGER NOT NULL,
            fund_code TEXT NOT NULL,
            fund_name TEXT,
            fund_type TEXT,
            role TEXT,
            position_pct REAL,
            max_single_position_pct REAL,
            risk_level TEXT,
            decision_priority INTEGER,
            holding_days INTEGER,
            fee_note TEXT,
            is_active INTEGER DEFAULT 1,
            tracking_json TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(portfolio_id, fund_code)
        );

        CREATE TABLE IF NOT EXISTS fund_nav_daily (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fund_code TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            unit_nav REAL,
            accumulated_nav REAL,
            daily_change_pct REAL,
            source TEXT,
            source_status TEXT,
            field_sources_json TEXT,
            raw_text_path TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(fund_code, trade_date)
        );

        CREATE TABLE IF NOT EXISTS fund_intraday_estimate (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fund_code TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            decision_time TEXT NOT NULL,
            estimate_time TEXT,
            estimate_nav REAL,
            estimate_change_pct REAL,
            unit_nav_previous REAL,
            estimate_source TEXT,
            source_status TEXT,
            field_sources_json TEXT,
            raw_text_path TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(fund_code, trade_date, decision_time)
        );

        CREATE TABLE IF NOT EXISTS fund_holding_snapshot (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fund_code TEXT NOT NULL,
            report_date TEXT NOT NULL,
            holding_stock_code TEXT,
            holding_stock_name TEXT,
            holding_weight_pct REAL,
            holding_market TEXT,
            holding_type TEXT,
            source TEXT,
            source_status TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS security_master (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL UNIQUE,
            baostock_code TEXT,
            name TEXT,
            security_type TEXT,
            market TEXT,
            exchange TEXT,
            sector TEXT,
            theme_json TEXT,
            is_active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS security_kline_daily (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL,
            baostock_code TEXT,
            trade_date TEXT NOT NULL,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            preclose REAL,
            pct_chg REAL,
            volume REAL,
            amount REAL,
            turnover_rate REAL,
            tradestatus TEXT,
            source TEXT,
            source_status TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(code, trade_date)
        );

        CREATE TABLE IF NOT EXISTS security_indicator_daily (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            ma5 REAL,
            ma10 REAL,
            ma20 REAL,
            ma60 REAL,
            below_ma5 INTEGER,
            below_ma10 INTEGER,
            below_ma20 INTEGER,
            near_ma5 INTEGER,
            near_ma10 INTEGER,
            long_upper_shadow INTEGER,
            intraday_pullback INTEGER,
            signal_json TEXT,
            field_sources_json TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(code, trade_date)
        );

        CREATE TABLE IF NOT EXISTS sector_snapshot (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sector_name TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            decision_time TEXT NOT NULL,
            change_pct REAL,
            change_5d_pct REAL,
            turnover_billion REAL,
            main_net_inflow_billion REAL,
            five_day_inflow_billion REAL,
            ten_day_inflow_billion REAL,
            rising_count INTEGER,
            falling_count INTEGER,
            limit_up_count INTEGER,
            limit_down_count INTEGER,
            rank_num INTEGER,
            leading_stocks_json TEXT,
            lagging_stocks_json TEXT,
            source TEXT,
            source_status TEXT,
            field_sources_json TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS market_snapshot (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_date TEXT NOT NULL,
            decision_time TEXT NOT NULL,
            sh_index_change_pct REAL,
            sz_index_change_pct REAL,
            chinext_change_pct REAL,
            star50_change_pct REAL,
            hs300_change_pct REAL,
            total_turnover_billion REAL,
            rising_count INTEGER,
            falling_count INTEGER,
            limit_up_count INTEGER,
            limit_down_count INTEGER,
            source TEXT,
            source_status TEXT,
            field_sources_json TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS lhb_event (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stock_code TEXT NOT NULL,
            stock_name TEXT,
            trade_date TEXT NOT NULL,
            is_on_lhb INTEGER,
            reason TEXT,
            buy_top5_amount_billion REAL,
            sell_top5_amount_billion REAL,
            net_buy_amount_billion REAL,
            institution_net_buy_billion REAL,
            hot_money_net_buy_billion REAL,
            sentiment_tag TEXT,
            source TEXT,
            source_status TEXT,
            raw_text_path TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS announcement_event (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_date TEXT NOT NULL,
            stock_code TEXT,
            stock_name TEXT,
            title TEXT,
            event_type TEXT,
            sentiment TEXT,
            importance INTEGER,
            summary TEXT,
            is_earnings_increase INTEGER,
            is_earnings_loss INTEGER,
            is_shareholder_reduce INTEGER,
            is_risk_warning INTEGER,
            is_big_order INTEGER,
            is_customer_validation INTEGER,
            affected_funds_json TEXT,
            affected_sectors_json TEXT,
            source TEXT,
            source_url TEXT,
            source_status TEXT,
            raw_text_path TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS intraday_snapshot (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            portfolio_id INTEGER NOT NULL,
            trade_date TEXT NOT NULL,
            decision_time TEXT NOT NULL,
            snapshot_time TEXT,
            source_mode TEXT,
            core_coverage_rate REAL,
            all_coverage_rate REAL,
            data_quality_level TEXT,
            baostock_status TEXT,
            web_status TEXT,
            firecrawl_status TEXT,
            snapshot_json TEXT,
            diagnostics_json TEXT,
            report_path TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(portfolio_id, trade_date, decision_time)
        );

        CREATE TABLE IF NOT EXISTS agent_analysis_result (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_id INTEGER,
            trade_date TEXT,
            decision_time TEXT,
            agent_name TEXT,
            analysis_type TEXT,
            content TEXT,
            summary TEXT,
            risk_notes_json TEXT,
            suggested_actions_json TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS estimate_error (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fund_code TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            estimate_1000_pct REAL,
            estimate_1445_pct REAL,
            actual_pct REAL,
            error_1000 REAL,
            error_1445 REAL,
            abs_error_1000 REAL,
            abs_error_1445 REAL,
            rolling_5_abs_error REAL,
            rolling_20_abs_error REAL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS data_source_run (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT,
            trade_date TEXT,
            decision_time TEXT,
            source_name TEXT,
            source_type TEXT,
            url TEXT,
            fetch_status TEXT,
            status_code INTEGER,
            raw_text_length INTEGER,
            matched_fields_count INTEGER,
            missing_fields_count INTEGER,
            error_reason TEXT,
            raw_text_path TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS fund_enrichment_result (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT,
            fund_code TEXT NOT NULL,
            fund_name TEXT,
            inferred_type TEXT,
            inferred_role TEXT,
            enrich_confidence TEXT,
            manual_review_required INTEGER,
            auto_enriched_json TEXT,
            missing_fields_json TEXT,
            source_summary_json TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS field_source (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT,
            snapshot_id INTEGER,
            entity_type TEXT,
            entity_code TEXT,
            field_name TEXT,
            semantic_field TEXT,
            source TEXT,
            upstream_source TEXT,
            upstream_group TEXT,
            source_level TEXT,
            independent INTEGER,
            source_status TEXT,
            value_text TEXT,
            value_numeric REAL,
            trade_date TEXT,
            data_time TEXT,
            parser_status TEXT,
            confidence REAL,
            error_reason TEXT,
            fix_suggestion TEXT,
            entity_name TEXT,
            final_source TEXT,
            raw_text_path TEXT,
            audit_status TEXT,
            audit_reason TEXT,
            config_file TEXT,
            run_time TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS security_quote_snapshot (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_type TEXT NOT NULL,
            code TEXT NOT NULL,
            name TEXT,
            trade_date TEXT NOT NULL,
            snapshot_time TEXT NOT NULL,
            latest_price REAL,
            change_pct REAL,
            change_amount REAL,
            volume REAL,
            amount REAL,
            turnover_rate REAL,
            high REAL,
            low REAL,
            open REAL,
            previous_close REAL,
            total_market_value REAL,
            float_market_value REAL,
            source TEXT,
            source_status TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(entity_type, code, trade_date, snapshot_time, source)
        );
        """
    )
    _ensure_optional_columns(conn)


def _ensure_optional_columns(conn: sqlite3.Connection) -> None:
    columns = {
        "field_source": {
            "run_id": "TEXT",
            "semantic_field": "TEXT",
            "upstream_source": "TEXT",
            "upstream_group": "TEXT",
            "source_level": "TEXT",
            "independent": "INTEGER",
            "value_numeric": "REAL",
            "trade_date": "TEXT",
            "data_time": "TEXT",
            "parser_status": "TEXT",
            "error_reason": "TEXT",
            "fix_suggestion": "TEXT",
            "entity_name": "TEXT",
            "final_source": "TEXT",
            "raw_text_path": "TEXT",
            "audit_status": "TEXT",
            "audit_reason": "TEXT",
            "config_file": "TEXT",
            "run_time": "TEXT",
        },
        "security_quote_snapshot": {
            "ma5": "REAL",
            "ma10": "REAL",
            "ma20": "REAL",
            "below_ma20": "INTEGER",
            "trend_status": "TEXT",
            "final_source": "TEXT",
            "upstream_group": "TEXT",
            "audit_status": "TEXT",
        },
        "data_source_run": {
            "parser_status": "TEXT",
            "started_at": "TEXT",
            "finished_at": "TEXT",
        }
    }
    for table, table_columns in columns.items():
        existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        for name, ddl in table_columns.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
