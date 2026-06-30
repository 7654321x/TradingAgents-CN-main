import re
from typing import Any, Dict, Optional

from .fetch_logger import DataFetchLogger


SECTOR_ALIASES = {
    "半导体": "semiconductor_main_inflow_billion",
    "存储芯片": "storage_main_inflow_billion",
    "电子行业": "electronics_main_inflow_billion",
    "电子": "electronics_main_inflow_billion",
    "芯片概念": "chip_main_inflow_billion",
}


def _clean_text(text: str) -> str:
    text = re.sub(r"<script[\s\S]*?</script>", " ", text or "", flags=re.IGNORECASE)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("&nbsp;", " ").replace("\u3000", " ")
    return re.sub(r"[ \t]+", " ", text)


def _number(value: str) -> Optional[float]:
    if not value:
        return None
    normalized = value.replace(",", "").replace("＋", "+").replace("－", "-").strip()
    match = re.search(r"[-+]?\d+(?:\.\d+)?", normalized)
    if not match:
        return None
    try:
        return float(match.group())
    except ValueError:
        return None


def parse_chinese_amount_to_billion(text: str) -> Optional[float]:
    value = _number(text)
    if value is None:
        return None

    normalized = (text or "").replace(" ", "")
    if "万亿" in normalized:
        return round(value * 10000, 4)
    if "亿元" in normalized or "亿" in normalized:
        return round(value, 4)
    if "万元" in normalized or "万" in normalized:
        return round(value / 10000, 4)
    return value


def parse_percent_value(text: str) -> Optional[float]:
    value = _number(text)
    if value is None:
        return None
    return round(value, 4)


def _find_value_after_label(text: str, labels: list[str], value_pattern: str = r"[-+]?\d+(?:\.\d+)?%?") -> Optional[str]:
    for label in labels:
        pattern = rf"{re.escape(label)}\s*[:：]?\s*({value_pattern})"
        match = re.search(pattern, text)
        if match:
            return match.group(1)
    return None


def _set_if_present(parsed: Dict[str, Any], field_name: str, value: Any) -> None:
    if value is not None:
        parsed[field_name] = value


def _parse_labeled_amount(text: str, labels: list[str]) -> Optional[float]:
    value = _find_value_after_label(
        text,
        labels,
        r"[-+]?\d+(?:,\d{3})*(?:\.\d+)?\s*(?:万亿|亿元|亿|万元|万)",
    )
    return parse_chinese_amount_to_billion(value) if value else None


def _parse_last_labeled_amount(text: str, labels: list[str]) -> Optional[float]:
    matches: list[str] = []
    for label in labels:
        pattern = rf"{re.escape(label)}\s*[:：]?\s*([-+]?\d+(?:,\d{{3}})*(?:\.\d+)?\s*(?:万亿|亿元|亿|万元|万))"
        matches.extend(match.group(1) for match in re.finditer(pattern, text))
    return parse_chinese_amount_to_billion(matches[-1]) if matches else None


def _parse_labeled_percent(text: str, labels: list[str]) -> Optional[float]:
    value = _find_value_after_label(text, labels, r"[-+]?\d+(?:\.\d+)?\s*%")
    return parse_percent_value(value) if value else None


def _parse_labeled_number(text: str, labels: list[str]) -> Optional[float]:
    value = _find_value_after_label(text, labels, r"[-+]?\d+(?:,\d{3})*(?:\.\d+)?")
    return _number(value) if value else None


