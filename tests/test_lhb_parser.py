from tradingagents.sector_fund.parsers import parse_lhb_text


def test_lhb_parser_extracts_institution_hot_money_and_net_buy():
    text = """
    688525 佰维存储 龙虎榜 上榜原因 日涨幅偏离值达7%
    机构专用净买入 1.20亿元，知名游资净买入 3500万元。
    买入前五合计 3.40亿元，卖出前五合计 2.10亿元，净买入 1.30亿元。
    """

    parsed = parse_lhb_text("688525", "佰维存储", text)

    assert parsed["is_on_lhb"] is True
    assert parsed["institution_net_buy"] == 1.2
    assert parsed["hot_money_net_buy"] == 0.35
    assert parsed["buy_top5_amount"] == 3.4
    assert parsed["sell_top5_amount"] == 2.1
    assert parsed["net_buy_amount"] == 1.3
    assert parsed["lhb_reason"] == "日涨幅偏离值达7%"
    assert parsed["sentiment_tag"] == "机构+游资净买入"


def test_lhb_parser_returns_empty_when_stock_missing():
    parsed = parse_lhb_text("688012", "中微公司", "603986 兆易创新 龙虎榜 机构净买入 1亿元")

    assert parsed == {}
