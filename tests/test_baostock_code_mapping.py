from tradingagents.sector_fund.baostock_provider import to_baostock_code


def test_to_baostock_code_maps_common_a_share_and_etf_codes():
    assert to_baostock_code("688012") == "sh.688012"
    assert to_baostock_code("603986") == "sh.603986"
    assert to_baostock_code("512480") == "sh.512480"
    assert to_baostock_code("159995") == "sz.159995"
    assert to_baostock_code("300750") == "sz.300750"


def test_to_baostock_code_keeps_existing_prefix():
    assert to_baostock_code("SH.688012") == "sh.688012"
    assert to_baostock_code("sz.159995") == "sz.159995"
