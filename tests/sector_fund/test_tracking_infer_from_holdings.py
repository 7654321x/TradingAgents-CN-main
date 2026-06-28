from tradingagents.sector_fund.fund_tracking_infer import infer_tracking


def test_tracking_infer_from_holdings_for_active_fund():
    holdings = [
        {"holding_stock_code": "603986", "holding_stock_name": "兆易创新"},
        {"holding_stock_code": "300476", "holding_stock_name": "胜宏科技"},
    ]

    tracking = infer_tracking("active_equity", "东方阿尔法科技智选混合C", holdings=holdings)

    assert tracking["stocks"][0]["code"] == "603986"
    assert tracking["tracking_source"] == "akshare_holdings"
    assert tracking["holding_is_stale"] is True


def test_etf_feeder_tracking_suggestion_from_name():
    tracking = infer_tracking("etf_feeder", "易方达科创芯片ETF联接C")

    assert {"code": "588200", "source": "name_keyword_suggestion", "confidence": "medium_low"} in tracking["etfs"]
    assert {"name": "科创50", "source": "name_keyword_suggestion", "confidence": "medium_low"} in tracking["indices"]
