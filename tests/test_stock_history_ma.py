from tradingagents.sector_fund.history_store import HistoryStore


def test_stock_history_returns_insufficient_history_before_five_days(tmp_path):
    store = HistoryStore(tmp_path / "history.json")
    for day, close in enumerate([10.0, 10.2, 10.4, 10.6], start=1):
        store.record_stock_quote("688012", f"2026-06-{day:02d}", {"close": close})

    state = store.calculate_stock_ma_state("688012", 10.6)

    assert state["ma5"] is None
    assert state["ma10"] is None
    assert state["ma5_status"] == "insufficient_history"
    assert state["ma10_status"] == "insufficient_history"
    assert state["below_ma5"] is None
    assert state["below_ma10"] is None


def test_stock_history_calculates_ma5_and_ma10(tmp_path):
    store = HistoryStore(tmp_path / "history.json")
    closes = [10, 11, 12, 13, 14, 15, 16, 17, 18, 19]
    for day, close in enumerate(closes, start=1):
        store.record_stock_quote(
            "688012",
            f"2026-06-{day:02d}",
            {
                "stock_name": "中微公司",
                "open": close - 0.2,
                "high": close + 0.5,
                "low": close - 0.5,
                "close": close,
                "previous_close": close - 1,
                "pct_chg": 1.0,
                "amount": 1.2,
                "turnover": 3.4,
            },
        )

    state = store.calculate_stock_ma_state("688012", 16.0)

    assert state["ma5"] == 17.0
    assert state["ma10"] == 14.5
    assert state["ma5_status"] == "ok"
    assert state["ma10_status"] == "ok"
    assert state["below_ma5"] is True
    assert state["below_ma10"] is False
