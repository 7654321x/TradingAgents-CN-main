from datetime import datetime
from pathlib import Path
from typing import Iterable, Mapping

from .context import Announcement, EtfObservation, FundHolding, SectorFundContext, SectorPerformance, StockObservation


def _value(value, suffix: str = "") -> str:
    if value is None:
        return "未获取到"
    if isinstance(value, float):
        return f"{value:.2f}{suffix}"
    return f"{value}{suffix}"


def _join(items: Iterable[str]) -> str:
    rows = [item for item in items if item]
    return "、".join(rows) if rows else "未获取到"


def _source(context: SectorFundContext, field_name: str) -> str:
    return context.field_sources.get(field_name, "missing")


def _is_mock_or_low_coverage(context: SectorFundContext) -> bool:
    coverage = (context.data_quality or {}).get("real_coverage_rate", 0.0)
    return context.source_mode == "mock" or coverage < 40


def _source_suffix(source: str) -> str:
    if source == "mock_fallback":
        return "（mock）"
    if source == "firecrawl_raw":
        return "（firecrawl_raw）"
    if source == "real_data":
        return "（real_data）"
    return ""


def _value_with_source(value, source: str, suffix: str = "") -> str:
    return f"{_value(value, suffix)}{_source_suffix(source)}"


def _score_value(value, context: SectorFundContext) -> str:
    if _is_mock_or_low_coverage(context):
        return f"{value}（mock，仅流程验证）"
    return str(value)


def _mock_warning(context: SectorFundContext) -> str:
    if _is_mock_or_low_coverage(context):
        return "【重要提示】当前为模拟/兜底报告，真实解析字段较低，仅用于流程验证，不代表真实市场。\n"
    return ""


def _is_trading_day(date_text: str) -> bool:
    try:
        return datetime.strptime(date_text, "%Y-%m-%d").weekday() < 5
    except ValueError:
        return False


def _date_status_lines(context: SectorFundContext) -> str:
    report_date = context.report_date or context.analysis_date
    data_date = context.data_date or "未获取到真实数据日期"
    lines = [f"- 报告生成日期：{report_date}", f"- 数据日期：{data_date}"]
    if not _is_trading_day(report_date):
        lines.append("- 日期提示：非交易日，应使用最近交易日数据。")
    if not context.data_date:
        lines.append("- 数据提示：未获取到真实数据日期，正文不按真实今日行情解读。")
    return "\n".join(lines)


def _bool_with_source(value: bool | None, source: str) -> str:
    if source == "insufficient_history":
        return "历史数据不足，无法判断"
    if source == "missing" or value is None:
        return "未获取到"
    if source == "mock_fallback":
        return "mock示例，不作为操作依据"
    return "是" if value else "否"


def _ma_judgement(value: bool | None, source: str) -> str:
    if source == "insufficient_history":
        return "历史数据不足，无法判断"
    if source == "missing" or value is None:
        return "无法判断"
    if source == "mock_fallback":
        return "mock示例，不作为操作依据"
    return "是" if value else "否"


def _sector_lines(sectors: list[SectorPerformance], context: SectorFundContext) -> str:
    return "\n".join(
        f"- {sector.name}：涨跌幅{_value_with_source(sector.change_pct, _source(context, f'sector.{sector.name}.change_pct'), '%')}，"
        f"近5日{_value_with_source(sector.change_5d_pct, _source(context, f'sector.{sector.name}.change_5d_pct'), '%')}，"
        f"成交额{_value_with_source(sector.turnover_billion, _source(context, f'sector.{sector.name}.turnover_billion'), '亿元')}，"
        f"领涨 {_join(sector.leading_stocks)}，领跌 {_join(sector.lagging_stocks)}。"
        for sector in sectors
    )


