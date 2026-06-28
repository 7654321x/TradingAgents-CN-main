from tradingagents.sector_fund.akshare_provider import _date_like, _estimate_date


def test_akshare_estimate_date_parse_from_column_name():
    row = {"2026-06-26-估算数据": "", "估算值": "1.1"}

    assert _estimate_date(row) == "2026-06-26"


def test_akshare_date_like_normalizes_slashes():
    assert _date_like("2026/6/8 00:00:00") == "2026-06-08"
