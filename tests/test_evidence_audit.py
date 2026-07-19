from __future__ import annotations

from pathlib import Path

from tradingagents.analysis.evidence_audit import EvidenceAuditService
from tradingagents.reports.stock_decision_report import save_evidence_audit_failure


def package():
    def record(value, unit="percent", status="SUCCESS"):
        return {"value": value, "unit": unit, "status": status, "source": "database", "price_basis": "adjusted", "data_cutoff": "2026-07-17"}

    return {
        "symbol": "001309.SZ",
        "analysis_date": "2026-07-17",
        "news": {"status": "SUCCESS_NO_DATA"},
        "fundamentals": {"status": "FUNDAMENTALS_UNAVAILABLE"},
        "evidence_index": {
            "market.returns.return_20d_pct": record(-12.34),
            "market.returns.return_60d_pct": record(4.2),
            "market.trend_strength.adx14": record(31.4, "index"),
            "market.trend_strength.minus_di14": record(35.0, "index"),
            "fundamentals.status": record("FUNDAMENTALS_UNAVAILABLE", "enum"),
            "news.status": record("SUCCESS_NO_DATA", "enum"),
        },
    }


def output(text="中期收益路径偏弱", refs=None, field="primary_reasons"):
    return {field: [{"text": text, "evidence_refs": refs or ["market.returns.return_20d_pct"]}]}


def rules(result):
    return {item["rule"] for item in result["violations"]}


def test_trader_requires_evidence_refs():
    result = EvidenceAuditService().audit(package(), {"primary_reasons": [{"text": "缺少引用", "evidence_refs": []}]})
    assert "MISSING_EVIDENCE_REFS" in rules(result)


def test_risk_review_requires_evidence_refs():
    result = EvidenceAuditService().audit(package(), {}, {"adjustment_reasons": [{"text": "缺少引用"}]})
    assert "MISSING_EVIDENCE_REFS" in rules(result)


def test_unknown_evidence_ref_is_rejected():
    result = EvidenceAuditService().audit(package(), output(refs=["market.unknown.field"]))
    assert "UNKNOWN_EVIDENCE_REF" in rules(result)


def test_missing_evidence_is_not_neutral():
    result = EvidenceAuditService().audit(package(), output("新闻中性", ["news.status"]))
    assert "NEWS_NO_DATA_MISINTERPRETED" in rules(result)


def test_numeric_sign_change_is_rejected():
    result = EvidenceAuditService().audit(package(), output("20日收益为 12.34%"))
    assert "NUMERIC_VALUE_MISMATCH" in rules(result)


def test_numeric_rounding_is_accepted():
    result = EvidenceAuditService().audit(package(), output("20日收益为 -12.34%"))
    assert result["status"] == "PASSED"


def test_ordinary_float_mismatch_is_rejected():
    result = EvidenceAuditService().audit(package(), output("模型写入 0.55", ["market.returns.return_20d_pct"]))
    assert "NUMERIC_VALUE_MISMATCH" in rules(result)


def test_percentage_unit_mismatch_is_rejected():
    result = EvidenceAuditService().audit(package(), output("ADX为 31.40%", ["market.trend_strength.adx14"]))
    assert "PERCENTAGE_UNIT_MISMATCH" in rules(result)


def test_news_no_data_cannot_be_called_neutral():
    result = EvidenceAuditService().audit(package(), output("没有重大事件", ["news.status"]))
    assert "NEWS_NO_DATA_MISINTERPRETED" in rules(result)


def test_fundamentals_unavailable_cannot_be_positive():
    result = EvidenceAuditService().audit(package(), output("公司盈利良好", ["fundamentals.status"]))
    assert "FUNDAMENTALS_UNAVAILABLE_MISINTERPRETED" in rules(result)


def test_fundamentals_mention_requires_status_ref():
    result = EvidenceAuditService().audit(package(), output("基本面尚未确认", ["market.returns.return_20d_pct"]))
    assert "MISSING_FUNDAMENTALS_STATUS_REF" in rules(result)


def test_adx_bullish_misinterpretation_is_rejected():
    result = EvidenceAuditService().audit(package(), output("ADX确认看涨", ["market.trend_strength.adx14"]))
    assert "ADX_DIRECTION_MISINTERPRETED" in rules(result)


def test_adx_with_directional_evidence_is_allowed():
    result = EvidenceAuditService().audit(package(), output("趋势偏强但方向由收益确认", ["market.trend_strength.adx14", "market.returns.return_60d_pct"]))
    assert "ADX_DIRECTION_MISINTERPRETED" not in rules(result)


def test_content_audit_failure_does_not_overwrite_report(tmp_path: Path):
    report = tmp_path / "decision_report.md"
    report.write_text("previous passed report", encoding="utf-8")
    failure = save_evidence_audit_failure(tmp_path, {"status": "CONTENT_AUDIT_FAILED"})
    assert report.read_text(encoding="utf-8") == "previous passed report"
    assert failure.exists()
