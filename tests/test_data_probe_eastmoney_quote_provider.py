from tradingagents.sector_fund.eastmoney_quote_provider import EastMoneyQuoteProvider, to_eastmoney_secid


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_eastmoney_quote_provider_parses_structured_quotes(monkeypatch):
    def fake_get(url, **kwargs):
        assert "push2.eastmoney.com" in url
        return FakeResponse(
            {
                "data": {
                    "diff": [
                        {
                            "f12": "512480",
                            "f14": "半导体ETF",
                            "f2": 1.23,
                            "f3": 2.5,
                            "f17": 1.2,
                            "f15": 1.25,
                            "f16": 1.18,
                            "f18": 1.2,
                            "f6": 123456789,
                            "f8": 3.4,
                        }
                    ]
                }
            }
        )

    monkeypatch.setattr("tradingagents.sector_fund.eastmoney_quote_provider.requests.get", fake_get)

    quotes = EastMoneyQuoteProvider().fetch_quotes(["512480"])

    assert quotes["512480"]["latest_price"] == 1.23
    assert quotes["512480"]["change_pct"] == 2.5
    assert quotes["512480"]["amount"] == 123456789
    assert quotes["512480"]["source_status"] == "success"


def test_to_eastmoney_secid_supports_indices_and_etfs():
    assert to_eastmoney_secid("512480") == "1.512480"
    assert to_eastmoney_secid("159995") == "0.159995"
    assert to_eastmoney_secid("科创50") == "1.000688"
