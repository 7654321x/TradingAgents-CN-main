from tradingagents.sector_fund.data_audit import build_audit_rows
from tradingagents.sector_fund.data_probe import ProbeRecord


def test_final_source_prefers_eastmoney_for_intraday_quotes_over_akshare():
    records = [
            ProbeRecord(
                source_name="akshare_etf_512480",
                source_type="akshare_etf_spot",
                category="AKShare ETF行情",
                entity_type="etf",
            entity_code="512480",
            matched_fields=["akshare.etf.512480.latest_price"],
            data={"latest_price": 1.1, "source": "akshare", "source_status": "success"},
        ),
            ProbeRecord(
                source_name="eastmoney_etf_512480",
                source_type="eastmoney_push2_quote",
                category="东方财富盘中行情",
                entity_type="etf",
            entity_code="512480",
            matched_fields=["eastmoney.etf.512480.latest_price"],
            data={"latest_price": 1.11, "source": "eastmoney_push2", "source_status": "success"},
        ),
    ]

    rows = build_audit_rows(records, "run", "2026-06-28T15:00:00", "config.yaml")

    assert {row["final_source"] for row in rows} == {"eastmoney_push2"}


def test_final_source_prefers_tiantian_for_estimate_and_akshare_for_holdings():
    records = [
            ProbeRecord(
                source_name="akshare_020671",
                source_type="akshare_fund_estimate",
                category="AKShare 基金估算",
                entity_type="fund",
            entity_code="020671",
            matched_fields=["akshare.fund.020671.estimate_nav", "akshare.fund.020671.top_holdings"],
            data={"estimate_nav": 1.2, "top_holdings": [{"holding_stock_code": "688981"}], "source": "akshare", "source_status": "success"},
        ),
            ProbeRecord(
                source_name="tiantian_020671",
                source_type="tiantian_fund_estimate",
                category="天天基金基金估算",
                entity_type="fund",
            entity_code="020671",
            matched_fields=["fund.020671.estimate_nav"],
            data={"estimate_nav": 1.21, "source": "tiantianfund_direct", "source_status": "success"},
        ),
    ]

    rows = build_audit_rows(records, "run", "2026-06-28T15:00:00", "config.yaml")
    by_field = {row["field_name"]: row["final_source"] for row in rows}

    assert by_field["akshare.fund.020671.estimate_nav"] == "tiantianfund_direct"
    assert by_field["akshare.fund.020671.top_holdings"] == "akshare"
