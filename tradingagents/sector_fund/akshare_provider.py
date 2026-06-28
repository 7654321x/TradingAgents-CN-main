from __future__ import annotations

import contextlib
import io
import re
from datetime import date
from typing import Any, Dict, Iterable, List, Optional


AKSHARE_META = {
    "source": "akshare",
    "upstream_source": "eastmoney",
    "upstream_group": "eastmoney",
    "source_level": "structured_wrapper",
    "independent": False,
}


FUND_TYPE_RELIABILITY = {
    "etf_feeder": "medium_high",
    "index_fund": "medium_high",
    "active_equity": "low",
    "mixed_active": "medium_low",
}


class AkShareProvider:
    def __init__(self):
        self.last_error = ""

    def check_available(self) -> Dict[str, Any]:
        try:
            import akshare as ak  # type: ignore
        except Exception as exc:
            self.last_error = str(exc)
            return {**AKSHARE_META, "source_status": "dependency_missing", "error_reason": f"akshare import failed: {exc}"}
        return {**AKSHARE_META, "source_status": "success", "version": getattr(ak, "__version__", "unknown"), "error_reason": ""}

    def fetch_fund_estimates(self, fund_codes: Iterable[str], fund_types: Optional[Dict[str, str]] = None) -> Dict[str, Dict[str, Any]]:
        ak = self._import_akshare()
        if ak is None:
            return {code: self._dependency_missing(code, "fund") for code in fund_codes}
        try:
            frame = _quiet_call(ak.fund_value_estimation_em, symbol="全部")
        except Exception as exc:
            self.last_error = str(exc)
            frame = self._fallback_fund_estimation_categories(ak)
        result: Dict[str, Dict[str, Any]] = {}
        if frame is None:
            return {code: self._failed(code, "fund", self.last_error or "akshare fund_value_estimation_em failed") for code in fund_codes}
        rows = _records(frame)
        by_code = {str(row.get("基金代码") or row.get("代码") or row.get("fund_code") or "").zfill(6): row for row in rows}
        today = date.today().isoformat()
        for raw_code in fund_codes:
            code = str(raw_code).zfill(6)
            row = by_code.get(code)
            if not row:
                result[code] = self._failed(code, "fund", "akshare fund estimate missing")
                continue
            estimate_date = _estimate_date(row)
            fund_type = (fund_types or {}).get(code, "")
            estimate_change = _percent(_pick_col(row, "估算增长率", "估算涨跌幅"))
            published_change = _percent(_pick_col(row, "公布数据-日增长率", "日增长率"))
            published_nav = _number(_pick_col(row, "公布数据-单位净值", "单位净值"))
            estimate_bias = _percent(row.get("估算偏差"))
            if estimate_bias is None and estimate_change is not None and published_change is not None:
                estimate_bias = round(published_change - estimate_change, 4)
            warning = bool(estimate_bias is not None and abs(estimate_bias) > 1.0)
            reliability = FUND_TYPE_RELIABILITY.get(fund_type, "medium_low")
            if warning:
                reliability = "low" if fund_type in {"active_equity", "mixed_active"} else "medium"
            result[code] = {
                **AKSHARE_META,
                "entity_type": "fund",
                "fund_code": code,
                "fund_name": str(row.get("基金名称") or row.get("名称") or ""),
                "estimate_date": estimate_date,
                "estimate_time": estimate_date,
                "estimate_nav": _number(_pick_col(row, "估算值", "估算净值")),
                "estimate_change_pct": estimate_change,
                "published_nav": published_nav,
                "previous_unit_nav": published_nav,
                "published_change_pct": published_change,
                "previous_nav": _number(_pick_col(row, "上一交易日-单位净值", "单位净值")),
                "estimate_bias_pct": estimate_bias,
                "estimate_error_pct": None if estimate_change is None or published_change is None else round(published_change - estimate_change, 4),
                "abs_estimate_error_pct": None if estimate_change is None or published_change is None else round(abs(published_change - estimate_change), 4),
                "is_stale": bool(estimate_date and estimate_date < today),
                "estimate_reliability": reliability,
                "estimate_warning": warning,
                "estimate_warning_reason": "主动基金估算误差较大，不宜单独作为交易依据。" if warning and fund_type in {"active_equity", "mixed_active"} else "",
                "source_status": "success",
            }
        return result

    def fetch_fund_daily_snapshot(self, fund_codes: Iterable[str]) -> Dict[str, Dict[str, Any]]:
        ak = self._import_akshare()
        if ak is None:
            return {code: self._dependency_missing(code, "fund") for code in fund_codes}
        try:
            frame = _quiet_call(ak.fund_open_fund_daily_em)
        except Exception as exc:
            self.last_error = str(exc)
            return {code: self._failed(code, "fund", str(exc)) for code in fund_codes}
        rows = _records(frame)
        by_code = {str(row.get("基金代码") or row.get("代码") or "").zfill(6): row for row in rows}
        result: Dict[str, Dict[str, Any]] = {}
        for raw_code in fund_codes:
            code = str(raw_code).zfill(6)
            row = by_code.get(code)
            if not row:
                result[code] = self._failed(code, "fund", "akshare fund daily snapshot missing")
                continue
            result[code] = {
                **AKSHARE_META,
                "entity_type": "fund",
                "fund_code": code,
                "fund_name": str(row.get("基金简称") or row.get("基金名称") or row.get("名称") or ""),
                "nav_date": _date_like(row.get("净值日期") or row.get("日期")),
                "unit_nav": _number(row.get("单位净值")),
                "accumulated_nav": _number(row.get("累计净值")),
                "daily_change_value": _number(row.get("日增长值")),
                "daily_change_pct": _percent(row.get("日增长率")),
                "purchase_status": row.get("申购状态"),
                "redeem_status": row.get("赎回状态"),
                "fee": row.get("手续费"),
                "source_status": "success",
            }
        return result

    def fetch_fund_nav_history(self, fund_codes: Iterable[str], tail: int = 20) -> Dict[str, List[Dict[str, Any]]]:
        ak = self._import_akshare()
        if ak is None:
            return {code: [] for code in fund_codes}
        result: Dict[str, List[Dict[str, Any]]] = {}
        for raw_code in fund_codes:
            code = str(raw_code).zfill(6)
            try:
                frame = _quiet_call(ak.fund_open_fund_info_em, symbol=code, indicator="单位净值走势")
                rows = _records(frame)[-tail:]
            except Exception as exc:
                self.last_error = str(exc)
                rows = []
            result[code] = [
                {
                    **AKSHARE_META,
                    "fund_code": code,
                    "nav_date": _date_like(row.get("净值日期") or row.get("日期")),
                    "unit_nav": _number(row.get("单位净值") or row.get("净值")),
                    "daily_change_pct": _percent(row.get("日增长率")),
                    "source_status": "success",
                }
                for row in rows
            ]
        return result

    def fetch_fund_holdings(self, fund_codes: Iterable[str]) -> Dict[str, Dict[str, Any]]:
        ak = self._import_akshare()
        if ak is None:
            return {code: self._dependency_missing(code, "fund") for code in fund_codes}
        current_year = date.today().year
        result: Dict[str, Dict[str, Any]] = {}
        for raw_code in fund_codes:
            code = str(raw_code).zfill(6)
            payload = self._failed(code, "fund", "akshare fund holdings missing")
            for year in (current_year, current_year - 1, current_year - 2):
                try:
                    frame = _quiet_call(ak.fund_portfolio_hold_em, symbol=code, date=str(year))
                    rows = _records(frame)
                except Exception as exc:
                    self.last_error = str(exc)
                    rows = []
                if rows:
                    holdings = [_holding_row(code, row, year) for row in rows[:10]]
                    payload = {
                        **AKSHARE_META,
                        "entity_type": "fund",
                        "fund_code": code,
                        "report_year": holdings[0].get("report_year") or year,
                        "report_quarter": holdings[0].get("report_quarter"),
                        "quarter_label": holdings[0].get("quarter_label"),
                        "top_holdings": holdings,
                        "holding_is_stale": True,
                        "holding_note": "基金持仓来自季度披露，存在滞后，不代表实时持仓。",
                        "source_status": "success",
                    }
                    break
            result[code] = payload
        return result

    def fetch_etf_spot(self, etf_codes: Iterable[str]) -> Dict[str, Dict[str, Any]]:
        return self._fetch_security_spot(etf_codes, is_etf=True)

    def fetch_stock_spot(self, stock_codes: Iterable[str]) -> Dict[str, Dict[str, Any]]:
        return self._fetch_security_spot(stock_codes, is_etf=False)

    def fetch_concept_boards(self, keywords: Iterable[str]) -> Dict[str, Dict[str, Any]]:
        ak = self._import_akshare()
        if ak is None:
            return {keyword: self._dependency_missing(keyword, "sector") for keyword in keywords}
        try:
            rows = _records(_quiet_call(ak.stock_board_concept_name_em))
        except Exception as exc:
            self.last_error = str(exc)
            return {keyword: self._failed(keyword, "sector", str(exc)) for keyword in keywords}
        result: Dict[str, Dict[str, Any]] = {}
        for keyword in keywords:
            row = _match_keyword(str(keyword), rows)
            if not row:
                result[str(keyword)] = self._failed(str(keyword), "sector", "akshare concept board missing")
                continue
            result[str(keyword)] = {
                **AKSHARE_META,
                "entity_type": "sector",
                "sector_name": str(row.get("板块名称") or row.get("概念名称") or row.get("名称") or keyword),
                "sector_code": row.get("板块代码") or row.get("代码"),
                "latest_price": _number(row.get("最新价")),
                "change_amount": _number(row.get("涨跌额")),
                "change_pct": _percent(row.get("涨跌幅")),
                "total_market_value": _number(row.get("总市值")),
                "turnover_rate": _percent(row.get("换手率")),
                "rising_count": _int(row.get("上涨家数")),
                "falling_count": _int(row.get("下跌家数")),
                "leading_stock_name": row.get("领涨股票"),
                "leading_stock_change_pct": _percent(row.get("领涨股票-涨跌幅") or row.get("领涨股涨跌幅")),
                "source_status": "success",
            }
        return result

    def _fetch_security_spot(self, codes: Iterable[str], is_etf: bool) -> Dict[str, Dict[str, Any]]:
        ak = self._import_akshare()
        if ak is None:
            return {code: self._dependency_missing(code, "etf" if is_etf else "stock") for code in codes}
        try:
            frame = _quiet_call(ak.fund_etf_spot_em) if is_etf else _quiet_call(ak.stock_zh_a_spot_em)
            rows = _records(frame)
        except Exception as exc:
            self.last_error = str(exc)
            return {code: self._failed(code, "etf" if is_etf else "stock", str(exc)) for code in codes}
        by_code = {str(row.get("代码") or row.get("基金代码") or "").zfill(6): row for row in rows}
        result: Dict[str, Dict[str, Any]] = {}
        for raw_code in codes:
            code = str(raw_code).zfill(6)
            row = by_code.get(code)
            if not row:
                result[code] = self._failed(code, "etf" if is_etf else "stock", "akshare security quote missing")
                continue
            result[code] = {
                **AKSHARE_META,
                "entity_type": "etf" if is_etf else "stock",
                "code": code,
                "name": str(row.get("名称") or row.get("基金简称") or ""),
                "latest_price": _number(row.get("最新价")),
                "change_pct": _percent(row.get("涨跌幅")),
                "change_amount": _number(row.get("涨跌额")),
                "volume": _number(row.get("成交量")),
                "amount": _number(row.get("成交额")),
                "turnover_rate": _percent(row.get("换手率")),
                "high": _number(row.get("最高")),
                "low": _number(row.get("最低")),
                "open": _number(row.get("今开")),
                "previous_close": _number(row.get("昨收")),
                "total_market_value": _number(row.get("总市值")),
                "float_market_value": _number(row.get("流通市值")),
                "source_status": "success",
            }
        return result

    def _fallback_fund_estimation_categories(self, ak: Any) -> Any:
        frames = []
        for symbol in ("股票型", "混合型", "指数型", "ETF联接", "LOF", "QDII"):
            try:
                frame = _quiet_call(ak.fund_value_estimation_em, symbol=symbol)
                if frame is not None and not getattr(frame, "empty", False):
                    frames.append(frame)
            except Exception as exc:
                self.last_error = str(exc)
        if not frames:
            return None
        try:
            import pandas as pd  # type: ignore

            return pd.concat(frames, ignore_index=True).drop_duplicates()
        except Exception:
            return frames[0]

    def _import_akshare(self) -> Any:
        try:
            import akshare as ak  # type: ignore

            return ak
        except Exception as exc:
            self.last_error = str(exc)
            return None

    def _dependency_missing(self, code: str, entity_type: str) -> Dict[str, Any]:
        return {**AKSHARE_META, "entity_type": entity_type, "code": code, "source_status": "dependency_missing", "error_reason": f"akshare import failed: {self.last_error}"}

    def _failed(self, code: str, entity_type: str, reason: str) -> Dict[str, Any]:
        return {**AKSHARE_META, "entity_type": entity_type, "code": code, "source_status": "failed", "error_reason": reason}


