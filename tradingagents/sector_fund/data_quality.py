from typing import Dict


REAL_SOURCES = {"real_data", "firecrawl_raw"}
MOCK_SOURCES = {"mock_fallback"}
MISSING_SOURCES = {"missing", "insufficient_history"}


def calculate_data_quality(field_sources: Dict[str, str]) -> Dict[str, float | int | str]:
    values = [value for value in field_sources.values() if value in REAL_SOURCES | MOCK_SOURCES | MISSING_SOURCES]
    real_count = sum(1 for value in values if value in REAL_SOURCES)
    mock_count = sum(1 for value in values if value in MOCK_SOURCES)
    missing_count = sum(1 for value in values if value in MISSING_SOURCES)
    total = real_count + mock_count + missing_count
    coverage = round((real_count / total * 100) if total else 0.0, 2)

    if coverage >= 70:
        level = "较好"
    elif coverage >= 40:
        level = "中等"
    else:
        level = "较低"

    return {
        "real_field_count": real_count,
        "mock_field_count": mock_count,
        "missing_field_count": missing_count,
        "real_coverage_rate": coverage,
        "data_quality_level": level,
    }
