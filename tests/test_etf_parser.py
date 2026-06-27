def test_etf_parser_extracts_quote_fields():
    from tradingagents.sector_fund.parsers import parse_etf_quote_text

    text = """
    512480 半导体ETF
    最新价 0.948 涨跌幅 +1.40% 成交额 24.6亿元
    换手率 6.80% 溢价率 0.08% 近5日涨幅 5.40%
    """

    parsed = parse_etf_quote_text("512480", "半导体ETF", text)

    assert parsed["latest_price"] == 0.948
    assert parsed["change_pct"] == 1.4
    assert parsed["turnover_billion"] == 24.6
    assert parsed["turnover_rate"] == 6.8
    assert parsed["premium_rate_pct"] == 0.08
    assert parsed["five_day_change_pct"] == 5.4


def test_history_store_returns_insufficient_history(tmp_path):
    from tradingagents.sector_fund.history_store import HistoryStore

    store = HistoryStore(tmp_path / "history.json")
    store.record_price("512480", "2026-06-27", 0.948)

    result = store.calculate_moving_averages("512480")

    assert result["ma5"] is None
    assert result["ma10"] is None
    assert result["ma20"] is None
    assert result["status"] == "insufficient_history"


def test_history_store_calculates_ma_and_pullback(tmp_path):
    from tradingagents.sector_fund.history_store import HistoryStore

    store = HistoryStore(tmp_path / "history.json")
    for day in range(1, 21):
        store.record_price("512480", f"2026-06-{day:02d}", 1.00 + day * 0.01)
    store.record_price("512480", "2026-06-27", 1.205)

    result = store.calculate_moving_averages("512480")
    state = store.calculate_ma_state("512480", 1.205)

    assert result["ma5"] == 1.189
    assert result["ma10"] == 1.1645
    assert result["ma20"] == 1.1148
    assert state["pullback_ma5"] is True
    assert state["pullback_ma10"] is False
    assert state["below_ma10"] is False
    assert state["below_ma20"] is False


def test_etf_missing_ma_is_marked_insufficient_history(monkeypatch, tmp_path):
    from tradingagents.sector_fund.domestic_web_provider import DomesticWebProvider, DomesticWebResult
    from tradingagents.sector_fund.runner import run_sector_fund_analysis

    def fake_fetch_raw_pages(self, urls=None, use_firecrawl=False):
        return DomesticWebResult(
            raw_text={"etf_eastmoney_512480": "512480 半导体ETF 最新价 0.948 涨跌幅 +1.40% 成交额 24.6亿元"},
            source_status={"etf_eastmoney_512480": "success"},
        )

    monkeypatch.setattr(DomesticWebProvider, "fetch_raw_pages", fake_fetch_raw_pages)

    result = run_sector_fund_analysis(
        use_mock=False,
        analysis_date="2026-06-27",
        output_dir=tmp_path / "reports",
        history_path=tmp_path / "history.json",
    )
    context = result["context"]
    etf = next(item for item in context.etfs if item.code == "512480")

    assert etf.latest_price == 0.948
    assert etf.ma5 is None
    assert context.field_sources["etf.512480.latest_price"] == "real_data"
    assert context.field_sources["etf.512480.ma5"] == "insufficient_history"
    assert "历史数据不足，无法判断" in result["report"]


def test_etf_raw_text_without_price_keeps_mock_ma(monkeypatch, tmp_path):
    from tradingagents.sector_fund.domestic_web_provider import DomesticWebProvider, DomesticWebResult
    from tradingagents.sector_fund.runner import run_sector_fund_analysis

    def fake_fetch_raw_pages(self, urls=None, use_firecrawl=False):
        return DomesticWebResult(
            raw_text={"etf_eastmoney_512480": "512480 半导体ETF 暂无可解析行情"},
            source_status={"etf_eastmoney_512480": "success"},
        )

    monkeypatch.setattr(DomesticWebProvider, "fetch_raw_pages", fake_fetch_raw_pages)

    result = run_sector_fund_analysis(
        use_mock=False,
        analysis_date="2026-06-27",
        output_dir=tmp_path / "reports",
        history_path=tmp_path / "history.json",
    )

    assert result["context"].field_sources["etf.512480.latest_price"] == "mock_fallback"
    assert result["context"].field_sources["etf.512480.ma5"] == "mock_fallback"
