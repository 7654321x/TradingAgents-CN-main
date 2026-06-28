from tradingagents.sector_fund.score_history import analyze_signal_changes


def test_signal_change_compares_today_with_previous_day():
    history = [
        {
            "date": "2026-06-26",
            "semiconductor_score": 60,
            "storage_score": 65,
            "risk_level": "中",
            "real_coverage_rate": 80.0,
            "data_quality_level": "较好",
            "flow_score": 5,
            "leader_score": 6,
            "announcement_score": 1,
            "suggestion": "已有仓位持有，可等回踩小加。",
        },
        {
            "date": "2026-06-27",
            "semiconductor_score": 54,
            "storage_score": 58,
            "risk_level": "高",
            "real_coverage_rate": 35.0,
            "data_quality_level": "较低",
            "flow_score": -1,
            "leader_score": 1,
            "announcement_score": -4,
            "suggestion": "观察为主。",
        },
    ]

    result = analyze_signal_changes(history, history[-1])

    assert result["semiconductor_delta"] == -6
    assert result["storage_delta"] == -7
    assert result["risk_change"] == "风险上升"
    assert result["data_quality_change"] == "数据质量下降"
    assert result["trend_signal"] == "转弱"
    assert result["change_tags"] == ["weakening", "risk_up", "data_unreliable"]
    assert result["operation_change"] == "从积极跟踪转为观察"


def test_signal_change_marks_stable_when_no_previous_history():
    today = {"date": "2026-06-27", "semiconductor_score": 70, "storage_score": 72, "risk_level": "中"}

    result = analyze_signal_changes([], today)

    assert result["trend_signal"] == "稳定"
    assert result["risk_change"] == "无可比历史"
    assert result["change_tags"] == ["stable"]
