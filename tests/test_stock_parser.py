def test_stock_parser_extracts_quote_fields():
    from tradingagents.sector_fund.parsers import parse_stock_quote_text

    text = """
    688012 中微公司
    最新价 188.80 涨跌幅 +4.20% 成交额 32.5亿元 换手率 3.40%
    主力净流入 2.6亿元 今开 181.00 最高 196.00 最低 180.00 收盘 188.80 昨收 181.20
    """

    parsed = parse_stock_quote_text("688012", "中微公司", "设备链", text)

    assert parsed["change_pct"] == 4.2
    assert parsed["turnover_billion"] == 32.5
    assert parsed["turnover_rate"] == 3.4
    assert parsed["main_inflow_billion"] == 2.6
    assert parsed["open"] == 181.0
    assert parsed["high"] == 196.0
    assert parsed["low"] == 180.0
    assert parsed["close"] == 188.8
    assert parsed["previous_close"] == 181.2


def test_long_upper_shadow_detection():
    from tradingagents.sector_fund.parsers import has_long_upper_shadow

    assert has_long_upper_shadow(open_price=10.0, high=11.8, low=9.8, close=10.5) is True
    assert has_long_upper_shadow(open_price=10.0, high=10.8, low=9.8, close=10.5) is False
    assert has_long_upper_shadow(open_price=None, high=10.8, low=9.8, close=10.5) is None


def test_intraday_fade_detection():
    from tradingagents.sector_fund.parsers import is_intraday_fade

    assert is_intraday_fade(high=105.0, close=101.0, previous_close=100.0) is True
    assert is_intraday_fade(high=102.0, close=101.0, previous_close=100.0) is False
    assert is_intraday_fade(high=None, close=101.0, previous_close=100.0) is None


def test_stock_parser_missing_fields_does_not_crash():
    from tradingagents.sector_fund.parsers import parse_stock_quote_text

    parsed = parse_stock_quote_text("688012", "中微公司", "设备链", "暂无行情")

    assert parsed["code"] == "688012"
    assert parsed["name"] == "中微公司"
    assert parsed["theme"] == "设备链"
    assert "change_pct" not in parsed


def test_real_stock_text_overrides_mock(monkeypatch, tmp_path):
    from tradingagents.sector_fund.domestic_web_provider import DomesticWebProvider, DomesticWebResult
    from tradingagents.sector_fund.runner import run_sector_fund_analysis

    def fake_fetch_raw_pages(self, urls=None, use_firecrawl=False):
        return DomesticWebResult(
            raw_text={
                "stock_eastmoney_688012": "688012 中微公司 最新价 188.80 涨跌幅 +4.20% 成交额 32.5亿元 换手率 3.40% 主力净流入 2.6亿元 今开 181.00 最高 196.00 最低 180.00 收盘 188.80 昨收 181.20"
            },
            source_status={"stock_eastmoney_688012": "success"},
        )

    monkeypatch.setattr(DomesticWebProvider, "fetch_raw_pages", fake_fetch_raw_pages)

    result = run_sector_fund_analysis(
        use_mock=False,
        analysis_date="2026-06-27",
        output_dir=tmp_path,
        history_path=tmp_path / "history.json",
    )
    stock = next(item for item in result["context"].stocks if item.code == "688012")

    assert stock.change_pct == 4.2
    assert stock.turnover_billion == 32.5
    assert stock.main_inflow_billion == 2.6
    assert stock.intraday_pullback is True
    assert result["context"].field_sources["stock.688012.change_pct"] == "real_data"
