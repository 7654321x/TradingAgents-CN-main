from tradingagents.sector_fund.data_audit import audit_field


def _record(field, value, rows=20, missing=False):
    return {
        "fetch_status": "success",
        "parser_status": "success",
        "matched_fields": [] if missing else [field],
        "missing_fields": [field] if missing else [],
        "entity_type": "index",
        "entity_code": "科创50",
        "source_type": "baostock_daily_k",
        "error_reason": "baostock returned no rows" if rows == 0 else "",
        "data": {field: value, "rows": rows},
    }


def test_rows_zero_is_missing_with_baostock_suggestion():
    field = "baostock.index.科创50.kline"
    status, reason, suggestion = audit_field(_record(field, None, rows=0, missing=True), field, None)

    assert status == "missing"
    assert "baostock returned no rows" in reason
    assert suggestion == "use eastmoney index quote as primary source"


def test_pct_chg_over_twenty_is_suspect_for_baostock():
    field = "baostock.index.创业板指.pct_chg"
    status, reason, _ = audit_field(_record(field, 25), field, 25)

    assert status == "suspect"
    assert "+/-20%" in reason


def test_ma_thresholds_use_each_window():
    ma5 = "baostock.index.创业板指.ma5"
    ma10 = "baostock.index.创业板指.ma10"
    ma20 = "baostock.index.创业板指.ma20"

    assert audit_field(_record(ma5, None, rows=5, missing=True), ma5, None)[0] == "suspect"
    assert audit_field(_record(ma10, None, rows=10, missing=True), ma10, None)[0] == "suspect"
    assert audit_field(_record(ma20, None, rows=20, missing=True), ma20, None)[0] == "suspect"
    assert audit_field(_record(ma20, None, rows=10, missing=True), ma20, None)[0] == "missing"
