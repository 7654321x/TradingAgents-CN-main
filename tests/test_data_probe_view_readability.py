from tradingagents.sector_fund.data_audit import render_terminal_summary


def test_terminal_summary_contains_readable_sections():
    rows = [
        {
            "entity_type": "etf",
            "entity_code": "512480",
            "entity_name": "半导体ETF",
            "field_name": "baostock.etf.512480.latest_close",
            "value": 2.7,
            "source": "baostock_daily_k",
            "source_status": "success",
            "audit_status": "ok",
        },
        {
            "entity_type": "index",
            "entity_code": "科创50",
            "entity_name": "科创50",
            "field_name": "baostock.index.科创50.kline",
            "value": "",
            "source": "baostock_daily_k",
            "source_status": "empty",
            "audit_status": "missing",
            "audit_reason": "all candidate index codes returned no rows",
            "fix_suggestion": "请检查 Baostock 是否支持该指数或改用东方财富指数行情作为主源。",
        },
    ]

    output = render_terminal_summary(rows, {"core_coverage_rate": 80, "all_coverage_rate": 70})

    assert "【覆盖率】" in output
    assert "【Baostock ETF】" in output
    assert "【Baostock 指数】" in output
    assert "【失败字段】" in output
    assert "科创50" in output
    assert "all candidate index codes returned no rows" in output