def parse_etf_quote_text(etf_code: str, etf_name: str, text: str) -> Dict[str, Any]:
    cleaned = _clean_text(text)
    parsed: Dict[str, Any] = {"code": etf_code, "name": etf_name}

    _set_if_present(parsed, "latest_price", _parse_labeled_number(cleaned, ["最新价", "最新价格", "价格", "单位净值", "最新净值"]))
    _set_if_present(parsed, "change_pct", _parse_labeled_percent(cleaned, ["涨跌幅", "涨幅", "日增长率", "日涨跌幅"]))
    _set_if_present(parsed, "turnover_billion", _parse_labeled_amount(cleaned, ["成交额", "成交金额"]))
    _set_if_present(parsed, "turnover_rate", _parse_labeled_percent(cleaned, ["换手率"]))
    _set_if_present(parsed, "premium_rate_pct", _parse_labeled_percent(cleaned, ["溢价率", "折溢价率"]))
    _set_if_present(parsed, "five_day_change_pct", _parse_labeled_percent(cleaned, ["近5日涨幅", "近5日", "近一周", "近1周"]))
    return parsed


def parse_fund_nav_text(fund_code: str, text: str) -> Dict[str, Any]:
    cleaned = _clean_text(text)
    parsed: Dict[str, Any] = {}

    unit_nav = _find_value_after_label(cleaned, ["单位净值", "最新净值"])
    if unit_nav is not None:
        parsed["unit_nav"] = _number(unit_nav)

    daily = _find_value_after_label(cleaned, ["日增长率", "日涨跌幅", "净值估算"], r"[-+]?\d+(?:\.\d+)?\s*%")
    if daily is not None:
        parsed["daily_change_pct"] = parse_percent_value(daily)

    week = _find_value_after_label(cleaned, ["近1周", "近一周"], r"[-+]?\d+(?:\.\d+)?\s*%")
    month = _find_value_after_label(cleaned, ["近1月", "近一月"], r"[-+]?\d+(?:\.\d+)?\s*%")
    three_month = _find_value_after_label(cleaned, ["近3月", "近三月"], r"[-+]?\d+(?:\.\d+)?\s*%")
    ytd = _find_value_after_label(cleaned, ["今年以来", "今年来"], r"[-+]?\d+(?:\.\d+)?\s*%")
    if week is not None:
        parsed["week_change_pct"] = parse_percent_value(week)
    if month is not None:
        parsed["month_change_pct"] = parse_percent_value(month)
    if three_month is not None:
        parsed["three_month_change_pct"] = parse_percent_value(three_month)
    if ytd is not None:
        parsed["ytd_change_pct"] = parse_percent_value(ytd)

    size_match = re.search(r"基金规模\s*[:：]?\s*([-+]?\d+(?:,\d{3})*(?:\.\d+)?\s*(?:万亿|亿元|亿|万元|万))", cleaned)
    if size_match:
        parsed["size_billion"] = parse_chinese_amount_to_billion(size_match.group(1))

    manager_match = re.search(r"基金经理\s*[:：]?\s*([\u4e00-\u9fa5A-Za-z·]{2,20})", cleaned)
    if manager_match:
        parsed["manager"] = manager_match.group(1)

    parsed["code"] = fund_code
    return {key: value for key, value in parsed.items() if value is not None}


def parse_fund_holdings_text(text: str) -> Dict[str, Any]:
    cleaned = _clean_text(text)
    rows = re.split(r"[\r\n]+| {2,}", cleaned)
    holdings: list[str] = []
    weights: list[float] = []

    for row in rows:
        match = re.search(r"(?:^\d+\s*)?([\u4e00-\u9fa5A-Za-z0-9]{2,20})\s+([-+]?\d+(?:\.\d+)?)\s*%", row.strip())
        if not match:
            continue
        name = match.group(1)
        if name in {"序号", "股票名称", "持仓占比", "基金名称"}:
            continue
        weight = parse_percent_value(match.group(2))
        if weight is None:
            continue
        holdings.append(name)
        weights.append(weight)

    return {
        "top_holdings": holdings[:10],
        "top_holdings_weight_pct": round(sum(weights[:10]), 4) if weights else None,
    }


