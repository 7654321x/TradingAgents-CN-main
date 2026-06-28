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


def test_akshare_fund_holdings_parse(monkeypatch):
    rows = [
        {"季度": "2025年4季度股票投资明细", "序号": "1", "股票代码": "688981", "股票名称": "中芯国际", "占净值比例": "8.5%"},
        {"季度": "2025年4季度股票投资明细", "序号": "2", "股票代码": "002371", "股票名称": "北方华创", "占净值比例": "7.1%"},
    ]
    fake = types.SimpleNamespace(fund_portfolio_hold_em=lambda symbol, date: FakeFrame(rows))
    monkeypatch.setitem(sys.modules, "akshare", fake)

    result = AkShareProvider().fetch_fund_holdings(["020671"])

    assert result["020671"]["source_status"] == "success"
    assert result["020671"]["holding_is_stale"] is True
    assert result["020671"]["top_holdings"][0]["holding_stock_code"] == "688981"
    assert result["020671"]["top_holdings"][0]["holding_weight_pct"] == 8.5
