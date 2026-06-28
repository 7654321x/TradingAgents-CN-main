from tradingagents.sector_fund.eastmoney_quote_provider import EastMoneyQuoteProvider


class FakeResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {
            "data": {
                "diff": [
                    {"f12": "BK1111", "f14": "印制电路板", "f3": 1.2, "f6": 100, "f62": 10},
                    {"f12": "BK2222", "f14": "存储器", "f3": -0.8, "f6": 200, "f62": 20},
                    {"f12": "BK3333", "f14": "半导体", "f3": 0.5, "f6": 300, "f62": 30},
                ]
            }
        }


def test_sector_alias_matching_hits_pcb_and_storage(monkeypatch):
    monkeypatch.setattr("tradingagents.sector_fund.eastmoney_quote_provider.requests.get", lambda *args, **kwargs: FakeResponse())

    sectors = EastMoneyQuoteProvider().fetch_sector_changes(["PCB", "存储芯片", "科创芯片"])

    assert sectors["PCB"]["name"] == "印制电路板"
    assert sectors["PCB"]["match_method"] == "matched_by_alias:印制电路板"
    assert sectors["存储芯片"]["name"] == "存储器"
    assert sectors["存储芯片"]["match_method"] == "matched_by_alias:存储器"
    assert sectors["科创芯片"]["match_confidence"] == "low"

