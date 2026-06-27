import json
from pathlib import Path
from typing import Dict, Optional


class HistoryStore:
    def __init__(self, path: str | Path = "data/sector_fund_history.json"):
        self.path = Path(path)
        self.data = self._load()

    def _load(self) -> Dict[str, Dict[str, float]]:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")

    def record_price(self, code: str, trade_date: str, price: float) -> None:
        if price is None:
            return
        rows = self.data.setdefault(code, {})
        rows[trade_date] = float(price)
        self._save()

    def _prices(self, code: str) -> list[float]:
        rows = self.data.get(code, {})
        return [rows[key] for key in sorted(rows)]

    def calculate_moving_averages(self, code: str) -> Dict[str, Optional[float] | str]:
        prices = self._prices(code)
        result: Dict[str, Optional[float] | str] = {
            "ma5": None,
            "ma10": None,
            "ma20": None,
            "status": "insufficient_history",
        }
        for window, field in ((5, "ma5"), (10, "ma10"), (20, "ma20")):
            if len(prices) >= window:
                result[field] = round(sum(prices[-window:]) / window, 4)
        if all(result[field] is not None for field in ("ma5", "ma10", "ma20")):
            result["status"] = "ok"
        return result

    def calculate_ma_state(self, code: str, price: float) -> Dict[str, Optional[bool] | Optional[float] | str]:
        ma = self.calculate_moving_averages(code)
        state: Dict[str, Optional[bool] | Optional[float] | str] = dict(ma)
        for field in ("pullback_ma5", "pullback_ma10", "below_ma10", "below_ma20"):
            state[field] = None
        if price is None or ma["status"] != "ok":
            return state

        ma5 = ma["ma5"]
        ma10 = ma["ma10"]
        ma20 = ma["ma20"]
        state["pullback_ma5"] = ma5 is not None and price >= ma5 and abs(price - ma5) / ma5 <= 0.015
        state["pullback_ma10"] = ma10 is not None and price >= ma10 and abs(price - ma10) / ma10 <= 0.02
        state["below_ma10"] = ma10 is not None and price < ma10
        state["below_ma20"] = ma20 is not None and price < ma20
        return state

