import json
from pathlib import Path
from typing import Any, Dict, Optional


class HistoryStore:
    def __init__(self, path: str | Path = "data/sector_fund_history.json"):
        self.path = Path(path)
        self.data = self._load()

    def _load(self) -> Dict[str, Dict[str, Any]]:
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

    def record_stock_quote(self, code: str, trade_date: str, quote: Dict[str, Any]) -> None:
        close = quote.get("close")
        if close is None:
            return
        rows = self.data.setdefault(code, {})
        rows[trade_date] = {
            "stock_name": quote.get("stock_name") or quote.get("name") or "",
            "date": trade_date,
            "open": quote.get("open"),
            "high": quote.get("high"),
            "low": quote.get("low"),
            "close": float(close),
            "previous_close": quote.get("previous_close"),
            "pct_chg": quote.get("pct_chg"),
            "amount": quote.get("amount"),
            "turnover": quote.get("turnover"),
        }
        self._save()

    def _row_close(self, row: Any) -> Optional[float]:
        if isinstance(row, dict):
            row = row.get("close")
        try:
            return float(row)
        except (TypeError, ValueError):
            return None

    def _prices(self, code: str) -> list[float]:
        rows = self.data.get(code, {})
        prices = []
        for key in sorted(rows):
            close = self._row_close(rows[key])
            if close is not None:
                prices.append(close)
        return prices

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

    def calculate_stock_ma_state(self, code: str, close: float) -> Dict[str, Optional[bool] | Optional[float] | str]:
        prices = self._prices(code)
        ma5 = round(sum(prices[-5:]) / 5, 4) if len(prices) >= 5 else None
        ma10 = round(sum(prices[-10:]) / 10, 4) if len(prices) >= 10 else None
        result: Dict[str, Optional[bool] | Optional[float] | str] = {
            "ma5": ma5,
            "ma10": ma10,
            "ma5_status": "ok" if ma5 is not None else "insufficient_history",
            "ma10_status": "ok" if ma10 is not None else "insufficient_history",
            "below_ma5": None,
            "below_ma10": None,
        }
        if close is None:
            return result
        if ma5 is not None:
            result["below_ma5"] = close < ma5
        if ma10 is not None:
            result["below_ma10"] = close < ma10
        return result
