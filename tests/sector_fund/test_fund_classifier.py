from tradingagents.sector_fund.fund_classifier import classify_fund


def test_fund_classifier_detects_common_types():
    assert classify_fund("易方达科创芯片ETF联接C")["fund_type"] == "etf_feeder"
    assert classify_fund("中证半导体指数A")["fund_type"] == "index_fund"
    assert classify_fund("东方阿尔法科技智选混合C")["fund_type"] == "sector_theme"
    assert classify_fund("某某债券A")["fund_type"] == "bond_fund"
    assert classify_fund("现金货币A")["fund_type"] == "money_fund"


def test_fund_classifier_unknown_requires_review():
    result = classify_fund("看不出来基金")

    assert result["fund_type"] == "unknown"
    assert result["manual_review_required"] is True
