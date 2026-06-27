def test_parse_chinese_amount_to_billion():
    from tradingagents.sector_fund.parsers import parse_chinese_amount_to_billion

    assert parse_chinese_amount_to_billion("12.5亿元") == 12.5
    assert parse_chinese_amount_to_billion("+8,500万") == 0.85
    assert parse_chinese_amount_to_billion("-1.2万亿") == -12000.0
    assert parse_chinese_amount_to_billion("未获取到") is None


def test_parse_percent_value():
    from tradingagents.sector_fund.parsers import parse_percent_value

    assert parse_percent_value("+3.21%") == 3.21
    assert parse_percent_value("-0.58 %") == -0.58
    assert parse_percent_value("涨幅 1.20") == 1.2
    assert parse_percent_value("--") is None


def test_parse_fund_nav_text():
    from tradingagents.sector_fund.parsers import parse_fund_nav_text

    text = """
    020671 易方达科创芯片ETF联接C
    单位净值 1.2345 日增长率 +1.23%
    近1周 3.45% 近1月 -2.10% 近3月 12.30% 今年以来 20.50%
    基金规模 18.60亿元 基金经理 张三
    """

    fund = parse_fund_nav_text("020671", text)

    assert fund["unit_nav"] == 1.2345
    assert fund["daily_change_pct"] == 1.23
    assert fund["week_change_pct"] == 3.45
    assert fund["month_change_pct"] == -2.1
    assert fund["three_month_change_pct"] == 12.3
    assert fund["ytd_change_pct"] == 20.5
    assert fund["size_billion"] == 18.6
    assert fund["manager"] == "张三"


def test_parse_fund_holdings_text():
    from tradingagents.sector_fund.parsers import parse_fund_holdings_text

    text = """
    序号 股票名称 持仓占比
    1 佰维存储 9.88%
    2 江波龙 8.12%
    3 兆易创新 6.00%
    """

    holdings = parse_fund_holdings_text(text)

    assert holdings["top_holdings"] == ["佰维存储", "江波龙", "兆易创新"]
    assert holdings["top_holdings_weight_pct"] == 24.0


def test_parse_fund_flow_text():
    from tradingagents.sector_fund.parsers import parse_fund_flow_text

    text = """
    行业 主力净流入 涨跌幅
    半导体 42.5亿元 +1.80%
    存储芯片 28.4亿元 +2.60%
    电子行业 55.1亿元 +0.90%
    芯片概念 37.8亿元 +1.20%
    """

    parsed = parse_fund_flow_text(text)

    assert parsed["fund_flow"]["semiconductor_main_inflow_billion"] == 42.5
    assert parsed["fund_flow"]["storage_main_inflow_billion"] == 28.4
    assert parsed["fund_flow"]["electronics_main_inflow_billion"] == 55.1
    assert parsed["fund_flow"]["chip_main_inflow_billion"] == 37.8
    assert parsed["sectors"]["半导体"]["change_pct"] == 1.8
    assert parsed["sectors"]["存储芯片"]["change_pct"] == 2.6


def test_real_data_missing_still_generates_report(monkeypatch, tmp_path):
    from tradingagents.sector_fund.domestic_web_provider import DomesticWebProvider
    from tradingagents.sector_fund.runner import run_sector_fund_analysis

    def fake_fetch_raw_pages(self, urls=None, use_firecrawl=False):
        from tradingagents.sector_fund.domestic_web_provider import DomesticWebResult

        return DomesticWebResult(
            raw_text={"eastmoney_sector_fund_flow": ""},
            source_status={"eastmoney_sector_fund_flow": "failed"},
        )

    monkeypatch.setattr(DomesticWebProvider, "fetch_raw_pages", fake_fetch_raw_pages)

    result = run_sector_fund_analysis(
        use_mock=False,
        analysis_date="2026-06-27",
        output_dir=tmp_path,
    )

    assert result["output_path"].exists()
    assert "mock_fallback" in result["report"]
    assert "missing" in result["report"]
    assert result["context"].field_sources["fund_flow.semiconductor_main_inflow_billion"] == "mock_fallback"
    assert result["context"].source_status["eastmoney_sector_fund_flow"] == "failed"


def test_real_data_text_overrides_mock_fields(monkeypatch, tmp_path):
    from tradingagents.sector_fund.domestic_web_provider import DomesticWebProvider, DomesticWebResult
    from tradingagents.sector_fund.runner import run_sector_fund_analysis

    def fake_fetch_raw_pages(self, urls=None, use_firecrawl=False):
        return DomesticWebResult(
            raw_text={
                "eastmoney_sector_fund_flow": "半导体 66.6亿元 +3.30%\n存储芯片 12.3亿元 +4.40%",
                "fund_020671": "单位净值 1.9999 日增长率 +2.22% 近1周 5.50% 基金规模 20.00亿元 基金经理 李四",
                "fund_020671_holdings": "1 佰维存储 10.00%\n2 江波龙 9.00%",
            },
            source_status={
                "eastmoney_sector_fund_flow": "success",
                "fund_020671": "success",
                "fund_020671_holdings": "success",
            },
        )

    monkeypatch.setattr(DomesticWebProvider, "fetch_raw_pages", fake_fetch_raw_pages)

    result = run_sector_fund_analysis(
        use_mock=False,
        use_firecrawl=False,
        analysis_date="2026-06-27",
        output_dir=tmp_path,
    )
    context = result["context"]
    fund_020671 = next(fund for fund in context.funds if fund.code == "020671")
    semiconductor = next(sector for sector in context.sectors if sector.name == "半导体")

    assert context.fund_flow.semiconductor_main_inflow_billion == 66.6
    assert semiconductor.change_pct == 3.3
    assert fund_020671.unit_nav == 1.9999
    assert fund_020671.manager == "李四"
    assert fund_020671.top_holdings == ["佰维存储", "江波龙"]
    assert context.field_sources["fund_flow.semiconductor_main_inflow_billion"] == "real_data"
    assert context.field_sources["fund.020671.unit_nav"] == "real_data"
    assert "fund_flow.semiconductor_main_inflow_billion: real_data" in result["report"]