def parse_fund_flow_text(text: str) -> Dict[str, Any]:
    cleaned = _clean_text(text)
    parsed: Dict[str, Any] = {"fund_flow": {}, "sectors": {}}

    for sector_name, flow_field in SECTOR_ALIASES.items():
        row_match = re.search(
            rf"{re.escape(sector_name)}[^\n\r]*?([-+]?\d+(?:,\d{{3}})*(?:\.\d+)?\s*(?:万亿|亿元|亿|万元|万))[^\n\r]*?([-+]?\d+(?:\.\d+)?)\s*%",
            cleaned,
        )
        if not row_match:
            continue
        amount = parse_chinese_amount_to_billion(row_match.group(1))
        change = parse_percent_value(row_match.group(2))
        if amount is not None:
            parsed["fund_flow"][flow_field] = amount
        if change is not None:
            parsed["sectors"].setdefault(sector_name, {})["change_pct"] = change

    return parsed


def has_long_upper_shadow(
    open_price: Optional[float],
    high: Optional[float],
    low: Optional[float],
    close: Optional[float],
) -> Optional[bool]:
    if None in (open_price, high, low, close):
        return None
    day_range = high - low
    if day_range <= 0:
        return None
    upper_shadow = high - max(open_price, close)
    return upper_shadow / day_range >= 0.45


def is_intraday_fade(
    high: Optional[float],
    close: Optional[float],
    previous_close: Optional[float],
) -> Optional[bool]:
    if None in (high, close, previous_close) or previous_close == 0:
        return None
    high_gain = (high - previous_close) / previous_close
    pullback = (high - close) / high if high else 0
    return high_gain > 0.03 and pullback > 0.02


def parse_stock_quote_text(stock_code: str, stock_name: str, theme: str, text: str) -> Dict[str, Any]:
    cleaned = _clean_text(text)
    parsed: Dict[str, Any] = {"code": stock_code, "name": stock_name, "theme": theme}

    _set_if_present(parsed, "change_pct", _parse_labeled_percent(cleaned, ["涨跌幅", "涨幅"]))
    _set_if_present(parsed, "turnover_billion", _parse_labeled_amount(cleaned, ["成交额", "成交金额"]))
    _set_if_present(parsed, "turnover_rate", _parse_labeled_percent(cleaned, ["换手率"]))
    _set_if_present(parsed, "main_inflow_billion", _parse_labeled_amount(cleaned, ["主力净流入", "主力净额"]))
    _set_if_present(parsed, "open", _parse_labeled_number(cleaned, ["今开", "开盘", "开盘价"]))
    _set_if_present(parsed, "high", _parse_labeled_number(cleaned, ["最高", "最高价"]))
    _set_if_present(parsed, "low", _parse_labeled_number(cleaned, ["最低", "最低价"]))
    _set_if_present(parsed, "close", _parse_labeled_number(cleaned, ["收盘", "最新价", "最新价格", "价格"]))
    _set_if_present(parsed, "previous_close", _parse_labeled_number(cleaned, ["昨收", "前收盘", "昨收盘"]))

    change_pct = parsed.get("change_pct")
    if change_pct is not None:
        parsed["limit_up"] = change_pct >= 9.8
        parsed["limit_down"] = change_pct <= -9.8

    long_upper = has_long_upper_shadow(
        parsed.get("open"),
        parsed.get("high"),
        parsed.get("low"),
        parsed.get("close"),
    )
    fade = is_intraday_fade(parsed.get("high"), parsed.get("close"), parsed.get("previous_close"))
    if long_upper is not None:
        parsed["long_upper_shadow"] = long_upper
    if fade is not None:
        parsed["intraday_pullback"] = fade

    return parsed