def _records(frame: Any) -> List[Dict[str, Any]]:
    if frame is None:
        return []
    if hasattr(frame, "to_dict"):
        return frame.to_dict("records")
    if isinstance(frame, list):
        return [dict(row) for row in frame]
    return []


def _quiet_call(func: Any, *args: Any, **kwargs: Any) -> Any:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        return func(*args, **kwargs)


def _pick_col(row: Dict[str, Any], *contains: str) -> Any:
    for token in contains:
        for key, value in row.items():
            if token in str(key):
                return value
    return None


def _estimate_date(row: Dict[str, Any]) -> str:
    for key in row:
        match = re.search(r"(\d{4}-\d{2}-\d{2})-估算数据", str(key))
        if match:
            return match.group(1)
    for key in row:
        match = re.search(r"(\d{4}-\d{2}-\d{2})", str(key))
        if match:
            return match.group(1)
    return ""


def _date_like(value: Any) -> str:
    if value in (None, ""):
        return ""
    text = str(value)
    match = re.search(r"\d{4}[-/]\d{1,2}[-/]\d{1,2}", text)
    if not match:
        return text[:10]
    parts = re.split(r"[-/]", match.group(0))
    return f"{int(parts[0]):04d}-{int(parts[1]):02d}-{int(parts[2]):02d}"


