from __future__ import annotations
import os
from pathlib import Path
from sqlalchemy import create_engine, event, text, inspect
from sqlalchemy.orm import DeclarativeBase, Session

class Base(DeclarativeBase): pass

def default_database_url() -> str:
    path = Path(os.getenv("TRADINGAGENTS_DATA_DIR", Path.home()/".tradingagents"/"data"))
    path.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{path/'market_data.db'}"

def get_engine(url: str | None = None):
    engine = create_engine(url or os.getenv("TRADINGAGENTS_DATABASE_URL") or default_database_url(), future=True)
    @event.listens_for(engine, "connect")
    def _pragma(dbapi_connection, _):
        cur=dbapi_connection.cursor()
        for sql in ("PRAGMA journal_mode=WAL", "PRAGMA busy_timeout=10000", "PRAGMA foreign_keys=ON", "PRAGMA synchronous=NORMAL"): cur.execute(sql)
        cur.close()
    return engine

def init_db(engine=None):
    engine=engine or get_engine()
    from .models import import_models
    import_models()
    Base.metadata.create_all(engine)
    # Lightweight forward migration for the already-created local database.
    with engine.begin() as conn:
        cols = {c["name"] for c in inspect(engine).get_columns("ingestion_run")}
        for name, typ in (("yfinance_version", "VARCHAR(32)"), ("schema_version", "VARCHAR(32)")):
            if name not in cols: conn.execute(text(f"ALTER TABLE ingestion_run ADD COLUMN {name} {typ}"))
        cols = {c["name"] for c in inspect(engine).get_columns("ingestion_run_item")}
        for name, typ in (("inserted_count", "INTEGER DEFAULT 0"), ("skipped_duplicate_count", "INTEGER DEFAULT 0"), ("first_data_time", "VARCHAR(64)"), ("quality_metrics_json", "TEXT")):
            if name not in cols: conn.execute(text(f"ALTER TABLE ingestion_run_item ADD COLUMN {name} {typ}"))
        cols = {c["name"] for c in inspect(engine).get_columns("market_bar_observation")}
        if "market_date" not in cols: conn.execute(text("ALTER TABLE market_bar_observation ADD COLUMN market_date VARCHAR(10)"))
    return engine
