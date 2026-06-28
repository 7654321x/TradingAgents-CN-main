import json

from tradingagents.sector_fund.score_history import ScoreHistoryStore


def test_score_history_missing_file_is_created(tmp_path):
    path = tmp_path / "score_history.json"
    store = ScoreHistoryStore(path)

    assert store.load() == []
    assert path.exists()
    assert json.loads(path.read_text(encoding="utf-8")) == []


def test_score_history_corruption_is_backed_up_and_rebuilt(tmp_path):
    path = tmp_path / "score_history.json"
    path.write_text("not-json", encoding="utf-8")
    store = ScoreHistoryStore(path)

    assert store.load() == []
    assert path.with_suffix(path.suffix + ".bak").exists()
    assert json.loads(path.read_text(encoding="utf-8")) == []


def test_score_history_repeated_same_day_updates_one_row(tmp_path):
    store = ScoreHistoryStore(tmp_path / "score_history.json")
    store.upsert({"date": "2026-06-28", "source_mode": "mock", "report_path": "a.md", "semiconductor_score": 1})
    store.upsert({"date": "2026-06-28", "source_mode": "real_data", "report_path": "b.md", "semiconductor_score": 2})

    rows = store.load()
    assert len(rows) == 1
    assert rows[0]["source_mode"] == "real_data"
    assert rows[0]["report_path"] == "b.md"
    assert rows[0]["semiconductor_score"] == 2
