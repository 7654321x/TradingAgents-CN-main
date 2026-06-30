def test_holding_stock_history_uses_batch_session(monkeypatch):
    import tradingagents.sector_fund.holding_stock_data as module

    calls = {"batch": 0}

    class FakeProvider:
        def fetch_latest_daily_snapshots_batch(self, codes, lookback_days=40, purpose=""):
            calls["batch"] += 1
            return {
                code: {
                    "code": code,
                    "rows": [{"close": 1}],
                    "indicator": {"ma20": 1.0},
                    "latest_trade_date": "2026-06-29",
                    "source_status": "success",
                }
                for code in codes
            }

    monkeypatch.setattr(module, "BaostockProvider", FakeProvider)

    result = module.fetch_holding_stock_history(["603986", "688012"])

    assert calls["batch"] == 1
    assert result["603986"]["final_source"] == "baostock"
    assert result["688012"]["indicator"]["ma20"] == 1.0