def parse_lhb_text(stock_code: str, stock_name: str, text: str) -> Dict[str, Any]:
    cleaned = _clean_text(text)
    if not cleaned or (stock_code not in cleaned and stock_name not in cleaned):
        return {}

    parsed: Dict[str, Any] = {"stock_code": stock_code, "stock_name": stock_name, "is_on_lhb": "龙虎榜" in cleaned}
    if not parsed["is_on_lhb"]:
        return {}

    institution = _parse_labeled_amount(cleaned, ["机构专用净买入", "机构净买入", "机构买入净额", "机构席位净买入"])
    hot_money = _parse_labeled_amount(cleaned, ["游资净买入", "知名游资净买入", "营业部净买入"])
    buy_top5 = _parse_labeled_amount(cleaned, ["买入前五合计", "买五合计", "买入金额合计"])
    sell_top5 = _parse_labeled_amount(cleaned, ["卖出前五合计", "卖五合计", "卖出金额合计"])
    net_buy = _parse_last_labeled_amount(cleaned, ["龙虎榜净买入", "净买入", "净买额", "净额"])

    _set_if_present(parsed, "institution_net_buy", institution)
    _set_if_present(parsed, "hot_money_net_buy", hot_money)
    _set_if_present(parsed, "buy_top5_amount", buy_top5)
    _set_if_present(parsed, "sell_top5_amount", sell_top5)
    _set_if_present(parsed, "net_buy_amount", net_buy)

    reason_match = re.search(r"上榜原因\s*[:：]?\s*([^，。；;\n\r]+)", cleaned)
    if reason_match:
        parsed["lhb_reason"] = reason_match.group(1).strip()

    if institution is not None and institution > 0 and hot_money is not None and hot_money > 0:
        parsed["sentiment_tag"] = "机构+游资净买入"
    elif institution is not None and institution > 0:
        parsed["sentiment_tag"] = "机构净买入"
    elif institution is not None and institution < 0:
        parsed["sentiment_tag"] = "机构净卖出"
    elif hot_money is not None and hot_money > 0:
        parsed["sentiment_tag"] = "游资主导"
    elif net_buy is not None and net_buy < 0:
        parsed["sentiment_tag"] = "龙虎榜净卖出"
    else:
        parsed["sentiment_tag"] = "龙虎榜上榜"

    return parsed


POSITIVE_ANNOUNCEMENT_KEYWORDS = {
    "业绩预增": "业绩预增",
    "订单增长": "订单增长",
    "中标": "中标",
    "客户验证通过": "客户验证",
    "扩产": "扩产",
    "国产替代": "国产替代",
    "研发突破": "研发突破",
    "毛利率提升": "毛利率提升",
}

NEGATIVE_ANNOUNCEMENT_KEYWORDS = {
    "减持": "股东减持",
    "业绩预亏": "业绩预亏",
    "风险提示": "风险提示",
    "股价异动": "股价异动",
    "问询函": "问询函",
    "监管函": "监管函",
    "毛利率下降": "毛利率下降",
    "终止项目": "终止项目",
    "诉讼": "诉讼",
}


def _announcement_segment(cleaned: str, code: str, name: str) -> str:
    marker_match = re.search(rf"(?:{re.escape(code)}|{re.escape(name)})", cleaned)
    if not marker_match:
        return ""
    start = max(0, cleaned.rfind("\n", 0, marker_match.start()))
    if start < 0:
        start = max(0, marker_match.start() - 80)
    next_stock = re.search(r"\n\s*\d{4}-\d{2}-\d{2}\s+\d{6}", cleaned[marker_match.end() :])
    end = marker_match.end() + next_stock.start() if next_stock else min(len(cleaned), marker_match.end() + 260)
    return cleaned[start:end].strip()