def _stock_group_lines(stocks: list[StockObservation], context: SectorFundContext) -> str:
    groups: dict[str, list[StockObservation]] = {}
    for stock in stocks:
        groups.setdefault(stock.theme, []).append(stock)

    lines: list[str] = []
    for theme, rows in groups.items():
        strong = [
            f"{stock.name}({_value_with_source(stock.change_pct, _source(context, f'stock.{stock.code}.change_pct'), '%')})"
            for stock in rows
            if (stock.change_pct or 0) > 3
        ]
        weak = [
            f"{stock.name}({_value_with_source(stock.change_pct, _source(context, f'stock.{stock.code}.change_pct'), '%')})"
            for stock in rows
            if stock.below_ma10 or (stock.change_pct or 0) < -3
        ]
        risks = [
            f"{stock.name}(长上影:{_bool_with_source(stock.long_upper_shadow, _source(context, f'stock.{stock.code}.long_upper_shadow'))}, "
            f"冲高回落:{_bool_with_source(stock.intraday_pullback, _source(context, f'stock.{stock.code}.intraday_pullback'))}, "
            f"跌破MA5:{_ma_judgement(stock.below_ma5, _source(context, f'stock.{stock.code}.below_ma5'))}, "
            f"跌破MA10:{_ma_judgement(stock.below_ma10, _source(context, f'stock.{stock.code}.below_ma10'))}, "
            f"来源:{_source(context, f'stock.{stock.code}.change_pct')})"
            for stock in rows
            if stock.long_upper_shadow or stock.intraday_pullback or stock.below_ma5 or stock.below_ma10
        ]
        lhb_rows = [
            f"{stock.name}(龙虎榜:{_bool_with_source(stock.on_lhb, _source(context, f'stock.{stock.code}.on_lhb'))}, "
            f"机构净买:{_value_with_source(stock.institution_net_buy_billion, _source(context, f'stock.{stock.code}.institution_net_buy_billion'), '亿元')}，"
            f"游资净买:{_value_with_source(stock.hot_money_net_buy_billion, _source(context, f'stock.{stock.code}.hot_money_net_buy_billion'), '亿元')}，"
            f"净买额:{_value_with_source(stock.net_buy_amount_billion, _source(context, f'stock.{stock.code}.net_buy_amount_billion'), '亿元')}，"
            f"标签:{stock.sentiment_tag or '未获取到'})"
            for stock in rows
            if stock.on_lhb or stock.sentiment_tag
        ]
        ma_rows = [
            f"{stock.name}(MA5={_value(stock.ma5)}，MA10={_value(stock.ma10)}，"
            f"跌破MA5={_ma_judgement(stock.below_ma5, _source(context, f'stock.{stock.code}.below_ma5'))}，"
            f"跌破MA10={_ma_judgement(stock.below_ma10, _source(context, f'stock.{stock.code}.below_ma10'))})"
            for stock in rows
        ]
        lines.append(
            f"- {theme}：强势股 {_join(strong)}；走弱股 {_join(weak)}；"
            f"MA5/MA10 {_join(ma_rows)}；龙虎榜/机构游资 {_join(lhb_rows)}；"
            f"长上影/炸板/跌破MA风险 {_join(risks)}。"
        )
    return "\n".join(lines)


def _etf_lines(etfs: list[EtfObservation], context: SectorFundContext) -> str:
    return "\n".join(
        f"- {etf.code} {etf.name}：价格{_value_with_source(etf.latest_price, _source(context, f'etf.{etf.code}.latest_price'))}，"
        f"涨跌幅{_value_with_source(etf.change_pct, _source(context, f'etf.{etf.code}.change_pct'), '%')}，"
        f"成交额{_value_with_source(etf.turnover_billion, _source(context, f'etf.{etf.code}.turnover_billion'), '亿元')}，"
        f"换手率{_value_with_source(etf.turnover_rate, _source(context, f'etf.{etf.code}.turnover_rate'), '%')}，"
        f"MA5={_value_with_source(etf.ma5, _source(context, f'etf.{etf.code}.ma5'))}，"
        f"MA10={_value_with_source(etf.ma10, _source(context, f'etf.{etf.code}.ma10'))}，"
        f"MA20={_value_with_source(etf.ma20, _source(context, f'etf.{etf.code}.ma20'))}，"
        f"回踩MA5={_ma_judgement(etf.pullback_ma5, _source(context, f'etf.{etf.code}.pullback_ma5'))}，"
        f"回踩MA10={_ma_judgement(etf.pullback_ma10, _source(context, f'etf.{etf.code}.pullback_ma10'))}，"
        f"跌破MA10={_ma_judgement(etf.below_ma10, _source(context, f'etf.{etf.code}.below_ma10'))}，"
        f"跌破MA20={_ma_judgement(etf.below_ma20, _source(context, f'etf.{etf.code}.below_ma20'))}，"
        f"字段来源={_source(context, f'etf.{etf.code}.latest_price')}。"
        for etf in etfs
    )