def _percent(value: Any) -> Optional[float]:
    if value in (None, "", "-", "--"):
        return None
    text = str(value).replace("%", "").replace(",", "").strip()
    try:
        return float(text)
    except ValueError:
        return None


def _number(value: Any) -> Optional[float]:
    if value in (None, "", "-", "--"):
        return None
    text = str(value).replace("%", "").replace(",", "").strip()
    try:
        return float(text)
    except ValueError:
        return None


def _int(value: Any) -> Optional[int]:
    number = _number(value)
    return None if number is None else int(number)


def _holding_row(code: str, row: Dict[str, Any], fallback_year: int) -> Dict[str, Any]:
    label = str(row.get("季度") or row.get("报告期") or row.get("股票投资明细") or "")
    parsed = re.search(r"(\d{4})年([1-4])季度", label)
    report_year = int(parsed.group(1)) if parsed else fallback_year
    report_quarter = int(parsed.group(2)) if parsed else None
    return {
        "fund_code": code,
        "report_year": report_year,
        "report_quarter": report_quarter,
        "rank": _int(row.get("序号") or row.get("排名")),
        "holding_stock_code": str(row.get("股票代码") or row.get("代码") or ""),
        "holding_stock_name": str(row.get("股票名称") or row.get("名称") or ""),
        "holding_weight_pct": _percent(row.get("占净值比例") or row.get("持仓占比")),
        "holding_shares": _number(row.get("持股数") or row.get("持股数量")),
        "holding_market_value": _number(row.get("持股市值") or row.get("市值")),
        "quarter_label": label or (f"{report_year}年{report_quarter}季度股票投资明细" if report_quarter else str(report_year)),
        "source": "akshare",
    }


def _match_keyword(keyword: str, rows: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    for row in rows:
        name = str(row.get("板块名称") or row.get("概念名称") or row.get("名称") or "")
        if name == keyword:
            return row
    for row in rows:
        name = str(row.get("板块名称") or row.get("概念名称") or row.get("名称") or "")
        if keyword and (keyword in name or name in keyword):
            return row
    return None
