import sys
import types

from tradingagents.sector_fund.akshare_provider import AkShareProvider


def test_akshare_provider_available_metadata(monkeypatch):
    fake = types.SimpleNamespace(__version__="test-version")
    monkeypatch.setitem(sys.modules, "akshare", fake)

    status = AkShareProvider().check_available()

    assert status["source_status"] == "success"
    assert status["source"] == "akshare"
    assert status["upstream_group"] == "eastmoney"
    assert status["source_level"] == "structured_wrapper"
    assert status["independent"] is False
