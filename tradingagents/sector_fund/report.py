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


def _bool_with_source(value: bool | None, source: str) -> str:
    if source == "insufficient_history":
        return "历史数据不足，无法判断"
    if source == "missing" or value is None:
        return "未获取到"
    return "是" if value else "否"


def _sector_lines(sectors: list[SectorPerformance]) -> str:
    return "\n".join(
        f"- {sector.name}：今日{_value(sector.change_pct, '%')}，近5日{_value(sector.change_5d_pct, '%')}，"
        f"成交额{_value(sector.turnover_billion, '亿元')}，领涨 {_join(sector.leading_stocks)}，领跌 {_join(sector.lagging_stocks)}。"
        for sector in sectors
    )


def _stock_group_lines(stocks: list[StockObservation], context: SectorFundContext) -> str:
    groups: dict[str, list[StockObservation]] = {}
    for stock in stocks:
        groups.setdefault(stock.theme, []).append(stock)

    lines: list[str] = []
    for theme, rows in groups.items():
        strong = [f"{stock.name}({_value(stock.change_pct, '%')})" for stock in rows if (stock.change_pct or 0) > 3]
        weak = [f"{stock.name}({_value(stock.change_pct, '%')})" for stock in rows if stock.below_ma10 or (stock.change_pct or 0) < -3]
        risks = [
            f"{stock.name}(长上影:{_bool_with_source(stock.long_upper_shadow, _source(context, f'stock.{stock.code}.long_upper_shadow'))}, "
            f"冲高回落:{_bool_with_source(stock.intraday_pullback, _source(context, f'stock.{stock.code}.intraday_pullback'))}, "
            f"跌破MA10:{_bool_with_source(stock.below_ma10, _source(context, f'stock.{stock.code}.below_ma10'))}, "
            f"来源:{_source(context, f'stock.{stock.code}.change_pct')})"
            for stock in rows
            if stock.long_upper_shadow or stock.intraday_pullback or stock.below_ma10
        ]
        lines.append(f"- {theme}：强势股 {_join(strong)}；走弱股 {_join(weak)}；长上影/炸板/跌破MA10风险 {_join(risks)}。")
    return "\n".join(lines)


def _etf_lines(etfs: list[EtfObservation], context: SectorFundContext) -> str:
    return "\n".join(
        f"- {etf.code} {etf.name}：价格{_value(etf.latest_price)}，涨跌幅{_value(etf.change_pct, '%')}，"
        f"成交额{_value(etf.turnover_billion, '亿元')}，换手率{_value(etf.turnover_rate, '%')}，"
        f"MA5={_value(etf.ma5)}，MA10={_value(etf.ma10)}，MA20={_value(etf.ma20)}，"
        f"回踩MA5={_bool_with_source(etf.pullback_ma5, _source(context, f'etf.{etf.code}.pullback_ma5'))}，"
        f"回踩MA10={_bool_with_source(etf.pullback_ma10, _source(context, f'etf.{etf.code}.pullback_ma10'))}，"
        f"跌破MA10={_bool_with_source(etf.below_ma10, _source(context, f'etf.{etf.code}.below_ma10'))}，"
        f"跌破MA20={_bool_with_source(etf.below_ma20, _source(context, f'etf.{etf.code}.below_ma20'))}，"
        f"字段来源={_source(context, f'etf.{etf.code}.latest_price')}。"
        for etf in etfs
    )


def _fund_lines(funds: list[FundHolding]) -> str:
    lines = []
    for fund in funds:
        if fund.position_role == "base":
            action = "持有为主；若科创芯片ETF回踩MA5/MA10不破，可考虑小加；跌破MA20则观察。"
        else:
            action = "继续观察强度；若存储链长上影、炸板和资金流出增多，可止盈一部分进攻仓。"
        lines.append(
            f"### {fund.code} {fund.name}\n"
            f"- 今日净值：{_value(fund.unit_nav)}\n"
            f"- 今日涨跌：{_value(fund.daily_change_pct, '%')}；近1周：{_value(fund.week_change_pct, '%')}；近1月：{_value(fund.month_change_pct, '%')}\n"
            f"- 前十大持仓：{_join(fund.top_holdings)}；占比：{_value(fund.top_holdings_weight_pct, '%')}\n"
            f"- 基金规模：{_value(fund.size_billion, '亿元')}；基金经理：{fund.manager or '未获取到'}\n"
            f"- 判断：{action}"
        )
    return "\n\n".join(lines)


