from tradingagents.sector_fund.data_audit import cross_validate_quotes
from tradingagents.sector_fund.data_probe import ProbeRecord


def _records(baostock_price=1.0, eastmoney_price=1.002, baostock_pct=1.0, eastmoney_pct=1.2):
    return [
        ProbeRecord(
            source_name="baostock",
            source_type="baostock_daily_k",
            category="Baostock 日K",
            entity_type="etf",
            entity_code="512480",
            data={"latest_close": baostock_price, "pct_chg": baostock_pct},
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


def test_cross_validate_quotes_ok_when_close_after_hours():
    rows = cross_validate_quotes(_records(), intraday=False)
    assert {row["audit_status"] for row in rows} == {"ok"}


def test_cross_validate_quotes_suspect_when_large_after_hours_diff():
    rows = cross_validate_quotes(_records(eastmoney_price=1.2), intraday=False)
    assert any(row["audit_status"] == "suspect" for row in rows)


def test_cross_validate_quotes_marks_daily_vs_intraday():
    rows = cross_validate_quotes(_records(eastmoney_price=1.2), intraday=True)
    assert {row["audit_status"] for row in rows} == {"daily_vs_intraday"}
