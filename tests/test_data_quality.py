def test_data_quality_counts_sources():
    from tradingagents.sector_fund.data_quality import calculate_data_quality

    field_sources = {
        "a": "real_data",
        "b": "firecrawl_raw",
        "c": "mock_fallback",
        "d": "missing",
        "e": "insufficient_history",
    }

    quality = calculate_data_quality(field_sources)

    assert quality["real_field_count"] == 2
    assert quality["mock_field_count"] == 1
    assert quality["missing_field_count"] == 2
    assert quality["real_coverage_rate"] == 40.0
    assert quality["data_quality_level"] == "中等"


def test_data_quality_low_coverage_warning_in_report():
    from tradingagents.sector_fund.mock_data import build_mock_sector_fund_context
    from tradingagents.sector_fund.report import render_sector_fund_report
    from tradingagents.sector_fund.scoring import score_sector_fund_context

    context = build_mock_sector_fund_context("config/personal_semiconductor.yaml", analysis_date="2026-06-27")
    context.data_quality = {
        "real_field_count": 0,
        "mock_field_count": 10,
        "missing_field_count": 5,
        "real_coverage_rate": 0.0,
        "data_quality_level": "较低",
    }

    report = render_sector_fund_report(context, score_sector_fund_context(context))

    assert "【数据可信度】" in report
    assert "真实解析字段：0" in report
    assert "真实覆盖率：0.00%" in report
    assert "当前真实结构化字段覆盖率较低" in report


def test_data_quality_high_level():
    from tradingagents.sector_fund.data_quality import calculate_data_quality

    field_sources = {f"real_{index}": "real_data" for index in range(7)}
    field_sources.update({f"mock_{index}": "mock_fallback" for index in range(3)})

    quality = calculate_data_quality(field_sources)

    assert quality["real_coverage_rate"] == 70.0
    assert quality["data_quality_level"] == "较好"
