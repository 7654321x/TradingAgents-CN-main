from .context import SectorFundContext


def format_sector_fund_context_for_agents(context: SectorFundContext) -> str:
    sector_names = "、".join(context.config.get("sectors", []))
    fund_lines = "\n".join(
        f"- {fund.code} {fund.name}：{fund.role or '未获取到'}。" for fund in context.funds
    )
    stock_lines = "\n".join(
        f"- {stock.theme} {stock.code} {stock.name}：涨跌幅 {stock.change_pct if stock.change_pct is not None else '未获取到'}%，"
        f"主力净流入 {stock.main_inflow_billion if stock.main_inflow_billion is not None else '未获取到'} 亿元。"
        for stock in context.stocks[:12]
    )

    return f"""【分析对象】
本次不是单一股票分析，而是A股半导体/存储板块与个人基金持仓分析。

【关注板块】
{sector_names}

【个人持仓】
{fund_lines}
当前科技仓位约{context.profile.get('current_tech_position', 0):.0%}，目标{context.profile.get('target_position_conservative', 0):.0%}-{context.profile.get('target_position_aggressive', 0):.0%}，不建议超过{context.profile.get('max_recommended_position', 0):.0%}。

【资金与龙头】
半导体主力净流入：{context.fund_flow.semiconductor_main_inflow_billion if context.fund_flow.semiconductor_main_inflow_billion is not None else '未获取到'} 亿元。
存储芯片主力净流入：{context.fund_flow.storage_main_inflow_billion if context.fund_flow.storage_main_inflow_billion is not None else '未获取到'} 亿元。
{stock_lines}

【分析重点】
1. 板块趋势
2. 主力资金流
3. 龙头股强弱
4. ETF回踩MA5/MA10情况
5. 公告和减持风险
6. 基金持仓风险
7. 下个交易日策略
"""