def _low_quality(score: Mapping[str, object]) -> bool:
    return score.get("data_quality_gate") == "low"


def _medium_quality(score: Mapping[str, object]) -> bool:
    return score.get("data_quality_gate") == "medium"


def _fund_lines(funds: list[FundHolding], score: Mapping[str, object], context: SectorFundContext) -> str:
    lines = []
    low_quality = _low_quality(score)
    for fund in funds:
        if low_quality:
            action = "持有观察；真实数据覆盖率较低时先人工核对，不根据本报告扩大仓位。"
        elif _medium_quality(score):
            action = "持有观察，等待资金、均线和龙头股信号进一步确认。"
        elif fund.position_role == "base":
            action = "持有为主；若科创芯片ETF回踩MA5/MA10不破，可考虑谨慎小仓跟踪；跌破MA20则观察。"
        else:
            action = "继续观察强度；若存储链长上影、炸板和资金流出增多，可止盈一部分进攻仓。"
        lines.append(
            f"### {fund.code} {fund.name}\n"
            f"- 净值：{_value_with_source(fund.unit_nav, _source(context, f'fund.{fund.code}.unit_nav'))}\n"
            f"- 涨跌：{_value_with_source(fund.daily_change_pct, _source(context, f'fund.{fund.code}.daily_change_pct'), '%')}；"
            f"近1周：{_value_with_source(fund.week_change_pct, _source(context, f'fund.{fund.code}.week_change_pct'), '%')}；"
            f"近1月：{_value_with_source(fund.month_change_pct, _source(context, f'fund.{fund.code}.month_change_pct'), '%')}\n"
            f"- 前十大持仓：{_join(fund.top_holdings)}{_source_suffix(_source(context, f'fund.{fund.code}.top_holdings'))}；"
            f"占比：{_value_with_source(fund.top_holdings_weight_pct, _source(context, f'fund.{fund.code}.top_holdings_weight_pct'), '%')}\n"
            f"- 基金规模：{_value_with_source(fund.size_billion, _source(context, f'fund.{fund.code}.size_billion'), '亿元')}；"
            f"基金经理：{fund.manager or '未获取到'}{_source_suffix(_source(context, f'fund.{fund.code}.manager'))}\n"
            f"- 判断：{action}"
        )
    return "\n\n".join(lines)


def _announcement_item_lines(announcements: list[Announcement], simulated: bool = False) -> str:
    return "\n".join(
        f"- {'【模拟】' if simulated else ''}{ann.date} {ann.stock_name or ann.stock_code}：{ann.title}。类型：{ann.announcement_type or '未获取到'}；"
        f"方向：{ann.impact_direction}；强度：{ann.impact_strength}/5；摘要：{ann.summary or '未获取到'}"
        for ann in announcements
    ) or "- 未获取到"


