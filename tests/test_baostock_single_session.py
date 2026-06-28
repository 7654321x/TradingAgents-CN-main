import sys
import types

from tradingagents.sector_fund.data_probe import _probe_baostock


class LoginResult:
    error_code = "0"
    error_msg = ""


class QueryResult:
    error_code = "0"
    error_msg = ""
    fields = ["date", "code", "open", "high", "low", "close", "preclose", "volume", "amount", "turn", "pctChg", "tradestatus"]

    def __init__(self, code):
        self.index = -1
        self.rows = [
            ["2026-06-01", code, "1", "1", "1", str(i), str(i - 1), "100", "1000", "1", "1", "1"]
            for i in range(1, 21)
        ]

    def next(self):
        self.index += 1
        return self.index < len(self.rows)

    def get_row_data(self):
        return self.rows[self.index]


def test_baostock_probe_logs_in_once_for_batch(monkeypatch, tmp_path):
    calls = {"login": 0, "logout": 0}

    def fake_login():
        calls["login"] += 1
        return LoginResult()

    def fake_logout():
        calls["logout"] += 1

    fake = types.SimpleNamespace(
        login=fake_login,
        logout=fake_logout,
        query_history_k_data_plus=lambda code, *args, **kwargs: QueryResult(code),
    )
    monkeypatch.setitem(sys.modules, "baostock", fake)

    records = _probe_baostock(
        {
            "etfs": [{"code": "512480", "name": "半导体ETF"}, {"code": "159995", "name": "芯片ETF"}],
            "stocks": [{"code": "688981", "name": "中芯国际"}],
            "indices": ["创业板指"],
        },
        tmp_path,
    )

    assert calls == {"login": 1, "logout": 1}
    assert len(records) == 4
    assert all(record.data["login_count"] == 1 for record in records)
    assert all(record.data["logout_count"] == 1 for record in records)
    assert all(record.data["success_symbols"] == 4 for record in records)

