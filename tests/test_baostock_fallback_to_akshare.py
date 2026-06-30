def test_baostock_fallback_to_akshare(monkeypatch):
    import tradingagents.sector_fund.holding_stock_data as module

    class FakeProvider:
        def fetch_latest_daily_snapshots_batch(self, codes, lookback_days=40, purpose=""):
            return {code: {"code": code, "rows": [], "source_status": "login_failed", "error_reason": "bad login"} for code in codes}

    monkeypatch.setattr(module, "BaostockProvider", FakeProvider)
    monkeypatch.setattr(
        module,
        "_fetch_akshare_history",
        lambda code, lookback_days=40: {
            "code": code,
            "rows": [{"close": 2}],
            "indicator": {"ma20": 2.0},
            "trade_date": "2026-06-29",
            "source": "akshare",
            "final_source": "akshare",
            "source_status": "success",
            "parser_status": "success",
        },
    )

    result = module.fetch_holding_stock_history(["603986"])

    assert result["603986"]["final_source"] == "akshare"
    assert result["603986"]["indicator"]["ma20"] == 2.0
