from tradingagents.sector_fund.data_audit import cross_validate_quotes
from tradingagents.sector_fund.data_probe import ProbeRecord


def _records(eastmoney_price=1.004, eastmoney_pct=1.2):
    return [
        ProbeRecord(
            source_name="baostock",
            source_type="baostock_daily_k",
            category="Baostock 日K",
            entity_type="etf",
            entity_code="512480",
            data={"latest_close": 1.0, "pct_chg": 1.0},
        ),
        ProbeRecord(
            source_name="eastmoney",
            source_type="eastmoney_push2_quote",
            category="东方财富盘中行情",
            entity_type="etf",
            entity_code="512480",
            data={"latest_price": eastmoney_price, "change_pct": eastmoney_pct},
        ),
    ]


def test_cross_validate_ok_after_hours_small_diff():
    rows = cross_validate_quotes(_records(), intraday=False)

    assert {row["audit_status"] for row in rows} == {"ok"}
    assert all("difference_pct" in row for row in rows)


def test_cross_validate_suspect_after_hours_medium_diff():
    rows = cross_validate_quotes(_records(eastmoney_price=1.01), intraday=False)

    assert any(row["audit_status"] == "suspect" for row in rows)


def test_cross_validate_daily_vs_intraday():
    rows = cross_validate_quotes(_records(eastmoney_price=1.2), run_time="2026-06-26T10:00:00")

    assert {row["audit_status"] for row in rows} == {"daily_vs_intraday"}
    assert all("Baostock 为日K" in row["audit_reason"] for row in rows)