def _announcement_lines(announcements: list[Announcement], funds: list[FundHolding], context: SectorFundContext) -> str:
    simulated = _is_mock_or_low_coverage(context) or not any(
        context.field_sources.get(f"announcement.{ann.stock_code}.title") in {"real_data", "firecrawl_raw"}
        for ann in announcements
    )
    positive = [ann for ann in announcements if (ann.sentiment or ann.impact_direction) == "利好"]
    negative = [ann for ann in announcements if (ann.sentiment or ann.impact_direction) == "利空"]
    fund_holdings = {holding for fund in funds for holding in fund.top_holdings}

    def affected_fund_hint(ann: Announcement) -> str:
        if ann.stock_name in fund_holdings:
            return "影响020671/025500重仓方向：是"
        if ann.stock_name and any(keyword in ann.stock_name for keyword in ("芯片", "半导体", "存储")):
            return "影响020671/025500重仓方向：可能"
        return "影响020671/025500重仓方向：未确认"

    detail = "\n".join(
        f"- {'【模拟】' if simulated else ''}{ann.date} {ann.stock_name or ann.stock_code}：{ann.title}；"
        f"类型：{ann.event_type or ann.announcement_type or '未获取到'}；"
        f"方向：{ann.sentiment or ann.impact_direction}；强度：{ann.importance or ann.impact_strength}/5；"
        f"{affected_fund_hint(ann)}；摘要：{ann.summary or '未获取到'}"
        for ann in announcements
    ) or "- 未获取到"

    prefix = "未获取到真实公告，本节为mock示例。\n\n" if simulated else ""
    return (
        prefix +
        "利好公告：\n"
        f"{_announcement_item_lines(positive, simulated=simulated)}\n\n"
        "利空公告：\n"
        f"{_announcement_item_lines(negative, simulated=simulated)}\n\n"
        "公告明细：\n"
        f"{detail}"
    )


def _field_source_lines(context: SectorFundContext) -> str:
    source_names = ("real_data", "firecrawl_raw", "mock_fallback", "missing", "insufficient_history")
    counts = {name: 0 for name in source_names}
    for source in context.field_sources.values():
        if source in counts:
            counts[source] += 1
    return "\n".join(f"- {name}: {counts[name]}" for name in source_names)


def _field_source_details(context: SectorFundContext) -> str:
    details = "\n".join(
        f"- {field_name}: {source}"
        for field_name, source in sorted(context.field_sources.items())
        if source in {"real_data", "firecrawl_raw", "mock_fallback", "missing", "insufficient_history"}
    )
    if not details:
        return ""
    return f"<details>\n<summary>字段来源附录（调试）</summary>\n\n{details}\n</details>"


def _data_quality_lines(context: SectorFundContext) -> str:
    quality = context.data_quality or {}
    real_count = quality.get("real_field_count", 0)
    mock_count = quality.get("mock_field_count", 0)
    missing_count = quality.get("missing_field_count", 0)
    coverage = quality.get("real_coverage_rate", 0.0)
    level = quality.get("data_quality_level", "较低")
    warning = ""
    if coverage < 40:
        warning = "\n- 提示：当前真实结构化字段覆盖率较低，本报告更适合验证流程，不建议作为实盘决策依据。"
    return (
        "【数据可信度】\n"
        f"- 真实解析字段：{real_count}\n"
        f"- mock兜底字段：{mock_count}\n"
        f"- 缺失字段：{missing_count}\n"
        f"- 真实覆盖率：{coverage:.2f}%\n"
        f"- 数据质量：{level}"
        f"{warning}"
    )



def _delta_text(delta) -> str:
    if delta is None:
        return "无可比历史"
    sign = "+" if delta > 0 else ""
    return f"{sign}{delta:.0f}"


def _score_change_lines(context: SectorFundContext) -> str:
    summary = context.history_summary or {}
    previous = summary.get("previous") or {}
    return (
        f"- 半导体评分：今日 {summary.get('recent_records', [{}])[-1].get('semiconductor_score', '未获取到') if summary.get('recent_records') else '未获取到'}，"
        f"昨日 {previous.get('semiconductor_score', '无可比历史')}，变化 {_delta_text(summary.get('semiconductor_delta'))}\n"
        f"- 存储评分：今日 {summary.get('recent_records', [{}])[-1].get('storage_score', '未获取到') if summary.get('recent_records') else '未获取到'}，"
        f"昨日 {previous.get('storage_score', '无可比历史')}，变化 {_delta_text(summary.get('storage_delta'))}\n"
        f"- 风险等级变化：{summary.get('risk_change', '无可比历史')}\n"
        f"- 数据质量变化：{summary.get('data_quality_change', '无可比历史')}"
    )


