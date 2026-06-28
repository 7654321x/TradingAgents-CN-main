from tradingagents.sector_fund.fund_context_formatter import decision_time_prompt, quality_prompt


def test_quality_gate_prompt_limits_low_coverage_conclusions():
    text = quality_prompt(12.3)

    assert "低于40%" in text
    assert "不要给出积极加仓或减仓建议" in text
    assert "人工核对" in text


def test_decision_time_prompt_is_context_not_strategy_engine():
    morning = decision_time_prompt("1000")
    afternoon = decision_time_prompt("1445")
    night = decision_time_prompt("night")

    assert "不要给出强买卖结论" in morning
    assert "交由原Agent分析" in afternoon
    assert "净值校准" in night
