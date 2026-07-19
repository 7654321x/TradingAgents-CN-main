from __future__ import annotations

import json
import math
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import pandas as pd
import yfinance as yf

TICKERS = [
    "600519.SS", "601318.SS", "600036.SS", "601899.SS", "600276.SS",
    "601012.SS", "688981.SS", "000001.SZ", "000858.SZ", "000333.SZ",
    "002594.SZ", "002475.SZ", "300750.SZ", "002371.SZ", "300308.SZ",
]

INFO_FIELDS = [
    "longName", "quoteType", "exchange", "currency", "sector", "industry",
    "marketCap", "currentPrice", "previousClose", "trailingPE", "forwardPE",
    "pegRatio", "priceToBook", "trailingEps", "forwardEps", "dividendYield",
    "beta", "fiftyTwoWeekHigh", "fiftyTwoWeekLow", "fiftyDayAverage",
    "twoHundredDayAverage", "totalRevenue", "grossProfits", "ebitda",
    "netIncomeToCommon", "profitMargins", "operatingMargins", "returnOnEquity",
    "returnOnAssets", "debtToEquity", "currentRatio", "bookValue", "freeCashflow",
]
KEY_INCOME_ROWS = ["TotalRevenue", "GrossProfit", "OperatingIncome", "PretaxIncome", "NetIncome", "BasicEPS", "DilutedEPS"]
KEY_BALANCE_ROWS = ["TotalAssets", "CurrentAssets", "CashCashEquivalentsAndShortTermInvestments", "TotalLiabilitiesNetMinorityInterest", "CurrentLiabilities", "StockholdersEquity", "TotalDebt"]
KEY_CASHFLOW_ROWS = ["OperatingCashFlow", "InvestingCashFlow", "FinancingCashFlow", "CapitalExpenditure", "FreeCashFlow"]


@dataclass
class Result:
    ticker: str
    test: str
    status: str
    rows: int | None = None
    columns: int | None = None
    available_fields: int | None = None
    expected_fields: int | None = None
    completeness_pct: float | None = None
    latest_period: str | None = None
    detail: str | None = None
    elapsed_seconds: float | None = None


def is_present(value: Any) -> bool:
    return value is not None and not (isinstance(value, float) and math.isnan(value)) and not (isinstance(value, str) and not value.strip())


def safe_call(ticker: str, test_name: str, func: Callable[[], Any]) -> tuple[Any, Result]:
    started = time.perf_counter()
    try:
        value = func()
        return value, Result(ticker, test_name, "OK", elapsed_seconds=round(time.perf_counter() - started, 3))
    except Exception as exc:
        return None, Result(ticker, test_name, "ERROR", detail=f"{type(exc).__name__}: {exc}", elapsed_seconds=round(time.perf_counter() - started, 3))


def inspect_dataframe(result: Result, frame: Any, expected_rows: list[str] | None = None) -> Result:
    if frame is None:
        result.status, result.detail = "EMPTY", "返回 None"
        return result
    if not isinstance(frame, pd.DataFrame):
        result.status, result.detail = "INVALID", f"返回类型不是 DataFrame：{type(frame).__name__}"
        return result
    result.rows, result.columns = int(frame.shape[0]), int(frame.shape[1])
    if frame.empty:
        result.status, result.detail = "EMPTY", "DataFrame 为空"
        return result
    periods = pd.to_datetime(frame.columns, errors="coerce")
    valid = periods[~pd.isna(periods)]
    if len(valid):
        result.latest_period = str(max(valid).date())
    if expected_rows:
        present = sum(name in frame.index for name in expected_rows)
        missing = [name for name in expected_rows if name not in frame.index]
        result.available_fields, result.expected_fields = present, len(expected_rows)
        result.completeness_pct = round(present / len(expected_rows) * 100, 1)
        result.detail = "关键行完整" if not missing else "缺少：" + ", ".join(missing)
    return result