def _signal_change_lines(context: SectorFundContext) -> str:
    summary = context.history_summary or {}
    return (
        f"- 趋势信号：{summary.get('trend_signal', '稳定')}\n"
        f"- 资金信号：{summary.get('fund_flow_signal', '数据不足')}\n"
        f"- 龙头股信号：{summary.get('leader_signal', '分化')}\n"
        f"- 公告风险：{summary.get('announcement_risk', '无明显变化')}\n"
        f"- 操作信号变化：{summary.get('operation_change', '无明显变化')}\n"
        f"- 标签：{_join(summary.get('change_tags', []))}"
    )


def _sequence_text(values) -> str:
    rows = ["未获取到" if value is None else f"{value}" for value in values or []]
    return " / ".join(rows) if rows else "无历史记录"


def _coverage_sequence_text(values) -> str:
    values = values or []
    if len(values) < 3:
        formatted = " / ".join(f"{float(value):.2f}%" for value in values) if values else "无历史记录"
        return f"历史记录不足3次（{formatted}）"
    return " / ".join(f"{float(value):.2f}%" for value in values[-3:])


def _continuous_lines(context: SectorFundContext) -> str:
    summary = context.history_summary or {}
    return (
        f"- 最近3次半导体评分：{_sequence_text((summary.get('recent_semiconductor_scores') or [])[-3:])}\n"
        f"- 最近3次存储评分：{_sequence_text((summary.get('recent_storage_scores') or [])[-3:])}\n"
        f"- 最近3次真实覆盖率：{_coverage_sequence_text(summary.get('recent_real_coverage_rates') or [])}\n"
        f"- 是否连续转弱：{'是' if summary.get('continuous_weakening') else '否'}\n"
        f"- 是否连续增强：{'是' if summary.get('continuous_improving') else '否'}"
    )


def _etf_action_line(score: Mapping[str, object]) -> str:
    if _low_quality(score):
        return "- ETF动作观察：真实数据覆盖率较低，先做人工核对，暂不根据本报告扩大仓位。"
    if _medium_quality(score):
        return "- ETF动作观察：持有观察，等待资金、均线和龙头股信号确认。"
    return "- ETF动作观察：只在回踩MA5/MA10不破、资金未转流出、核心股未集体走弱时考虑谨慎小仓跟踪。"


def _strategy_lines(score: Mapping[str, object]) -> str:
    if _low_quality(score):
        return "\n".join([
            "- 开盘快速冲高：不追，先人工核对真实行情和资金流。",
            "- 低开后修复：只观察，不根据低覆盖率报告扩大仓位。",
            "- 尾盘站稳：等待下一次真实数据覆盖率改善后再评估。",
            "- 放量跌破MA10：不补仓，优先控制进攻仓波动。",
            "- 025500观察：若存储链长上影、炸板和资金流出增多，可降低进攻仓波动敞口。",
            "- 020671观察：作为底仓继续复盘，关键结论需人工核对。",
        ])
    if _medium_quality(score):
        return "\n".join([
            "- 开盘快速冲高：不追，先看量能和龙头股是否放量承接。",
            "- 低开后修复：10:30 前后观察半导体ETF、科创芯片ETF能否收回MA5。",
            "- 尾盘站稳：持有观察，等待真实字段覆盖率和资金信号进一步确认。",
            "- 放量跌破MA10：不补仓，优先降低025500这类进攻仓波动。",
            "- 025500是否需要止盈：若存储链连续大涨后长上影、炸板、资金流出增多，可止盈一部分。",
            "- 020671是否继续做底仓：除非科创芯片跌破MA20且资金明显流出，否则不建议轻易清仓。",
        ])
    return "\n".join([
        "- 开盘快速冲高：不建议追，先看量能和龙头股是否放量承接。",
        "- 低开后修复：10:30 前后观察半导体ETF、科创芯片ETF能否收回MA5。",
        "- 尾盘站稳：若MA5/MA10不破且资金流仍为正，可考虑谨慎小仓跟踪。",
        "- 放量跌破MA10：不补仓，优先降低025500这类进攻仓波动。",
        "- 025500是否需要止盈：若存储链连续大涨后长上影、炸板、资金流出增多，可止盈一部分。",
        "- 020671是否继续做底仓：除非科创芯片跌破MA20且资金明显流出，否则不建议轻易清仓。",
    ])