def parse_announcement_text(text: str, watch_stocks: Dict[str, str] | None = None) -> list[Dict[str, Any]]:
    cleaned = _clean_text(text).replace("。", "。\n")
    watch_stocks = watch_stocks or {}
    announcements: list[Dict[str, Any]] = []

    for code, name in watch_stocks.items():
        segment = _announcement_segment(cleaned, code, name)
        if not segment:
            continue

        positive_types = [event_type for keyword, event_type in POSITIVE_ANNOUNCEMENT_KEYWORDS.items() if keyword in segment]
        negative_types = [event_type for keyword, event_type in NEGATIVE_ANNOUNCEMENT_KEYWORDS.items() if keyword in segment]
        if not positive_types and not negative_types:
            continue

        title_match = re.search(rf"(?:\d{{4}}-\d{{2}}-\d{{2}}\s*)?(?:{re.escape(code)}\s*)?{re.escape(name)}\s*([^\n。；;]{{2,80}})", segment)
        date_match = re.search(r"\d{4}-\d{2}-\d{2}", segment)
        event_types = negative_types + positive_types if negative_types else positive_types
        sentiment = "利好" if positive_types and not negative_types else "利空" if negative_types else "中性"
        importance = 3
        if any(item in event_types for item in ("业绩预增", "订单增长", "客户验证")):
            importance = 4
        if any(item in event_types for item in ("股东减持", "业绩预亏", "风险提示")):
            importance = 5 if "业绩预亏" in event_types else 4

        title = title_match.group(1).strip() if title_match else "公告事件"
        announcements.append(
            {
                "announcement_date": date_match.group(0) if date_match else "",
                "stock_code": code,
                "stock_name": name,
                "title": title,
                "event_type": "、".join(dict.fromkeys(event_types)),
                "sentiment": sentiment,
                "importance": importance,
                "summary": segment[:160],
                "is_earnings_increase": "业绩预增" in segment,
                "is_earnings_loss": "业绩预亏" in segment,
                "is_shareholder_reduce": "减持" in segment,
                "is_risk_warning": "风险提示" in segment or "股价异动" in segment,
                "is_big_order": "订单增长" in segment or "中标" in segment,
                "is_customer_validation": "客户验证通过" in segment,
                "source": "",
                "raw_text": segment,
            }
        )

    return announcements


def _log_parsed(fetch_logger: DataFetchLogger | None, source_name: str, parsed: Dict[str, Any], entity: str = "") -> None:
    if not fetch_logger:
        return
    fields = [field for field, value in parsed.items() if field not in {"code", "name", "theme"} and value is not None and value != []]
    fetch_logger.parsed_fields(source_name, fields, entity=entity)


