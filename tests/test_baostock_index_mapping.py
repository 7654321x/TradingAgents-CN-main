import sys
import types

from tradingagents.sector_fund.baostock_provider import (
    INDEX_CODE_CANDIDATES,
    BaostockProvider,
    to_baostock_code,
)


class LoginResult:
    error_code = "0"
    error_msg = ""


class QueryResult:
    error_code = "0"
    error_msg = ""
    fields = ["date", "code", "open", "high", "low", "close", "preclose", "volume", "amount", "turn", "pctChg", "tradestatus"]

    def __init__(self, code, has_rows):
        self.index = -1
        self.rows = []
        if has_rows:
            self.rows = [
                ["2026-06-01", code, "1", "1", "1", str(i), str(i - 1), "100", "1000", "1", "1", "1"]
                for i in range(1, 21)
            ]

    def next(self):
        self.index += 1
        return self.index < len(self.rows)

    def get_row_data(self):
        return self.rows[self.index]


def test_star50_maps_to_candidate_codes():
    assert to_baostock_code("科创50") == "sh.000688"
    assert INDEX_CODE_CANDIDATES["科创50"] == ["sh.000688", "sh.000689"]


def test_star50_uses_first_candidate_with_rows(monkeypatch):
    queried = []

    def fake_query(code, *args, **kwargs):
        queried.append(code)
        return QueryResult(code, has_rows=code == "sh.000689")

    fake = types.SimpleNamespace(login=lambda: LoginResult(), logout=lambda: None, query_history_k_data_plus=fake_query)
    monkeypatch.setitem(sys.modules, "baostock", fake)

    snapshot = BaostockProvider().fetch_latest_daily_snapshot("科创50")

    assert queried[:2] == ["sh.000688", "sh.000689"]
    assert snapshot["rows_count"] == 20
    assert snapshot["baostock_code"] == "sh.000689"
    assert snapshot["source_status"] == "success"


def test_star50_all_candidates_empty_has_clear_reason(monkeypatch):
    fake = types.SimpleNamespace(
        login=lambda: LoginResult(),
        logout=lambda: None,
        query_history_k_data_plus=lambda code, *args, **kwargs: QueryResult(code, has_rows=False),
    )
    monkeypatch.setitem(sys.modules, "baostock", fake)

    snapshot = BaostockProvider().fetch_latest_daily_snapshot("科创50")

    assert snapshot["rows_count"] == 0
    assert snapshot["source_status"] == "missing"
    assert snapshot["error_reason"] == "baostock returned no rows"
