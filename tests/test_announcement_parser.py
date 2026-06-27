from tradingagents.sector_fund.parsers import parse_announcement_text


def test_announcement_parser_detects_positive_and_negative_events():
    text = """
    2026-06-26 688525 佰维存储 关于股东减持计划的公告 风险提示
    公司股东拟减持不超过1%，同时提示股价异动风险。
    2026-06-26 688012 中微公司 2026年半年度业绩预增公告
    公司预计净利润同比增长，并获得客户验证通过，订单增长。
    2026-06-26 301308 江波龙 业绩预亏公告
    """

    anns = parse_announcement_text(text, watch_stocks={"688525": "佰维存储", "688012": "中微公司", "301308": "江波龙"})

    reduce_ann = next(item for item in anns if item["stock_code"] == "688525")
    up_ann = next(item for item in anns if item["stock_code"] == "688012")
    loss_ann = next(item for item in anns if item["stock_code"] == "301308")
    assert reduce_ann["is_shareholder_reduce"] is True
    assert reduce_ann["is_risk_warning"] is True
    assert reduce_ann["sentiment"] == "利空"
    assert up_ann["is_earnings_increase"] is True
    assert up_ann["is_customer_validation"] is True
    assert up_ann["is_big_order"] is True
    assert up_ann["sentiment"] == "利好"
    assert loss_ann["is_earnings_loss"] is True
    assert loss_ann["sentiment"] == "利空"
