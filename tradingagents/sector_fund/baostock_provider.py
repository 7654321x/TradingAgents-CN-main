from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout
from datetime import date, timedelta
from typing import Any, Dict, Iterable, List, Optional

from .logging_utils import get_sector_logger


INDEX_CODE_MAP = {
    "上证指数": "sh.000001",
    "上证综指": "sh.000001",
    "深成指": "sz.399001",
    "深证成指": "sz.399001",
    "创业板指": "sz.399006",
    "沪深300": "sh.000300",
    "中证500": "sh.000905",
    "中证1000": "sh.000852",
    "科创50": "sh.000688",
}


INDEX_CODE_CANDIDATES = {
    "科创50": ["sh.000688", "sh.000689"],
}


def to_baostock_code(code: str) -> str:
    normalized = str(code).strip().lower()
    if str(code).strip() in INDEX_CODE_MAP:
        return INDEX_CODE_MAP[str(code).strip()]
    if normalized.startswith(("sh.", "sz.")):
        return normalized
    raw = normalized.zfill(6)
    if raw.startswith(("6", "9", "688", "689", "5")):
        return f"sh.{raw}"
    if raw.startswith(("0", "2", "3", "1")):
        return f"sz.{raw}"
    return raw


def _float(value: Any) -> Optional[float]:
    try:
        if value in ("", None):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def calculate_indicators(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    cleaned = [row for row in rows if _float(row.get("close")) is not None]
    if not cleaned:
        return {}
    latest = cleaned[-1]
    closes = [_float(row.get("close")) for row in cleaned]

    def ma(window: int) -> Optional[float]:
        if len(closes) < window:
            return None
        return round(sum(closes[-window:]) / window, 4)

    close = _float(latest.get("close"))
    open_price = _float(latest.get("open"))
    high = _float(latest.get("high"))
    low = _float(latest.get("low"))
    ma5 = ma(5)
    ma10 = ma(10)
    ma20 = ma(20)
    ma60 = ma(60)
    day_range = (high - low) if high is not None and low is not None else None
    upper_shadow = (high - max(open_price, close)) if None not in (high, open_price, close) else None
    field_sources = {
        "kline": "baostock",
        "latest_price": "baostock",
        "change_pct": "baostock",
        "turnover_billion": "baostock",
        "turnover_rate": "baostock",
        "ma5": "baostock" if ma5 is not None else "insufficient_history",
        "ma10": "baostock" if ma10 is not None else "insufficient_history",
        "ma20": "baostock" if ma20 is not None else "insufficient_history",
        "ma60": "baostock" if ma60 is not None else "insufficient_history",
    }
    return {
        "code": latest.get("code"),
        "trade_date": latest.get("trade_date") or latest.get("date"),
        "latest_price": close,
        "change_pct": _float(latest.get("pct_chg")),
        "turnover_billion": round((_float(latest.get("amount")) or 0) / 100000000, 4) if latest.get("amount") is not None else None,
        "turnover_rate": _float(latest.get("turnover_rate")),
        "ma5": ma5,
        "ma10": ma10,
        "ma20": ma20,
        "ma60": ma60,
        "near_ma5": None if ma5 in (None, 0) or close is None else abs(close - ma5) / ma5 <= 0.015,
        "near_ma10": None if ma10 in (None, 0) or close is None else abs(close - ma10) / ma10 <= 0.02,
        "below_ma5": None if ma5 is None or close is None else close < ma5,
        "below_ma10": None if ma10 is None or close is None else close < ma10,
        "below_ma20": None if ma20 is None or close is None else close < ma20,
        "long_upper_shadow": None if not day_range or upper_shadow is None else upper_shadow / day_range >= 0.45,
        "intraday_pullback": None if high in (None, 0) or close is None or _float(latest.get("preclose")) in (None, 0) else (high - (_float(latest.get("preclose")) or 0)) / (_float(latest.get("preclose")) or 1) > 0.03 and (high - close) / high > 0.02,
        "field_sources": field_sources,
    }


class BaostockProvider:
    def __init__(self):
        self.login_status = "not_started"
        self.logout_status = "not_started"
        self.last_error = ""
        self._bs = None
        self._logged_in = False
        self.login_count = 0
        self.logout_count = 0
        self.native_stdout = ""
        self.native_stderr = ""

    def login(self) -> str:
        if self._logged_in:
            return self.login_status
        try:
            import baostock as bs  # type: ignore
        except Exception as exc:
            self.login_status = "dependency_missing"
            self.last_error = f"baostock import failed: {exc}"
            return self.login_status
        out = io.StringIO()
        err = io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            login = bs.login()
        self._capture_native_output(out.getvalue(), err.getvalue())
        self.login_count += 1
        if getattr(login, "error_code", "") != "0":
            self.login_status = "login_failed"
            self.last_error = getattr(login, "error_msg", "baostock login failed")
            return self.login_status
        self._bs = bs
        self._logged_in = True
        self.login_status = "success"
        self.last_error = ""
        return self.login_status

    def logout(self) -> str:
        if not self._logged_in or self._bs is None:
            self.logout_status = "not_logged_in"
            return self.logout_status
        try:
            out = io.StringIO()
            err = io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                self._bs.logout()
            self._capture_native_output(out.getvalue(), err.getvalue())
            self.logout_count += 1
            self.logout_status = "success"
        except Exception as exc:
            self.logout_status = "failed"
            self.last_error = str(exc)
        finally:
            self._logged_in = False
            self._bs = None
        return self.logout_status

    def fetch_latest_daily_snapshots_batch(
        self,
        codes: Iterable[str],
        lookback_days: int = 40,
        purpose: str = "batch_history",
    ) -> Dict[str, Dict[str, Any]]:
        code_list = list(codes)
        logger = get_sector_logger("baostock")
        if self.login() != "success":
            logger.warning(
                "⚠️ [Baostock] 批次登录失败，改用AKShare历史行情兜底 | reason=%s purpose=%s symbols=%s",
                self.last_error,
                purpose,
                len(code_list),
            )
            return {
                code: {
                    "code": code,
                    "rows": [],
                    "indicator": {},
                    "source": "baostock",
                    "source_status": self.login_status,
                    "error_reason": self.last_error or "baostock login failed",
                }
                for code in code_list
            }
        logger.info("✅ [Baostock] 批次登录成功 | symbols=%s purpose=%s", len(code_list), purpose)
        if self.native_stdout or self.native_stderr:
            logger.debug("🔧 [Baostock] 原生输出 | stdout=%s stderr=%s", self.native_stdout.strip(), self.native_stderr.strip())
        try:
            return {code: self.fetch_latest_daily_snapshot(code, lookback_days=lookback_days) for code in code_list}
        finally:
            self.logout()
            logger.info("✅ [Baostock] 批次退出成功 | symbols=%s purpose=%s", len(code_list), purpose)
            if self.native_stdout or self.native_stderr:
                logger.debug("🔧 [Baostock] 原生输出 | stdout=%s stderr=%s", self.native_stdout.strip(), self.native_stderr.strip())

    def _capture_native_output(self, stdout_text: str, stderr_text: str) -> None:
        if stdout_text:
            self.native_stdout = (self.native_stdout + stdout_text)[-2000:]
        if stderr_text:
            self.native_stderr = (self.native_stderr + stderr_text)[-2000:]

    def __enter__(self):
        self.login()
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.logout()
        return False

    def fetch_history_k(
        self,
        code: str,
        start_date: str | None = None,
        end_date: str | None = None,
        frequency: str = "d",
        lookback_days: int = 40,
    ) -> List[Dict[str, Any]]:
        end_date = end_date or date.today().isoformat()
        start_date = start_date or (date.today() - timedelta(days=lookback_days * 2)).isoformat()
        close_after_query = not self._logged_in
        if self.login() != "success" or self._bs is None:
            return []
        fields = "date,code,open,high,low,close,preclose,volume,amount,turn,pctChg,tradestatus"
        rows: List[Dict[str, Any]] = []
        try:
            result = self._bs.query_history_k_data_plus(
                to_baostock_code(code),
                fields,
                start_date=start_date,
                end_date=end_date,
                frequency=frequency,
                adjustflag="2",
            )
            if getattr(result, "error_code", "") != "0":
                self.login_status = "query_failed"
                self.last_error = getattr(result, "error_msg", "query_history_k_data_plus failed")
                return []
            while result.error_code == "0" and result.next():
                item = dict(zip(result.fields, result.get_row_data()))
                rows.append(normalize_baostock_row(code, item))
        except Exception as exc:
            self.login_status = "query_failed"
            self.last_error = str(exc)
            return []
        finally:
            if close_after_query:
                self.logout()
        return rows

    def fetch_latest_daily_snapshot(self, code: str, lookback_days: int = 40) -> Dict[str, Any]:
        rows = []
        candidates = index_code_candidates(code)
        used_code = ""
        errors: List[str] = []
        for candidate in candidates:
            rows = self.fetch_history_k(candidate, lookback_days=lookback_days)
            if rows:
                used_code = to_baostock_code(candidate)
                break
            if self.last_error:
                errors.append(f"{to_baostock_code(candidate)}: {self.last_error}")
            elif len(candidates) > 1:
                errors.append(f"{to_baostock_code(candidate)}: no rows")
        indicator = calculate_indicators(rows)
        latest_trade_date = indicator.get("trade_date") or (rows[-1].get("trade_date") if rows else None)
        if rows:
            source_status = "success"
            error_reason = ""
        elif self.login_status == "dependency_missing":
            source_status = "dependency_missing"
            error_reason = self.last_error
        else:
            source_status = "missing"
            error_reason = "baostock returned no rows"
        support_probe = self.probe_security_support(candidates) if not rows and self.login_status == "success" else {}
        return {
            "code": code,
            "baostock_code": used_code or to_baostock_code(code),
            "candidate_codes": [to_baostock_code(candidate) for candidate in candidates],
            "support_probe": support_probe,
            "rows": rows,
            "rows_count": len(rows),
            "indicator": indicator,
            "latest_trade_date": latest_trade_date,
            "latest_close": indicator.get("latest_price"),
            "pct_chg": indicator.get("change_pct"),
            "ma5": indicator.get("ma5"),
            "ma10": indicator.get("ma10"),
            "ma20": indicator.get("ma20"),
            "source": "baostock",
            "source_status": source_status,
            "error_reason": error_reason,
            "candidate_errors": errors,
        }

    def fetch_latest_snapshot(self, code: str, lookback_days: int = 40) -> Dict[str, Any]:
        return self.fetch_latest_daily_snapshot(code, lookback_days=lookback_days)

    def fetch_etf_daily(self, etf_codes: Iterable[str]) -> Dict[str, Dict[str, Any]]:
        return {code: self.fetch_latest_snapshot(code) for code in etf_codes}

    def fetch_stock_daily(self, stock_codes: Iterable[str]) -> Dict[str, Dict[str, Any]]:
        return {code: self.fetch_latest_snapshot(code) for code in stock_codes}

    def fetch_index_daily(self, index_codes: Iterable[str]) -> Dict[str, Dict[str, Any]]:
        return {code: self.fetch_latest_snapshot(code) for code in index_codes}

    def get_latest_trade_date(self) -> str:
        probe = self.fetch_latest_daily_snapshot("sh.000001", lookback_days=10)
        return probe.get("latest_trade_date") or date.today().isoformat()

    def query_all_stock(self, trade_date: str | None = None) -> Dict[str, Any]:
        close_after_query = not self._logged_in
        if self.login() != "success" or self._bs is None:
            return {"status": self.login_status, "rows": [], "error_reason": self.last_error}
        try:
            probe_days = [trade_date] if trade_date else [(date.today() - timedelta(days=offset)).isoformat() for offset in range(0, 11)]
            last_error = ""
            for day in probe_days:
                result = self._bs.query_all_stock(day=day)
                if getattr(result, "error_code", "") != "0":
                    last_error = getattr(result, "error_msg", "query_all_stock failed")
                    continue
                rows: List[Dict[str, Any]] = []
                while result.error_code == "0" and result.next():
                    rows.append(dict(zip(result.fields, result.get_row_data())))
                if rows or trade_date:
                    return {"status": "success", "rows": rows, "trade_date": day, "error_reason": ""}
            return {"status": "empty", "rows": [], "trade_date": probe_days[-1] if probe_days else "", "error_reason": last_error}
        except Exception as exc:
            return {"status": "query_failed", "rows": [], "error_reason": str(exc)}
        finally:
            if close_after_query:
                self.logout()

    def probe_security_support(self, codes: Iterable[str]) -> Dict[str, Any]:
        candidates = [to_baostock_code(code) for code in codes]
        result = self.query_all_stock()
        rows = result.get("rows", [])
        supported_codes = {str(row.get("code") or "") for row in rows}
        return {
            "status": result.get("status", ""),
            "candidate_codes": candidates,
            "supported_codes": [code for code in candidates if code in supported_codes],
            "is_supported": any(code in supported_codes for code in candidates),
            "total_listed": len(rows),
            "trade_date": result.get("trade_date", ""),
            "error_reason": result.get("error_reason", ""),
        }


def index_code_candidates(code: str) -> List[str]:
    raw = str(code).strip()
    candidates = INDEX_CODE_CANDIDATES.get(raw)
    if candidates:
        return candidates
    return [to_baostock_code(raw)]


def normalize_baostock_row(code: str, row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "code": code,
        "baostock_code": row.get("code") or to_baostock_code(code),
        "trade_date": row.get("date"),
        "open": _float(row.get("open")),
        "high": _float(row.get("high")),
        "low": _float(row.get("low")),
        "close": _float(row.get("close")),
        "preclose": _float(row.get("preclose")),
        "volume": _float(row.get("volume")),
        "amount": _float(row.get("amount")),
        "turnover_rate": _float(row.get("turn") or row.get("turnover_rate")),
        "pct_chg": _float(row.get("pctChg") or row.get("pct_chg")),
        "tradestatus": row.get("tradestatus"),
        "source": "baostock",
        "source_status": "success",
    }
