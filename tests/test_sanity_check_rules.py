from tradingagents.sector_fund.data_audit import audit_field


def _record(field, value, entity_type="stock", entity_code="000001", rows=20):
    return {
        "fetch_status": "success",
        "parser_status": "success",
        "matched_fields": [field],
        "missing_fields": [],
        "entity_type": entity_type,
        "entity_code": entity_code,
        "source_type": "test",
        "data": {field: value, "rows": rows},
    }


def test_close_less_equal_zero_is_suspect():
    field = "eastmoney.stock.000001.latest_price"
    status, reason, _ = audit_field(_record(field, 0), field, 0)
    assert status == "suspect"
    assert "price must be > 0" in reason


def test_pct_change_over_twenty_is_suspect():
    field = "eastmoney.stock.000001.change_pct"
    status, reason, _ = audit_field(_record(field, 25), field, 25)
    assert status == "suspect"
    assert "+/-20%" in reason


def test_rows_over_twenty_with_missing_ma20_is_suspect():
    field = "baostock.etf.512480.ma20"
    record = _record(field, None, entity_type="etf", entity_code="512480", rows=20)
    record["matched_fields"] = []
    record["missing_fields"] = [field]
    status, reason, _ = audit_field(record, field, None)
    assert status == "suspect"
    assert "rows=20" in reason


def test_star50_rows_zero_has_mapping_suggestion():
    field = "baostock.index.科创50.kline"
    record = _record(field, None, entity_type="index", entity_code="科创50", rows=0)
    record["matched_fields"] = []
    record["missing_fields"] = [field]
    status, reason, suggestion = audit_field(record, field, None)
    assert status == "missing"
    assert "baostock returned no rows" in reason
    assert suggestion == "use eastmoney index quote as primary source"
