from tradingagents.sector_fund.akshare_provider import _percent


def test_akshare_percent_parse_handles_percent_and_empty_values():
    assert _percent("1.23%") == 1.23
    assert _percent("-0.50") == -0.5
    assert _percent("--") is None
