import sqlite3

from tradingagents.sector_fund.db import initialize_database
from tradingagents.sector_fund.models import SCHEMA_TABLES


def test_sql_schema_creates_expected_tables(tmp_path):
    db_path = tmp_path / "fund_assistant.sqlite3"

    initialize_database(db_path)

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    table_names = {row[0] for row in rows}
    assert set(SCHEMA_TABLES).issubset(table_names)


def test_sql_schema_can_initialize_existing_empty_file(tmp_path):
    db_path = tmp_path / "empty.sqlite3"
    db_path.write_text("", encoding="utf-8")

    initialize_database(db_path)

    with sqlite3.connect(db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
    assert count >= len(SCHEMA_TABLES)
