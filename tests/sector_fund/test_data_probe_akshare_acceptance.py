from pathlib import Path

from tradingagents.sector_fund.akshare_provider import AKSHARE_META
from tradingagents.sector_fund.data_audit import build_audit_rows
from tradingagents.sector_fund.data_probe import ProbeRecord


def test_akshare_source_group_is_eastmoney_wrapper():
    assert AKSHARE_META["source"] == "akshare"
    assert AKSHARE_META["upstream_group"] == "eastmoney"
    assert AKSHARE_META["source_level"] == "structured_wrapper"
    assert AKSHARE_META["independent"] is False


def test_eastmoney_quote_wins_over_akshare_wrapper_for_intraday_final_source():
    rows = build_audit_rows(
        [
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
        ],
        "run",
        "2026-06-28T15:00:00",
        "config.yaml",
    )

    assert {row["final_source"] for row in rows} == {"eastmoney_push2"}


def test_data_probe_changes_do_not_modify_graph_or_agent_logic():
    graph_source = Path("tradingagents/graph/trading_graph.py").read_text(encoding="utf-8")

    assert "data_probe" not in graph_source
    assert "akshare_provider" not in graph_source