def _position_guidance(profile: Mapping[str, object], score: Mapping[str, object]) -> str:
    if _low_quality(score):
        return "真实数据覆盖率较低，暂不依据本报告调整仓位。"
    if _medium_quality(score):
        return f"持有观察，目标仓位仍需等待确认；配置区间参考 {profile.get('target_position_conservative', 0):.0%}-{profile.get('target_position_aggressive', 0):.0%}。"
    return f"{profile.get('target_position_conservative', 0):.0%}-{profile.get('target_position_aggressive', 0):.0%}"


def _reading_guide_lines() -> str:
    return "\n".join([
        "- 先看数据可信度，真实覆盖率低于40%时不要用于操作。",
        "- 再看评分变化，连续转弱比单日分数更重要。",
        "- 再看资金流和龙头股风险，确认是否出现分化。",
        "- ETF MA5/MA10 历史不足时，不要依据回踩结论操作。",
        "- 025500 是进攻仓，波动更大；020671 是底仓，优先稳定。",
        "- 本报告只是辅助工具，不构成投资建议。",
    ])


def _manual_checklist_lines() -> str:
    return "\n".join([
        "- 东方财富板块资金流是否与报告一致。",
        "- 同花顺行业资金流是否与报告一致。",
        "- 020671 天天基金净值是否一致。",
        "- 025500 天天基金净值是否一致。",
        "- 512480 / 159995 ETF 是否接近报告价格。",
        "- 龙头股是否真的出现长上影或跌破MA10。",
        "- 是否有重大公告遗漏。",
        "- 数据覆盖率是否足够。",
    ])


def _final_command(score: Mapping[str, object]) -> str:
    if _low_quality(score):
        return "真实数据覆盖率较低，先做流程验证和人工核对；已有仓位以持有观察为主，不根据本报告扩大仓位。"
    if _medium_quality(score):
        return "已有仓位持有观察，不开盘追；等待资金、均线和龙头股信号进一步确认。025500作为进攻仓，若存储链长上影和炸板增多，可止盈一部分。"
    return "已有仓位持有，不开盘追；低开修复看10:30，尾盘站稳MA5/MA10再考虑谨慎小仓跟踪。025500作为进攻仓，若存储长上影和炸板增多，可止盈一部分。020671作为底仓，除非科创芯片跌破MA20，否则不建议轻易清仓。"

