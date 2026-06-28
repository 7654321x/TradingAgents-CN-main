from tradingagents.sector_fund.score_history import ScoreHistoryStore, build_score_record


def test_score_history_writes_and_updates_same_day(tmp_path):
    path = tmp_path / "score_history.json"
    store = ScoreHistoryStore(path)
    record = build_score_record(
        analysis_date="2026-06-25",
        score={
            "semiconductor_score": 70,
            "storage_score": 72,
            "trend_score": 10,
            "flow_score": 11,
            "leader_score": 12,
            "announcement_score": 1,
            "emotion_score": 2,
            "market_score": 3,
            "risk_level": "中",
            "suggestion": "持有观察。",
        },
        data_quality={"real_coverage_rate": 55.0, "data_quality_level": "中等"},
        source_mode="mock",
        report_path="reports/a.md",
    )

    store.upsert(record)
    updated = dict(record)
    updated["semiconductor_score"] = 75
    updated["report_path"] = "reports/b.md"
    store.upsert(updated)

    rows = store.load()
    assert len(rows) == 1
    assert rows[0]["semiconductor_score"] == 75
    assert rows[0]["source_mode"] == "mock"
    assert rows[0]["report_path"] == "reports/b.md"


def test_score_history_reads_recent_days_sorted(tmp_path):
    store = ScoreHistoryStore(tmp_path / "score_history.json")
    for index in range(6):
        store.upsert({"date": f"2026-06-{20 + index:02d}", "semiconductor_score": index, "storage_score": index + 10})

    recent = store.recent(3)

    assert [row["date"] for row in recent] == ["2026-06-23", "2026-06-24", "2026-06-25"]
    assert [row["storage_score"] for row in recent] == [13, 14, 15]
