import sys
import types


def test_baostock_batch_login_once(monkeypatch):
    from tradingagents.sector_fund.baostock_provider import BaostockProvider

    calls = {"login": 0, "logout": 0}

    class LoginResult:
        error_code = "0"
        error_msg = ""

    def fake_login():
        calls["login"] += 1
        print("login success!")
        return LoginResult()

    def fake_logout():
        calls["logout"] += 1
        print("logout success!")

    fake = types.SimpleNamespace(login=fake_login, logout=fake_logout)
    monkeypatch.setitem(sys.modules, "baostock", fake)
    monkeypatch.setattr(BaostockProvider, "fetch_latest_daily_snapshot", lambda self, code, lookback_days=40: {"code": code, "rows": [], "source_status": "missing"})

    result = BaostockProvider().fetch_latest_daily_snapshots_batch(["603986", "688012", "688525"], purpose="holding_stock_history")

    assert calls["login"] == 1
    assert calls["logout"] == 1
    assert set(result) == {"603986", "688012", "688525"}