def render_sector_fund_report(context: SectorFundContext, score: Mapping[str, object]) -> str:
    profile = context.profile
    strongest = max(context.sectors, key=lambda item: item.change_pct or -999)
    weak_or_hot = [sector.name for sector in context.sectors if (sector.change_5d_pct or 0) > 10 or (sector.change_pct or 0) < 0]
    disclaimer = "本报告仅用于个人研究和复盘，不构成投资建议，不包含自动交易或确定性收益承诺。市场有风险，决策需自行承担。"

    body = f"""{_mock_warning(context)}## 1. 今日总判断
{_date_status_lines(context)}
- 半导体评分：{_score_value(score['semiconductor_score'], context)}
- 存储芯片评分：{_score_value(score['storage_score'], context)}
- 公告分：{score.get('announcement_score', 0)}
- 情绪分：{score.get('emotion_score', 0)}
- 状态：{score['status']}
- 风险等级：{score['risk_level']}
- 结论：半导体/存储仍偏强，但短线波动和分化需要观察。
- 操作建议：{score['suggestion']}
- 免责声明：{disclaimer}

## 2. 大盘环境
- 上证指数：{_value(context.market.shanghai_change_pct, '%')}
- 深成指：{_value(context.market.shenzhen_change_pct, '%')}
- 创业板指：{_value(context.market.chinext_change_pct, '%')}
- 科创50：{_value(context.market.star50_change_pct, '%')}
- 沪深300：{_value(context.market.csi300_change_pct, '%')}
- 全市场成交额：{_value(context.market.total_turnover_billion, '亿元')}
- 上涨/下跌家数：{_value(context.market.advancing_count)} / {_value(context.market.declining_count)}
- 判断：成长方向有进攻条件，但若成交额缩量或下跌家数扩大，应降低追高动作。

## 3. 板块表现
{_sector_lines(context.sectors, context)}

- 最强方向：{strongest.name}
- 分化/过热观察：{_join(weak_or_hot)}
- 主线判断：若半导体、存储芯片、AI芯片同时维持资金流入，仍按科技主线观察。

## 4. 资金流向
- 半导体主力净流入：{_value_with_source(context.fund_flow.semiconductor_main_inflow_billion, _source(context, 'fund_flow.semiconductor_main_inflow_billion'), '亿元')}
- 存储芯片主力净流入：{_value_with_source(context.fund_flow.storage_main_inflow_billion, _source(context, 'fund_flow.storage_main_inflow_billion'), '亿元')}
- 电子行业主力净流入：{_value_with_source(context.fund_flow.electronics_main_inflow_billion, _source(context, 'fund_flow.electronics_main_inflow_billion'), '亿元')}
- 芯片概念主力净流入：{_value_with_source(context.fund_flow.chip_main_inflow_billion, _source(context, 'fund_flow.chip_main_inflow_billion'), '亿元')}
- 5日/10日资金连续性：{_value_with_source(context.fund_flow.five_day_inflow_billion, _source(context, 'fund_flow.five_day_inflow_billion'), '亿元')} / {_value_with_source(context.fund_flow.ten_day_inflow_billion, _source(context, 'fund_flow.ten_day_inflow_billion'), '亿元')}
- 资金判断：当前按连续流入处理；若上涨但资金转流出，应视为分歧升温。

## 5. 龙头股观察
{_stock_group_lines(context.stocks, context)}

## 6. ETF回踩观察
{_etf_lines(context.etfs, context)}

{_etf_action_line(score)}

## 7. 我的基金持仓
{_fund_lines(context.funds, score, context)}

- 当前科技仓位：{profile.get('current_tech_position', 0):.0%}
- 建议目标仓位：{_position_guidance(profile, score)}
- 是否建议超过{profile.get('max_recommended_position', 0):.0%}：不建议。

## 8. 公告与新闻风险
{_announcement_lines(context.announcements, context.funds, context)}

- 重要利好：关注重大订单、国产替代、产业政策。
- 重要利空：关注减持、业绩预亏、风险提示和高位放量分歧。
- 对板块影响：利好强化主线，利空会优先冲击进攻仓弹性。

## 【评分变化】
{_score_change_lines(context)}

## 【信号变化】
{_signal_change_lines(context)}

## 【连续观察】
{_continuous_lines(context)}

## 9. 下个交易日策略
{_strategy_lines(score)}

## 10. 最终操作口令
{_final_command(score)}

## 数据源状态
{chr(10).join(f"- {name}: {status}" for name, status in sorted(context.source_status.items())) or "- 未获取到"}

{_data_quality_lines(context)}

字段来源：
{_field_source_lines(context)}

{_field_source_details(context)}

## 【如何阅读本报告】
{_reading_guide_lines()}

## 【人工复核清单】
{_manual_checklist_lines()}

## 免责声明
{disclaimer}
"""

    template_path = Path("templates/sector_fund_report.md")
    if template_path.exists():
        return template_path.read_text(encoding="utf-8").replace("{{body}}", body)
    return "# 【A股半导体/存储板块与个人基金持仓趋势报告】\n\n" + body


def save_sector_fund_report(
    report: str,
    output_dir: str | Path = "reports/sector_fund",
    analysis_date: str | None = None,
) -> Path:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    date_part = analysis_date or datetime.now().strftime("%Y-%m-%d")
    file_path = output_path / f"sector_fund_report_{date_part}.md"
    file_path.write_text(report, encoding="utf-8")
    return file_path
