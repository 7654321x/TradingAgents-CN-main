import json
from pathlib import Path
from typing import Any, Dict, List, Optional


RISK_LEVEL_ORDER = {"低": 1, "中": 2, "中高": 3, "高": 4}
QUALITY_LEVEL_ORDER = {"较低": 1, "中等": 2, "较好": 3}


class ScoreHistoryStore:
    def __init__(self, path: str | Path = "data/sector_fund_score_history.json"):
        self.path = Path(path)

    def _write_empty(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("[]", encoding="utf-8")

    def _backup_corrupt_file(self) -> None:
        if not self.path.exists():
            return
        backup_path = self.path.with_suffix(self.path.suffix + ".bak")
        try:
            backup_path.write_text(self.path.read_text(encoding="utf-8"), encoding="utf-8")
        except Exception:
            pass

    def load(self) -> List[Dict[str, Any]]:
        if not self.path.exists():
            self._write_empty()
            return []
        raw = self.path.read_text(encoding="utf-8").strip()
        if not raw:
            self._write_empty()
            return []
        try:
            data = json.loads(raw)
        except Exception:
            self._backup_corrupt_file()
            self._write_empty()
            return []
        if not isinstance(data, list):
            self._backup_corrupt_file()
            self._write_empty()
            return []
        return sorted((row for row in data if isinstance(row, dict) and row.get("date")), key=lambda row: row.get("date", ""))

    def upsert(self, record: Dict[str, Any]) -> None:
        if not record.get("date"):
            return
        rows = [row for row in self.load() if row.get("date") != record["date"]]
        rows.append(dict(record))
        rows.sort(key=lambda row: row.get("date", ""))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

    def recent(self, days: int = 5) -> List[Dict[str, Any]]:
        days = max(1, int(days or 5))
        return self.load()[-days:]


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def build_score_record(
    analysis_date: str,
    score: Dict[str, Any],
    data_quality: Dict[str, Any],
    source_mode: str,
    report_path: str,
) -> Dict[str, Any]:
    semiconductor_score = _num(score.get("semiconductor_score"))
    storage_score = _num(score.get("storage_score"))
    total_score = score.get("total_score")
    if total_score is None:
        total_score = round((semiconductor_score + storage_score) / 2, 2)
    return {
        "date": analysis_date,
        "semiconductor_score": int(round(semiconductor_score)),
        "storage_score": int(round(storage_score)),
        "trend_score": round(_num(score.get("trend_score")), 2),
        "flow_score": round(_num(score.get("flow_score")), 2),
        "leader_score": round(_num(score.get("leader_score")), 2),
        "announcement_score": round(_num(score.get("announcement_score")), 2),
        "emotion_score": round(_num(score.get("emotion_score")), 2),
        "market_score": round(_num(score.get("market_score")), 2),
        "total_score": round(_num(total_score), 2),
        "risk_level": score.get("risk_level", ""),
        "suggestion": score.get("suggestion", ""),
        "real_coverage_rate": round(_num(data_quality.get("real_coverage_rate")), 2),
        "data_quality_level": data_quality.get("data_quality_level", ""),
        "source_mode": source_mode,
        "report_path": str(report_path),
    }


def _previous_row(history: List[Dict[str, Any]], today: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    today_date = today.get("date", "")
    previous = [row for row in history if row.get("date", "") < today_date]
    return previous[-1] if previous else None


def _delta(today: Dict[str, Any], previous: Optional[Dict[str, Any]], field: str) -> Optional[float]:
    if not previous:
        return None
    return round(_num(today.get(field)) - _num(previous.get(field)), 2)


def _recent_with_today(history: List[Dict[str, Any]], today: Dict[str, Any], days: int) -> List[Dict[str, Any]]:
    rows = [row for row in history if row.get("date") != today.get("date")] + [today]
    rows.sort(key=lambda row: row.get("date", ""))
    return rows[-max(1, int(days or 5)) :]


def _is_strict(values: List[float], direction: str) -> bool:
    if len(values) < 3:
        return False
    pairs = zip(values, values[1:])
    if direction == "up":
        return all(b > a for a, b in pairs)
    return all(b < a for a, b in pairs)


def analyze_signal_changes(history: List[Dict[str, Any]], today: Dict[str, Any], history_days: int = 5) -> Dict[str, Any]:
    history = sorted(history, key=lambda row: row.get("date", ""))
    previous = _previous_row(history, today)
    sem_delta = _delta(today, previous, "semiconductor_score")
    storage_delta = _delta(today, previous, "storage_score")
    avg_delta = ((sem_delta or 0) + (storage_delta or 0)) / 2 if previous else 0

    if not previous:
        trend_signal = "稳定"
        risk_change = "无可比历史"
        data_quality_change = "无可比历史"
        tags = ["stable"]
    else:
        if avg_delta >= 3:
            trend_signal = "增强"
            tags = ["improving"]
        elif avg_delta <= -3:
            trend_signal = "转弱"
            tags = ["weakening"]
        else:
            trend_signal = "稳定"
            tags = ["stable"]

        risk_change = "风险上升" if RISK_LEVEL_ORDER.get(today.get("risk_level"), 0) > RISK_LEVEL_ORDER.get(previous.get("risk_level"), 0) else "基本稳定"
        if risk_change == "风险上升" and "risk_up" not in tags:
            tags.append("risk_up")

        quality_now = QUALITY_LEVEL_ORDER.get(today.get("data_quality_level"), 0)
        quality_prev = QUALITY_LEVEL_ORDER.get(previous.get("data_quality_level"), 0)
        coverage_delta = _num(today.get("real_coverage_rate")) - _num(previous.get("real_coverage_rate"))
        data_quality_change = "数据质量下降" if quality_now < quality_prev or coverage_delta < -10 else "基本稳定"
        if data_quality_change == "数据质量下降" and "data_unreliable" not in tags:
            tags.append("data_unreliable")

    flow_score = _num(today.get("flow_score"))
    leader_score = _num(today.get("leader_score"))
    announcement_score = _num(today.get("announcement_score"))
    fund_flow_signal = "数据不足" if today.get("flow_score") is None else "明显流出" if flow_score < 0 else "开始分歧" if flow_score < 5 else "继续流入"
    leader_signal = "风险增加" if leader_score < 3 else "分化" if leader_score < 8 else "强势"
    announcement_risk = "新增利空" if announcement_score < 0 else "新增利好" if announcement_score > 0 else "无明显变化"

    previous_suggestion = previous.get("suggestion", "") if previous else ""
    today_suggestion = today.get("suggestion", "") or ""
    operation_change = "无明显变化"
    if "小加" in previous_suggestion and "小加" not in today_suggestion:
        operation_change = "从积极跟踪转为观察"
    elif "持有" in previous_suggestion and any(word in today_suggestion for word in ("降低", "减仓", "控制")):
        operation_change = "从持有转为减仓观察"

    recent = _recent_with_today(history, today, history_days)
    recent_semiconductor = [row.get("semiconductor_score") for row in recent]
    recent_storage = [row.get("storage_score") for row in recent]
    recent_coverage = [row.get("real_coverage_rate") for row in recent]
    totals = [_num(row.get("total_score")) for row in recent[-3:]]

    return {
        "previous": previous,
        "semiconductor_delta": sem_delta,
        "storage_delta": storage_delta,
        "risk_change": risk_change,
        "data_quality_change": data_quality_change,
        "trend_signal": trend_signal,
        "fund_flow_signal": fund_flow_signal,
        "leader_signal": leader_signal,
        "announcement_risk": announcement_risk,
        "operation_change": operation_change,
        "change_tags": tags,
        "recent_records": recent,
        "recent_semiconductor_scores": recent_semiconductor,
        "recent_storage_scores": recent_storage,
        "recent_real_coverage_rates": recent_coverage,
        "continuous_weakening": _is_strict(totals, "down"),
        "continuous_improving": _is_strict(totals, "up"),
    }
