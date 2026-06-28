import sys
import types

from tradingagents.sector_fund.baostock_provider import BaostockProvider
from tradingagents.sector_fund.data_audit import build_audit_rows, render_summary_markdown
from tradingagents.sector_fund.data_probe import ProbeRecord


class LoginResult:
    error_code = "0"
    error_msg = ""


class EmptyKResult:
    error_code = "0"
    error_msg = ""
    fields = ["date", "code", "open", "high", "low", "close", "preclose", "volume", "amount", "turn", "pctChg", "tradestatus"]

    def next(self):
        return False


class AllStockResult:
    error_code = "0"
    error_msg = ""
    fields = ["code", "tradeStatus", "code_name"]

    def __init__(self):
        self.index = -1
        self.rows = [["sh.000688", "1", "科创50"]]

    def next(self):
        self.index += 1
        return self.index < len(self.rows)

    def get_row_data(self):
        return self.rows[self.index]


def test_baostock_support_probe_uses_query_all_stock(monkeypatch):
    fake = types.SimpleNamespace(
        login=lambda: LoginResult(),
        logout=lambda: None,
        query_history_k_data_plus=lambda *args, **kwargs: EmptyKResult(),
        query_all_stock=lambda **kwargs: AllStockResult(),
    )
    monkeypatch.setitem(sys.modules, "baostock", fake)

    snapshot = BaostockProvider().fetch_latest_daily_snapshot("科创50")

    assert snapshot["source_status"] == "missing"
    assert snapshot["error_reason"] == "baostock returned no rows"
    assert snapshot["support_probe"]["status"] == "success"
    assert snapshot["support_probe"]["is_supported"] is True
    assert snapshot["support_probe"]["supported_codes"] == ["sh.000688"]


def test_summary_shows_final_adopted_source_eastmoney():
    records = [
        ProbeRecord(
            source_name="baostock_index_科创50",
            source_type="baostock_daily_k",
            category="Baostock 日K",
            entity_type="index",
            entity_code="科创50",
            entity_name="科创50",
            fetch_status="missing",
            parser_status="no_data",
            missing_fields=["baostock.index.科创50.latest_close"],
            error_reason="baostock returned no rows",
            data={"source_status": "missing", "rows": 0},
        ),
        ProbeRecord(
            source_name="eastmoney_quote_index_科创50",
            source_type="eastmoney_push2_quote",
            category="东方财富盘中行情",
            entity_type="index",
            entity_code="科创50",
            entity_name="科创50",
            fetch_status="success",
            parser_status="success",
            matched_fields=["eastmoney.index.科创50.latest_price", "eastmoney.index.科创50.change_pct", "eastmoney.index.科创50.source_status"],
            data={"latest_price": 1234.5, "change_pct": 1.2, "source_status": "success"},
        ),
    ]
    rows = build_audit_rows(records, "run", "2026-06-28T16:00:00", "config.yaml")
    report = render_summary_markdown(rows, {"core_coverage_rate": 100, "all_coverage_rate": 50, "all_matched_count": 3}, [])

    assert "最终采用数据源" in report
    assert "| 科创50 | 科创50 |" in report
    assert "eastmoney" in report

