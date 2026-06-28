from datetime import date, timedelta

from tradingagents.sector_fund.baostock_provider import calculate_indicators


def _row(i: int, close: float) -> dict:
    day = date(2026, 1, 1) + timedelta(days=i)
    return {
        "code": "512480",
        "baostock_code": "sh.512480",
        "trade_date": day.isoformat(),
        "open": close - 0.02,
        "high": close + 0.03,
        "low": close - 0.04,
        "close": close,
        "preclose": close - 0.01,
        "pct_chg": 1.0,
        "amount": 2_000_000_000,
        "turnover_rate": 3.5,
    }


def test_calculate_indicators_from_mocked_baostock_rows():
    rows = [_row(i, 1 + i * 0.01) for i in range(20)]

    indicator = calculate_indicators(rows)

    assert indicator["code"] == "512480"
    assert indicator["latest_price"] == 1.19
    assert indicator["ma5"] is not None
    assert indicator["ma10"] is not None
    assert indicator["ma20"] is not None
    assert indicator["turnover_billion"] == 20.0
    assert indicator["field_sources"]["ma5"] == "baostock"


def test_calculate_indicators_marks_insufficient_ma_history():
    indicator = calculate_indicators([_row(0, 1.0), _row(1, 1.01)])

    assert indicator["ma5"] is None
    assert indicator["field_sources"]["ma5"] == "insufficient_history"
    assert indicator["below_ma5"] is None
