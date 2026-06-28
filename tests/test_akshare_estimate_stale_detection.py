import sys
import types

from tradingagents.sector_fund.akshare_provider import AkShareProvider


class FakeFrame:
    empty = False

    def to_dict(self, orient):
        assert orient == "records"
        return [
            {
                "基金代码": "020671",
                "2000-01-01-估算数据": "",
                "估算值": "1.0000",
                "估算增长率": "0.10%",
            }
        ]


def test_akshare_estimate_stale_detection(monkeypatch):
    fake = types.SimpleNamespace(fund_value_estimation_em=lambda symbol="全部": FakeFrame())
    monkeypatch.setitem(sys.modules, "akshare", fake)

    result = AkShareProvider().fetch_fund_estimates(["020671"])

    assert result["020671"]["is_stale"] is True
