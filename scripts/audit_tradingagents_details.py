from __future__ import annotations

import csv
import sys
import time
from datetime import date, timedelta
from pathlib import Path

# Support the documented direct invocation: python scripts/audit_tradingagents_details.py
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tradingagents.dataflows.config import set_config
from tradingagents.dataflows.interface import route_to_vendor
from tradingagents.default_config import DEFAULT_CONFIG

TICKERS = ["600519.SS", "601318.SS", "600036.SS", "688981.SS", "000001.SZ", "002594.SZ", "300750.SZ", "300308.SZ"]
METHODS = [
    ("get_fundamentals", lambda ticker, today: (ticker, today)),
    ("get_balance_sheet", lambda ticker, today: (ticker, "quarterly", today)),
    ("get_cashflow", lambda ticker, today: (ticker, "quarterly", today)),
    ("get_income_statement", lambda ticker, today: (ticker, "quarterly", today)),
    ("get_insider_transactions", lambda ticker, today: (ticker,)),
    ("get_news", lambda ticker, today: (ticker, (date.fromisoformat(today) - timedelta(days=7)).isoformat(), today)),
]
INDICATORS = ["close_10_ema", "close_50_sma", "macd", "macds", "macdh", "rsi", "boll", "boll_ub", "boll_lb", "atr", "vwma", "mfi"]


def classify(text: str) -> str:
    normalized = text.upper()
    if "NO_DATA_AVAILABLE" in normalized:
        return "NO_DATA"
    if "ERROR RETRIEVING" in normalized:
        return "ERROR_TEXT"
    return "OK" if text.strip() else "EMPTY"


def main() -> None:
    config = DEFAULT_CONFIG.copy()
    config["data_vendors"] = {**DEFAULT_CONFIG["data_vendors"], "core_stock_apis": "yfinance", "technical_indicators": "yfinance", "fundamental_data": "yfinance", "news_data": "yfinance"}
    set_config(config)
    today, rows = date.today().isoformat(), []
    for ticker in TICKERS:
        print(f"\n测试 {ticker}")
        for method, build_args in METHODS:
            started = time.perf_counter()
            try:
                result = route_to_vendor(method, *build_args(ticker, today))
                status, detail = classify(result), result[:500].replace("\n", " ")
            except Exception as exc:
                status, detail = "EXCEPTION", f"{type(exc).__name__}: {exc}"
            elapsed = round(time.perf_counter() - started, 3)
            rows.append({"ticker": ticker, "method": method, "status": status, "elapsed_seconds": elapsed, "detail": detail})
            print(f"  {method:26} {status:12} {elapsed:7.3f}s")
            time.sleep(0.5)
        for indicator in INDICATORS:
            started = time.perf_counter()
            try:
                result = route_to_vendor("get_indicators", ticker, indicator, today, 10)
                status, detail = classify(result), result[:300].replace("\n", " ")
            except Exception as exc:
                status, detail = "EXCEPTION", f"{type(exc).__name__}: {exc}"
            elapsed = round(time.perf_counter() - started, 3)
            method = f"get_indicators:{indicator}"
            rows.append({"ticker": ticker, "method": method, "status": status, "elapsed_seconds": elapsed, "detail": detail})
            print(f"  {indicator:26} {status:12} {elapsed:7.3f}s")
    output = Path("audit_output")
    output.mkdir(exist_ok=True)
    path = output / "tradingagents_detail_audit.csv"
    with path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=["ticker", "method", "status", "elapsed_seconds", "detail"])
        writer.writeheader()
        writer.writerows(rows)
    print(f"\n结果已保存：{path}")


if __name__ == "__main__":
    main()
