from __future__ import annotations

from typing import Any, Dict


def quality_prompt(core_coverage_rate: float) -> str:
    if core_coverage_rate < 40:
        return "当前核心数据覆盖率低于40%，请不要给出积极加仓或减仓建议，建议以人工核对和观察为主。"
    if core_coverage_rate < 70:
        return "当前核心数据覆盖率中等，建议谨慎判断，避免强结论。"
    return "当前核心数据覆盖率较高，可进行相对完整分析，但仍需注明不构成投资建议。"


def decision_time_prompt(decision_time: str) -> str:
    if decision_time == "1000":
        return "这是早盘预警场景。请重点判断今天是否值得在14:45再次关注，不要给出强买卖结论。"
    if decision_time == "1445":
        return "这是场外基金15:00前的关键决策窗口。请根据事实数据交由原Agent分析持有观察、谨慎加仓、暂不操作或减仓观察等可能情形。"
    if decision_time == "night":
        return "这是晚间净值校准场景。请重点比较盘中估算和真实净值的误差，评估今日模型可靠性，并提出明日观察重点。"
    return "未知决策场景，请先核对 decision_time。"


def format_fund_intraday_context(snapshot: Dict[str, Any]) -> str:
    payload = snapshot.get("snapshot", {})
    portfolio = payload.get("portfolio", {})
    funds = payload.get("funds", [])
    tracking = payload.get("tracking", {})
    diagnostics = snapshot.get("diagnostics", {})
    core_coverage = float(snapshot.get("core_coverage_rate") or 0)
    lines = [
        "【场外基金盘中分析上下文】",
        f"- 决策时间：{snapshot.get('decision_time')}",
        f"- 交易日期：{snapshot.get('trade_date')}",
        "- 当前是场外基金决策场景，15:00 前交易按当天净值，15:00 后通常顺延。",
        f"- 场景提示：{decision_time_prompt(str(snapshot.get('decision_time')))}",
        f"- 数据质量提示：{quality_prompt(core_coverage)}",
        "",
        "【组合约束】",
        f"- 组合名称：{portfolio.get('name', '未获取到')}",
        f"- 当前总仓位：{portfolio.get('total_position_pct', '未获取到')}%",
        f"- 目标仓位：{portfolio.get('target_position_pct', '未获取到')}%",
        f"- 最大仓位：{portfolio.get('max_position_pct', '未获取到')}%",
        "",
        "【持仓基金】",
    ]
    for fund in funds:
        lines.extend(
            [
                f"- {fund.get('code')} {fund.get('name')}：类型={fund.get('type')}，角色={fund.get('role')}，仓位={fund.get('position_pct')}%，风险={fund.get('risk_level')}",
                f"  跟踪ETF：{', '.join(fund.get('tracking', {}).get('etfs', [])) or '未配置'}",
                f"  跟踪指数：{', '.join(fund.get('tracking', {}).get('indices', [])) or '未配置'}",
                f"  跟踪板块：{', '.join(fund.get('tracking', {}).get('sectors', [])) or '未配置'}",
            ]
        )
    lines.extend(
        [
            "",
            "【跟踪对象汇总】",
            f"- ETF：{', '.join(tracking.get('etfs', [])) or '未获取到'}",
            f"- 指数：{', '.join(tracking.get('indices', [])) or '未获取到'}",
            f"- 重仓股篮子：{', '.join(tracking.get('stocks', [])) or '未获取到'}",
            f"- 板块：{', '.join(tracking.get('sectors', [])) or '未获取到'}",
            "",
            "【事实行情指标】",
        ]
    )
    indicators = payload.get("indicators", {})
    if indicators:
        for code, item in indicators.items():
            lines.append(
                f"- {code}：价格={item.get('latest_price')}，涨跌幅={item.get('change_pct')}%，"
                f"MA5={item.get('ma5')}，MA10={item.get('ma10')}，MA20={item.get('ma20')}，"
                f"near_ma5={item.get('near_ma5')}，near_ma10={item.get('near_ma10')}"
            )
    else:
        lines.append("- 未获取到 Baostock 结构化行情，需结合网页和人工复核。")
    lines.extend(
        [
            "",
            "【数据覆盖率与来源】",
            f"- 核心覆盖率：{snapshot.get('core_coverage_rate')}%",
            f"- 全字段覆盖率：{snapshot.get('all_coverage_rate')}%",
            f"- 数据质量：{snapshot.get('data_quality_level')}",
            f"- Baostock状态：{diagnostics.get('baostock_status')}",
            f"- Web状态：{diagnostics.get('web_status')}",
            f"- Firecrawl状态：{diagnostics.get('firecrawl_status')}",
            "",
            "【需要原分析师Agent重点判断的问题】",
            "- 数据覆盖率是否足以支持本次分析。",
            "- 基金估算、ETF、指数、板块和重仓股是否一致。",
            "- 公告、龙虎榜、新闻风险是否改变风险暴露。",
            "- 组合仓位约束下，不同基金角色是否需要区分讨论。",
            "",
            "注意：以上内容只包含事实、来源和问题，不是数据层生成的最终投资结论。",
        ]
    )
    return "\n".join(lines)
