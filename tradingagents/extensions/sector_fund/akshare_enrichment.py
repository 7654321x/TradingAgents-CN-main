"""AKShare enrichments used only by user-triggered fund analysis."""
from __future__ import annotations

import pandas as pd


def _code(symbol: str) -> str:
    return symbol.split(".", 1)[0]


def get_intraday_5m(symbol: str, start: str, end: str) -> pd.DataFrame:
    import akshare as ak
    code = _code(symbol)
    if symbol.startswith("589130"):
        raw = ak.fund_etf_hist_min_em(code, start, end, "5", "")
    else:
        raw = ak.stock_zh_a_hist_min_em(code, start, end, "5", "")
    rename = {"时间": "Date", "开盘": "Open", "最高": "High", "最低": "Low", "收盘": "Close", "成交量": "Volume", "成交额": "Amount"}
    missing = set(rename) - set(raw.columns)
    if missing:
        raise ValueError(f"AKShare intraday missing columns: {sorted(missing)}")
    frame = raw.rename(columns=rename)[list(rename.values())].copy()
    frame["Date"] = pd.to_datetime(frame["Date"], errors="coerce")
    frame = frame.dropna(subset=["Date"]).set_index("Date").sort_index()
    for column in rename.values():
        if column != "Date":
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame.attrs.update({"market_source": "akshare_eastmoney_intraday", "upstream_group": "eastmoney", "price_adjustment": "raw"})
    return frame


def fetch_individual_fund_flow(symbol: str) -> pd.DataFrame:
    import akshare as ak
    code = _code(symbol)
    market = "sh" if symbol.endswith(".SS") else "sz"
    return ak.stock_individual_fund_flow(stock=code, market=market)


def fetch_financial_indicators(symbol: str) -> pd.DataFrame:
    import akshare as ak
    financial_symbol = symbol.replace(".SS", ".SH")
    return ak.stock_financial_analysis_indicator_em(symbol=financial_symbol, indicator="按报告期")


def normalize_financial_indicator(raw: dict[str, object]) -> dict[str, object]:
    """Map known AKShare financial aliases without inventing absent fields."""
    aliases = {
        "revenue": ("TOTAL_OPERATE_INCOME", "营业总收入", "营业收入"),
        "net_profit": ("PARENT_NETPROFIT", "NETPROFIT", "归母净利润", "净利润"),
        "gross_margin_pct": ("GROSS_PROFIT_MARGIN", "销售毛利率", "毛利率"),
        "inventory": ("INVENTORY", "存货"),
        "contract_liabilities": ("CONTRACT_LIABILITY", "合同负债"),
        "research_and_development_expense": ("RD_EXPENSE", "研发费用"),
        "capital_expenditure": ("CAPITAL_EXPENDITURE", "资本开支"),
        "operating_cash_flow": ("NETCASH_OPERATE", "经营活动产生的现金流量净额"),
    }

    def number(value: object) -> float | None:
        parsed = pd.to_numeric(value, errors="coerce")
        return float(parsed) if pd.notna(parsed) else None

    normalized = {
        field: next(
            (number(raw.get(alias)) for alias in candidates if number(raw.get(alias)) is not None),
            None,
        )
        for field, candidates in aliases.items()
    }
    return {
        "report_date": raw.get("REPORT_DATE") or raw.get("报告期"),
        "notice_date": raw.get("NOTICE_DATE") or raw.get("公告日期"),
        "metrics": normalized,
        "available_metric_count": sum(value is not None for value in normalized.values()),
    }


def fetch_cninfo_announcements(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    import akshare as ak
    return ak.stock_zh_a_disclosure_report_cninfo(
        symbol=_code(symbol), market="沪深京", keyword="", category="", start_date=start_date.replace("-", ""), end_date=end_date.replace("-", "")
    )


def fetch_industry_cycle_board(theme: str, start_date: str, end_date: str) -> dict[str, object]:
    """Read a historical Eastmoney industry-board proxy for a theme.

    This is an observable market-cycle proxy, not a substitute for paid DRAM,
    NAND, or global semiconductor-sales datasets.  The caller stores its
    source/date range so the report can state exactly which proxy was used.
    """
    import akshare as ak

    boards = ak.stock_board_industry_name_em()
    if "板块名称" not in boards.columns:
        raise ValueError("AKShare industry-board list lacks 板块名称")
    names = [str(name) for name in boards["板块名称"].dropna()]
    board = next((name for name in names if name == theme), None)
    board = board or next((name for name in names if theme in name or name in theme), None)
    if board is None:
        raise ValueError(f"no AKShare industry board matches theme: {theme}")
    raw = ak.stock_board_industry_hist_em(
        symbol=board,
        start_date=start_date.replace("-", ""),
        end_date=end_date.replace("-", ""),
        period="日k",
        adjust="",
    )
    required = {"日期", "收盘"}
    if raw.empty or not required.issubset(raw.columns):
        raise ValueError(f"AKShare industry-board history missing columns: {sorted(required - set(raw.columns))}")
    data = raw.copy()
    data["日期"] = pd.to_datetime(data["日期"], errors="coerce")
    data["收盘"] = pd.to_numeric(data["收盘"], errors="coerce")
    data = data.dropna(subset=["日期", "收盘"]).sort_values("日期")
    if data.empty:
        raise ValueError("AKShare industry-board history has no valid rows")
    latest = data.iloc[-1]
    close = float(latest["收盘"])

    def return_pct(days: int) -> float | None:
        if len(data) <= days or float(data.iloc[-days - 1]["收盘"]) == 0:
            return None
        return (close / float(data.iloc[-days - 1]["收盘"]) - 1) * 100

    amount = None
    if "成交额" in data.columns:
        value = pd.to_numeric(data["成交额"], errors="coerce").iloc[-1]
        amount = float(value) if pd.notna(value) else None
    return {
        "status": "SUCCESS",
        "proxy_type": "industry_board_market_proxy",
        "theme": theme,
        "board_name": board,
        "market_date": latest["日期"].date().isoformat(),
        "close": close,
        "return_5d_pct": return_pct(5),
        "return_20d_pct": return_pct(20),
        "amount": amount,
        "source": "akshare_eastmoney_industry_board",
    }
