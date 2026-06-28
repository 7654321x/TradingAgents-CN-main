import sys
import types

from tradingagents.sector_fund.akshare_provider import AkShareProvider


class FakeFrame:
    def __init__(self, rows):
        self._rows = rows
        self.empty = not bool(rows)

    def to_dict(self, orient):
        assert orient == "records"
        return self._rows


def test_akshare_fund_estimate_parse(monkeypatch):
    rows = [
        {
            "基金代码": "020671",
            "基金名称": "半导体联接A",
            "2026-06-26-估算数据": "",
            "估算值": "1.2345",
            "估算增长率": "0.80%",
            "公布数据-单位净值": "1.2200",
            "公布数据-日增长率": "0.70%",
        },
        {
            "基金代码": "025500",
            "基金名称": "主动权益",
            "2026-06-26-估算数据": "",
            "估算净值": "0.9000",
            "估算涨跌幅": "0.50%",
            "公布数据-单位净值": "0.8800",
            "公布数据-日增长率": "2.60%",
        },
    ]
    fake = types.SimpleNamespace(fund_value_estimation_em=lambda symbol="全部": FakeFrame(rows))
    monkeypatch.setitem(sys.modules, "akshare", fake)

    result = AkShareProvider().fetch_fund_estimates(
        ["020671", "025500"],
        fund_types={"020671": "etf_feeder", "025500": "active_equity"},
    )

    assert result["020671"]["estimate_nav"] == 1.2345
    assert result["020671"]["estimate_change_pct"] == 0.8
    assert result["020671"]["estimate_time"] == "2026-06-26"
    assert result["020671"]["previous_unit_nav"] == 1.22
    assert result["025500"]["estimate_warning"] is True
    assert result["025500"]["estimate_reliability"] == "low"
    assert result["025500"]["estimate_warning_reason"]