def test_one_ticker(symbol: str) -> tuple[list[Result], dict[str, Any]]:
    ticker, results, raw = yf.Ticker(symbol), [], {"ticker": symbol}
    fast, result = safe_call(symbol, "fast_info", lambda: dict(ticker.fast_info))
    if result.status == "OK":
        keys = ["lastPrice", "previousClose", "marketCap", "currency", "exchange", "timezone"]
        present = sum(is_present(fast.get(key)) for key in keys)
        result.available_fields, result.expected_fields = present, len(keys)
        result.completeness_pct = round(present / len(keys) * 100, 1)
        result.detail = json.dumps({key: fast.get(key) for key in keys}, ensure_ascii=False, default=str)
        raw["fast_info"] = {key: fast.get(key) for key in keys}
    results.append(result)

    info, result = safe_call(symbol, "info", ticker.get_info)
    if result.status == "OK":
        info = info or {}
        present = {key: info.get(key) for key in INFO_FIELDS if is_present(info.get(key))}
        missing = [key for key in INFO_FIELDS if key not in present]
        result.available_fields, result.expected_fields = len(present), len(INFO_FIELDS)
        result.completeness_pct = round(len(present) / len(INFO_FIELDS) * 100, 1)
        result.detail = f"公司={info.get('longName')}; 行业={info.get('sector')}/{info.get('industry')}; 缺失字段={','.join(missing)}"
        raw["info_present"], raw["info_missing"] = present, missing
    results.append(result)

    history, result = safe_call(symbol, "history_1y_actions", lambda: ticker.history(period="1y", interval="1d", auto_adjust=False, actions=True))
    if result.status == "OK":
        result = inspect_dataframe(result, history)
        if isinstance(history, pd.DataFrame) and not history.empty:
            result.latest_period = str(history.index[-1])
            result.detail = "字段：" + ", ".join(c for c in ["Open", "High", "Low", "Close", "Volume", "Dividends", "Stock Splits"] if c in history.columns)
    results.append(result)

    intraday, result = safe_call(symbol, "intraday_5m_5d", lambda: ticker.history(period="5d", interval="5m", auto_adjust=False, actions=False))
    if result.status == "OK":
        result = inspect_dataframe(result, intraday)
        if isinstance(intraday, pd.DataFrame) and not intraday.empty:
            result.latest_period, result.detail = str(intraday.index[-1]), f"首条={intraday.index[0]}; 末条={intraday.index[-1]}"
    results.append(result)

    statements = [
        ("income_quarterly", lambda: ticker.get_income_stmt(freq="quarterly"), KEY_INCOME_ROWS),
        ("income_annual", lambda: ticker.get_income_stmt(freq="yearly"), KEY_INCOME_ROWS),
        ("balance_quarterly", lambda: ticker.get_balance_sheet(freq="quarterly"), KEY_BALANCE_ROWS),
        ("balance_annual", lambda: ticker.get_balance_sheet(freq="yearly"), KEY_BALANCE_ROWS),
        ("cashflow_quarterly", lambda: ticker.get_cash_flow(freq="quarterly"), KEY_CASHFLOW_ROWS),
        ("cashflow_annual", lambda: ticker.get_cash_flow(freq="yearly"), KEY_CASHFLOW_ROWS),
    ]
    for name, func, expected in statements:
        frame, result = safe_call(symbol, name, func)
        results.append(inspect_dataframe(result, frame, expected) if result.status == "OK" else result)

    news, result = safe_call(symbol, "news", lambda: ticker.get_news(count=10))
    if result.status == "OK":
        news = news or []
        result.rows = len(news)
        if not news:
            result.status, result.detail = "EMPTY", "没有返回新闻"
        else:
            first = news[0]
            content = first.get("content", first) if isinstance(first, dict) else {}
            title = content.get("title") if isinstance(content, dict) else None
            provider = content.get("provider", {}).get("displayName") if isinstance(content, dict) and isinstance(content.get("provider"), dict) else None
            result.detail = f"第一条：{title}; 来源={provider}"
    results.append(result)

    insider, result = safe_call(symbol, "insider_transactions", lambda: ticker.insider_transactions)
    if result.status == "OK":
        if insider is None:
            result.status, result.detail = "EMPTY", "返回 None"
        elif isinstance(insider, pd.DataFrame):
            result.rows, result.columns = len(insider), len(insider.columns)
            if insider.empty:
                result.status, result.detail = "EMPTY", "无内部人交易记录"
        else:
            result.status, result.detail = "INVALID", f"返回类型：{type(insider).__name__}"
    results.append(result)

    targets, result = safe_call(symbol, "analyst_price_targets", lambda: ticker.analyst_price_targets)
    if result.status == "OK":
        if not targets:
            result.status, result.detail = "EMPTY", "无分析师目标价"
        else:
            result.available_fields, result.expected_fields = sum(is_present(v) for v in targets.values()), len(targets)
            result.detail = json.dumps(targets, ensure_ascii=False, default=str)
    results.append(result)
    return results, raw


def main() -> None:
    output = Path("audit_output")
    output.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    all_results, raw = [], []
    print(f"yfinance 版本：{yf.__version__}\n开始时间：{datetime.now().isoformat()}\n测试股票数：{len(TICKERS)}")
    for index, symbol in enumerate(TICKERS, 1):
        print(f"\n[{index}/{len(TICKERS)}] 测试 {symbol}")
        items, summary = test_one_ticker(symbol)
        all_results.extend(items)
        raw.append(summary)
        for item in items:
            print(f"  {item.test:24} {item.status:7} rows={item.rows!s:5} complete={item.completeness_pct!s:6} time={item.elapsed_seconds!s:6}")
        time.sleep(1.5)
    frame = pd.DataFrame(asdict(item) for item in all_results)
    csv_path = output / f"yfinance_detail_audit_{stamp}.csv"
    json_path = output / f"yfinance_detail_raw_{stamp}.json"
    summary_path = output / f"yfinance_detail_summary_{stamp}.csv"
    frame.to_csv(csv_path, index=False, encoding="utf-8-sig")
    json_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    summary = frame.groupby("test", dropna=False).agg(
        tested=("ticker", "count"), ok=("status", lambda x: int((x == "OK").sum())),
        empty=("status", lambda x: int((x == "EMPTY").sum())), error=("status", lambda x: int((x == "ERROR").sum())),
        invalid=("status", lambda x: int((x == "INVALID").sum())), avg_completeness=("completeness_pct", "mean"),
        avg_seconds=("elapsed_seconds", "mean"),
    ).reset_index()
    summary.to_csv(summary_path, index=False, encoding="utf-8-sig")
    print("\n" + "=" * 100)
    print(summary.to_string(index=False))
    print(f"\n输出文件：\n{csv_path}\n{json_path}\n{summary_path}")


if __name__ == "__main__":
    main()