def _announcement_lines(announcements: list[Announcement]) -> str:
    return "\n".join(
        f"- {ann.date} {ann.stock_name or ann.stock_code}：{ann.title}。类型：{ann.announcement_type or '未获取到'}；"
        f"方向：{ann.impact_direction}；强度：{ann.impact_strength}/5；摘要：{ann.summary or '未获取到'}"
        for ann in announcements
    )


def _field_source_lines(context: SectorFundContext) -> str:
    if not context.field_sources:
        return "- 未获取到"
    return "\n".join(
        f"- {field_name}: {source}"
        for field_name, source in sorted(context.field_sources.items())
        if source in {"real_data", "firecrawl_raw", "mock_fallback", "missing", "insufficient_history"}
    ) or "- 未获取到"


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


def render_sector_fund_report(context: SectorFundContext, score: Mapping[str, object]) -> str:
    profile = context.profile
    strongest = max(context.sectors, key=lambda item: item.change_pct or -999)
    weak_or_hot = [sector.name for sector in context.sectors if (sector.change_5d_pct or 0) > 10 or (sector.change_pct or 0) < 0]
    disclaimer = "本报告仅用于个人研究和复盘，不构成投资建议，不包含自动交易或确定性收益承诺。市场有风险，决策需自行承担。"

    body = f"""## 1. 今日总判断
- 半导体评分：{score['semiconductor_score']}
- 存储芯片评分：{score['storage_score']}
- 状态：{score['status']}
- 风险等级：{score['risk_level']}
- 今日结论：半导体/存储仍偏强，但短线波动和分化需要观察。
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
{_sector_lines(context.sectors)}

- 最强方向：{strongest.name}
- 分化/过热观察：{_join(weak_or_hot)}
- 主线判断：若半导体、存储芯片、AI芯片同时维持资金流入，仍按科技主线观察。

## 4. 资金流向
- 半导体主力净流入：{_value(context.fund_flow.semiconductor_main_inflow_billion, '亿元')}
- 存储芯片主力净流入：{_value(context.fund_flow.storage_main_inflow_billion, '亿元')}
- 电子行业主力净流入：{_value(context.fund_flow.electronics_main_inflow_billion, '亿元')}
- 芯片概念主力净流入：{_value(context.fund_flow.chip_main_inflow_billion, '亿元')}
- 5日/10日资金连续性：{_value(context.fund_flow.five_day_inflow_billion, '亿元')} / {_value(context.fund_flow.ten_day_inflow_billion, '亿元')}
- 资金判断：当前按连续流入处理；若上涨但资金转流出，应视为分歧升温。

## 5. 龙头股观察
{_stock_group_lines(context.stocks, context)}

## 6. ETF回踩观察
{_etf_lines(context.etfs, context)}

- 是否适合小加：只在回踩MA5/MA10不破、资金未转流出、核心股未集体走弱时考虑。

## 7. 我的基金持仓
{_fund_lines(context.funds)}

- 当前科技仓位：{profile.get('current_tech_position', 0):.0%}
- 建议目标仓位：{profile.get('target_position_conservative', 0):.0%}-{profile.get('target_position_aggressive', 0):.0%}
- 是否建议超过{profile.get('max_recommended_position', 0):.0%}：不建议。

## 8. 公告与新闻风险
{_announcement_lines(context.announcements)}

- 重要利好：关注重大订单、国产替代、产业政策。
- 重要利空：关注减持、业绩预亏、风险提示和高位放量分歧。
- 对板块影响：利好强化主线，利空会优先冲击进攻仓弹性。

## 9. 下个交易日策略
- 开盘快速冲高：不建议追，先看量能和龙头股是否放量承接。
- 低开后修复：10:30 前后观察半导体ETF、科创芯片ETF能否收回MA5。
- 尾盘站稳：若MA5/MA10不破且资金流仍为正，可考虑小加到目标仓位下沿。
- 放量跌破MA10：不补仓，优先降低025500这类进攻仓波动。
- 025500是否需要止盈：若存储链连续大涨后长上影、炸板、资金流出增多，可止盈一部分。
- 020671是否继续做底仓：除非科创芯片跌破MA20且资金明显流出，否则不建议轻易清仓。

## 10. 最终操作口令
已有仓位持有，不开盘追；低开修复看10:30，尾盘站稳MA5/MA10再小加。025500作为进攻仓，若存储长上影和炸板增多，可止盈一部分。020671作为底仓，除非科创芯片跌破MA20，否则不建议轻易清仓。

## 数据源状态
{chr(10).join(f"- {name}: {status}" for name, status in sorted(context.source_status.items())) or "- 未获取到"}

{_data_quality_lines(context)}

字段来源：
{_field_source_lines(context)}

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
