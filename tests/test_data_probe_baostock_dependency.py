import sys
import types

from tradingagents.sector_fund.baostock_provider import BaostockProvider, to_baostock_code


def test_baostock_missing_does_not_crash(monkeypatch):
    monkeypatch.setitem(sys.modules, "baostock", None)

    snapshot = BaostockProvider().fetch_latest_daily_snapshot("512480")

    assert snapshot["source_status"] == "dependency_missing"
    assert snapshot["rows"] == []
    assert "baostock import failed" in snapshot["error_reason"]


def test_baostock_mocked_daily_k_calculates_ma(monkeypatch):
    class LoginResult:
        error_code = "0"
        error_msg = ""

    class QueryResult:
        error_code = "0"
        error_msg = ""
        fields = ["date", "code", "open", "high", "low", "close", "preclose", "volume", "amount", "turn", "pctChg", "tradestatus"]

        def __init__(self):
            self.index = -1
            self.rows = [
                ["2026-06-01", "sh.512480", "1", "1", "1", str(i), str(i - 1), "100", "1000", "1", "1", "1"]
                for i in range(1, 21)
            ]

        def next(self):
            self.index += 1
            return self.index < len(self.rows)

        def get_row_data(self):
            return self.rows[self.index]

    fake = types.SimpleNamespace(
        login=lambda: LoginResult(),
        logout=lambda: None,
        query_history_k_data_plus=lambda *args, **kwargs: QueryResult(),
    )
    monkeypatch.setitem(sys.modules, "baostock", fake)

    snapshot = BaostockProvider().fetch_latest_daily_snapshot("512480")

    assert snapshot["source_status"] == "success"
    assert snapshot["rows_count"] == 20
    assert snapshot["latest_close"] == 20
    assert snapshot["ma5"] == 18
    assert snapshot["ma10"] == 15.5
    assert snapshot["ma20"] == 10.5


def test_to_baostock_code_supports_indices():
    assert to_baostock_code("科创50") == "sh.000688"
    assert to_baostock_code("创业板指") == "sz.399006"