def apply_raw_text_to_context(context, raw_text: Dict[str, str], source_label: str, history_store=None, fetch_logger: DataFetchLogger | None = None):
    parsed_any = False

    for source_key in ("eastmoney_sector_fund_flow", "ths_industry_flow"):
        text = raw_text.get(source_key, "")
        if not text:
            context.field_sources[f"raw.{source_key}"] = "missing"
            continue
        parsed = parse_fund_flow_text(text)
        _log_parsed(fetch_logger, source_key, {**parsed.get("fund_flow", {}), **{f"sector.{k}.{sf}": sv for k, v in parsed.get("sectors", {}).items() for sf, sv in v.items()}})
        for field_name, value in parsed.get("fund_flow", {}).items():
            setattr(context.fund_flow, field_name, value)
            context.field_sources[f"fund_flow.{field_name}"] = source_label
            parsed_any = True
        for sector_name, sector_values in parsed.get("sectors", {}).items():
            sector = next((item for item in context.sectors if item.name == sector_name), None)
            if sector:
                for field_name, value in sector_values.items():
                    setattr(sector, field_name, value)
                    context.field_sources[f"sector.{sector_name}.{field_name}"] = source_label
                    parsed_any = True

    for fund_code in ("020671", "025500"):
        fund = next((item for item in context.funds if item.code == fund_code), None)
        if not fund:
            continue

        fund_text = raw_text.get(f"fund_{fund_code}", "")
        if fund_text:
            parsed_fund_nav = parse_fund_nav_text(fund_code, fund_text)
            _log_parsed(fetch_logger, f"fund_{fund_code}", parsed_fund_nav, entity=fund_code)
            for field_name, value in parsed_fund_nav.items():
                if hasattr(fund, field_name) and field_name != "code":
                    setattr(fund, field_name, value)
                    context.field_sources[f"fund.{fund_code}.{field_name}"] = source_label
                    parsed_any = True
        else:
            context.field_sources[f"raw.fund_{fund_code}"] = "missing"

        holdings_text = raw_text.get(f"fund_{fund_code}_holdings", "")
        if holdings_text:
            parsed_holdings = parse_fund_holdings_text(holdings_text)
            _log_parsed(fetch_logger, f"fund_{fund_code}_holdings", parsed_holdings, entity=fund_code)
            for field_name, value in parsed_holdings.items():
                if value:
                    setattr(fund, field_name, value)
                    context.field_sources[f"fund.{fund_code}.{field_name}"] = source_label
                    parsed_any = True
        else:
            context.field_sources[f"raw.fund_{fund_code}_holdings"] = "missing"

    for etf in context.etfs:
        text = raw_text.get(f"etf_eastmoney_{etf.code}") or raw_text.get(f"etf_fund_{etf.code}") or raw_text.get(f"etf_10jqka_{etf.code}", "")
        if not text:
            context.field_sources[f"raw.etf_{etf.code}"] = "missing"
            continue

        parsed = parse_etf_quote_text(etf.code, etf.name, text)
        _log_parsed(fetch_logger, f"etf_{etf.code}", parsed, entity=f"{etf.code} {etf.name}")
        for field_name, value in parsed.items():
            if field_name in {"code", "name"}:
                continue
            if hasattr(etf, field_name):
                setattr(etf, field_name, value)
                context.field_sources[f"etf.{etf.code}.{field_name}"] = source_label
                parsed_any = True

        if history_store and "latest_price" in parsed:
            history_store.record_price(etf.code, context.analysis_date, etf.latest_price)
            ma_state = history_store.calculate_ma_state(etf.code, etf.latest_price)
            if ma_state.get("status") == "ok":
                for field_name in ("ma5", "ma10", "ma20", "pullback_ma5", "pullback_ma10", "below_ma10", "below_ma20"):
                    value = ma_state.get(field_name)
                    if value is not None:
                        setattr(etf, field_name, value)
                        context.field_sources[f"etf.{etf.code}.{field_name}"] = source_label
            else:
                for field_name in ("ma5", "ma10", "ma20", "pullback_ma5", "pullback_ma10", "below_ma10", "below_ma20"):
                    setattr(etf, field_name, None if field_name.startswith("ma") else False)
                    context.field_sources[f"etf.{etf.code}.{field_name}"] = "insufficient_history"

    for stock in context.stocks:
        text = raw_text.get(f"stock_eastmoney_{stock.code}") or raw_text.get(f"stock_10jqka_{stock.code}", "")
        if not text:
            context.field_sources[f"raw.stock_{stock.code}"] = "missing"
        else:
            parsed = parse_stock_quote_text(stock.code, stock.name, stock.theme, text)
            _log_parsed(fetch_logger, f"stock_{stock.code}", parsed, entity=f"{stock.code} {stock.name}")
            field_mapping = {
                "open": "open_price",
                "high": "high",
                "low": "low",
                "close": "close",
                "previous_close": "previous_close",
                "change_pct": "change_pct",
                "turnover_billion": "turnover_billion",
                "turnover_rate": "turnover_rate",
                "main_inflow_billion": "main_inflow_billion",
                "limit_up": "limit_up",
                "limit_down": "limit_down",
                "long_upper_shadow": "long_upper_shadow",
                "intraday_pullback": "intraday_pullback",
            }
            for parsed_field, context_field in field_mapping.items():
                if parsed_field in parsed and hasattr(stock, context_field):
                    setattr(stock, context_field, parsed[parsed_field])
                    context.field_sources[f"stock.{stock.code}.{context_field}"] = source_label
                    parsed_any = True

            if history_store and parsed.get("close") is not None:
                history_store.record_stock_quote(
                    stock.code,
                    context.analysis_date,
                    {
                        "stock_name": stock.name,
                        "open": parsed.get("open"),
                        "high": parsed.get("high"),
                        "low": parsed.get("low"),
                        "close": parsed.get("close"),
                        "previous_close": parsed.get("previous_close"),
                        "pct_chg": parsed.get("change_pct"),
                        "amount": parsed.get("turnover_billion"),
                        "turnover": parsed.get("turnover_rate"),
                    },
                )
                ma_state = history_store.calculate_stock_ma_state(stock.code, parsed.get("close"))
                for field_name in ("ma5", "ma10", "below_ma5", "below_ma10"):
                    value = ma_state.get(field_name)
                    if value is not None:
                        setattr(stock, field_name, value)
                    elif field_name in {"ma5", "ma10"}:
                        setattr(stock, field_name, None)
                    else:
                        setattr(stock, field_name, False)
                    source = ma_state.get(f"{field_name}_status") if field_name in {"ma5", "ma10"} else None
                    if field_name == "below_ma5":
                        source = ma_state.get("ma5_status")
                    if field_name == "below_ma10":
                        source = ma_state.get("ma10_status")
                    context.field_sources[f"stock.{stock.code}.{field_name}"] = source_label if source == "ok" else "insufficient_history"
                    parsed_any = True

        lhb_text = raw_text.get(f"stock_lhb_{stock.code}") or raw_text.get("ths_lhb") or raw_text.get("eastmoney_lhb", "")
        lhb = parse_lhb_text(stock.code, stock.name, lhb_text)
        if lhb:
            _log_parsed(fetch_logger, f"lhb_{stock.code}", lhb, entity=f"{stock.code} {stock.name}")
            lhb_mapping = {
                "is_on_lhb": "on_lhb",
                "institution_net_buy": "institution_net_buy_billion",
                "hot_money_net_buy": "hot_money_net_buy_billion",
                "buy_top5_amount": "buy_top5_amount_billion",
                "sell_top5_amount": "sell_top5_amount_billion",
                "net_buy_amount": "net_buy_amount_billion",
                "lhb_reason": "lhb_reason",
                "sentiment_tag": "sentiment_tag",
            }
            for parsed_field, context_field in lhb_mapping.items():
                if parsed_field in lhb and hasattr(stock, context_field):
                    setattr(stock, context_field, lhb[parsed_field])
                    context.field_sources[f"stock.{stock.code}.{context_field}"] = source_label
                    parsed_any = True
        else:
            context.field_sources.setdefault(f"stock.{stock.code}.on_lhb", "missing")

    announcement_text = "\n".join(
        raw_text.get(key, "")
        for key in ("cninfo", "eastmoney_announcements", "ths_announcements")
        if raw_text.get(key)
    )
    watch_stocks = {stock.code: stock.name for stock in context.stocks}
    parsed_announcements = parse_announcement_text(announcement_text, watch_stocks=watch_stocks)
    if parsed_announcements:
        from .context import Announcement

        context.announcements = []
        for item in parsed_announcements:
            _log_parsed(fetch_logger, "announcements", item, entity=f"{item['stock_code']} {item['stock_name']}")
            ann = Announcement(
                title=item["title"],
                date=item["announcement_date"] or context.analysis_date,
                stock_code=item["stock_code"],
                stock_name=item["stock_name"],
                announcement_type=item["event_type"],
                event_type=item["event_type"],
                sentiment=item["sentiment"],
                importance=item["importance"],
                earnings_up=item["is_earnings_increase"],
                earnings_down=item["is_earnings_loss"],
                shareholder_reduce=item["is_shareholder_reduce"],
                major_order=item["is_big_order"],
                risk_warning=item["is_risk_warning"],
                customer_validation=item["is_customer_validation"],
                summary=item["summary"],
                impact_direction=item["sentiment"],
                impact_strength=item["importance"],
                source=source_label,
                raw_text=item["raw_text"],
            )
            context.announcements.append(ann)
            for field_name in (
                "title",
                "event_type",
                "sentiment",
                "importance",
                "is_earnings_increase",
                "is_earnings_loss",
                "is_shareholder_reduce",
                "is_risk_warning",
                "is_big_order",
                "is_customer_validation",
            ):
                context.field_sources[f"announcement.{ann.stock_code}.{field_name}"] = source_label
            parsed_any = True
    else:
        context.field_sources.setdefault("announcement.raw_text", "missing")

    if not parsed_any:
        context.warnings.append("真实网页raw_text未解析出结构化字段，保留mock_fallback字段。")
    return context
