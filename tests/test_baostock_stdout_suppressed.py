import sys
import types


def test_baostock_stdout_suppressed(monkeypatch, capsys):
    from tradingagents.sector_fund.baostock_provider import BaostockProvider

    class LoginResult:
        error_code = "0"
        error_msg = ""

    fake = types.SimpleNamespace(
        login=lambda: (print("login success!") or LoginResult()),
        logout=lambda: print("logout success!"),
    )
    monkeypatch.setitem(sys.modules, "baostock", fake)

    provider = BaostockProvider()
    assert provider.login() == "success"
    assert provider.logout() == "success"

    output = capsys.readouterr().out
    assert "login success!" not in output
    assert "logout success!" not in output
    assert "login success!" in provider.native_stdout
    assert "logout success!" in provider.native_stdout
